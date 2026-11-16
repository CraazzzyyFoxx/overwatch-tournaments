"""A player's career portrait: what their Overwatch accounts show outside our tournaments, from the collected career.

The portrait is the latest row of every career series: hours, roles, hero pool, the current competitive season and
per-10-minute rates. The signals are what an organizer checks before admitting a player: a tag that no longer
resolves, a closed profile, an account with few hours at a high rank, a player who stopped playing. A profile that is
closed now shows no career, whatever was collected while it was open.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core.social import SocialProvider
from shared.schemas import rank_collection as schemas
from shared.services.rank_snapshots import fetch_latest_ow_ranks_by_account

from .domain import RATES_PLATFORM, RATES_REGION, map_division_tier_to_rank_value, rate_division
from .service import DISCIPLINE

ACCOUNT_TOTAL = "all-heroes"
COMPETITIVE = "competitive"
#: Rates per 10 minutes, as ``(category, key)`` of the career; the response names them by ``key``.
RATES = (
    ("combat", "eliminations"),
    ("combat", "final_blows"),
    ("combat", "deaths"),
    ("combat", "hero_damage_done"),
    ("assists", "healing_done"),
    ("assists", "assists"),
    ("combat", "objective_time"),
)
#: A role's mains: its most played heroes, until they cover this share of the role's time.
MAINS_SHARE = 0.8

#: ``low_hours_high_rank``: an account under this many hours (all of quick play plus the current competitive season)
#: ranked at or above Diamond 5.
LOW_HOURS = 60
HIGH_RANK = map_division_tier_to_rank_value("diamond", 5)
#: ``inactive``: Blizzard's profile has not changed for this long.
INACTIVE_AFTER = timedelta(days=30)
#: Problem accounts one health read lists; the counts cover them all.
MAX_CAREER_PROBLEMS = 200


@dataclass(frozen=True, slots=True)
class SeriesRow:
    platform: str | None
    queue: str | None
    season: int | None
    character: str
    stats: Mapping[str, Mapping[str, float]]
    captured_at: datetime


def _stat(stats: Mapping[str, Mapping[str, float]], category: str, key: str) -> float | None:
    value = (stats.get(category) or {}).get(key)
    return float(value) if value is not None else None


def _games(stats: Mapping[str, Mapping[str, float]]) -> tuple[int | None, int | None, int | None, float | None]:
    played, won, lost = (_stat(stats, "game", key) for key in ("games_played", "games_won", "games_lost"))
    winrate = round(won / played, 4) if played and won is not None else None
    return (
        None if played is None else int(played),
        None if won is None else int(won),
        None if lost is None else int(lost),
        winrate,
    )


def _rates(stats: Mapping[str, Mapping[str, float]], seconds: float) -> dict[str, float]:
    if seconds <= 0:
        return {}
    return {
        key: round(total * 600 / seconds, 2)
        for category, key in RATES
        if (total := _stat(stats, category, key)) is not None
    }


def pool_size(seconds: Iterable[float]) -> float:
    """The effective number of heroes a role is played on: ``exp`` of the entropy of their time shares.

    1 is a one-trick; an even split over four heroes is 4.
    """
    times = [value for value in seconds if value > 0]
    total = sum(times)
    if not total:
        return 0.0
    return round(math.exp(-sum(t / total * math.log(t / total) for t in times)), 2)


def mains(by_time: Sequence[tuple[str, float]]) -> list[str]:
    """The most played heroes, in order, until they cover ``MAINS_SHARE`` of the time."""
    total = sum(seconds for _, seconds in by_time)
    picked: list[str] = []
    covered = 0.0
    for character, seconds in sorted(by_time, key=lambda item: -item[1]):
        if seconds <= 0 or covered >= MAINS_SHARE * total:
            break
        picked.append(character)
        covered += seconds
    return picked


def current_rows(rows: Iterable[SeriesRow]) -> list[SeriesRow]:
    """The rows the profile shows now: every quick play row, and competitive rows of the platform's latest season.

    A hero not played this competitive season keeps its last row, dated by its old season; that is history, not the
    current season.
    """
    rows = list(rows)
    season: dict[str | None, int] = {}
    for row in rows:
        if row.queue == COMPETITIVE and row.season is not None:
            season[row.platform] = max(row.season, season.get(row.platform, row.season))
    return [row for row in rows if row.queue != COMPETITIVE or row.season == season.get(row.platform)]


Rates = tuple[float | None, float | None, float | None]


@dataclass(frozen=True, slots=True)
class MetaSource:
    """The game's latest daily rates, and where one player stands in them.

    ``rates`` maps ``(queue, division)`` (``None``: every division) to each character's ``(pick, win, ban)``
    fractions on the collected platform; ``divisions`` the player's current division per role on it.
    """

    platform: str
    captured_on: date
    rates: Mapping[tuple[str, str | None], Mapping[str, Rates]]
    divisions: Mapping[str, str]

    def of(self, queue: str | None, role: str | None) -> tuple[str | None, Mapping[str, Rates]] | None:
        """The slice a character of ``role`` is compared in: the player's division there in competitive."""
        key = queue or ""
        division = self.divisions.get(role) if key == COMPETITIVE and role else None
        if division is not None and (key, division) in self.rates:
            return division, self.rates[(key, division)]
        overall = self.rates.get((key, None))
        return (None, overall) if overall is not None else None


def _weighted(pairs: Iterable[tuple[float, float | None]]) -> float | None:
    known = [(share, value) for share, value in pairs if value is not None]
    weight = sum(share for share, _ in known)
    return round(sum(share * value for share, value in known) / weight, 4) if weight else None


def queue_portraits(
    rows: Iterable[SeriesRow], class_of: Mapping[str, str], meta: MetaSource | None = None
) -> list[schemas.CareerQueue]:
    """One portrait per platform and queue, heroes and roles ordered by time played; ``meta`` adds the game's rates."""
    grouped: dict[tuple[str | None, str | None], list[SeriesRow]] = {}
    for row in current_rows(rows):
        grouped.setdefault((row.platform, row.queue), []).append(row)

    portraits: list[schemas.CareerQueue] = []
    for (platform, queue), group in sorted(grouped.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))):
        total_row = next((row for row in group if row.character == ACCOUNT_TOTAL), None)
        heroes = [row for row in group if row.character != ACCOUNT_TOTAL]
        hero_seconds = {row.character: _stat(row.stats, "game", "time_played") or 0.0 for row in heroes}
        total_seconds = _stat(total_row.stats, "game", "time_played") if total_row is not None else None
        seconds = total_seconds or sum(hero_seconds.values())
        if not seconds:
            continue
        played, won, lost, winrate = _games(total_row.stats) if total_row is not None else (None, None, None, None)

        characters: list[schemas.CareerCharacter] = []
        for row in sorted(heroes, key=lambda r: -hero_seconds[r.character]):
            hero_time = hero_seconds[row.character]
            if hero_time <= 0:
                continue
            h_played, h_won, _, h_winrate = _games(row.stats)
            role = class_of.get(row.character)
            character_meta = None
            if meta is not None and platform == meta.platform and (found := meta.of(queue, role)) is not None:
                division, by_character = found
                if (rates := by_character.get(row.character)) is not None:
                    character_meta = schemas.CareerMeta(
                        division=division,
                        pickrate=rates[0],
                        winrate=rates[1],
                        banrate=rates[2],
                        captured_on=meta.captured_on,
                    )
            characters.append(
                schemas.CareerCharacter(
                    character=row.character,
                    role=role,
                    seconds=hero_time,
                    share=round(hero_time / seconds, 4),
                    games_played=h_played,
                    games_won=h_won,
                    winrate=h_winrate,
                    rates=_rates(row.stats, hero_time),
                    meta=character_meta,
                )
            )

        by_role: dict[str, list[tuple[str, float]]] = {}
        for character in characters:
            if character.role:
                by_role.setdefault(character.role, []).append((character.character, character.seconds))
        roles = [
            schemas.CareerRole(
                role=role,
                seconds=(role_seconds := sum(s for _, s in times)),
                share=round(role_seconds / seconds, 4),
                pool_size=pool_size(s for _, s in times),
                mains=mains(times),
            )
            for role, times in by_role.items()
        ]
        roles.sort(key=lambda role: -role.seconds)

        portraits.append(
            schemas.CareerQueue(
                platform=platform,
                queue=queue,
                season=next((row.season for row in group if row.season is not None), None),
                seconds=seconds,
                games_played=played,
                games_won=won,
                games_lost=lost,
                winrate=winrate,
                rates=_rates(total_row.stats, seconds) if total_row is not None else {},
                roles=roles,
                characters=characters,
                captured_at=max(row.captured_at for row in group),
                meta_fit=_weighted((c.share, c.meta.pickrate if c.meta else None) for c in characters),
                ban_exposure=_weighted((c.share, c.meta.banrate if c.meta else None) for c in characters),
            )
        )
    return portraits


def is_renamed(handle: str, display_name: str | None) -> bool:
    """Whether the game shows the account under another name than its stored BattleTag's."""
    return bool(display_name) and display_name.casefold() != handle.split("#", 1)[0].casefold()


def account_signals(account: schemas.CareerAccount, best_rank: int | None) -> list[schemas.CareerSignal]:
    """What an organizer should know about one account, most actionable first."""
    status = account.status
    profile = account.profile
    not_found = enums.RankCollectionStatus.not_found.value
    signals: list[schemas.CareerSignal] = []

    def signal(code: str, value: float | None = None) -> None:
        signals.append(
            schemas.CareerSignal(
                code=code, social_account_id=account.social_account_id, handle=account.handle, value=value
            )
        )

    if status is None or status == enums.RankCollectionStatus.pending.value:
        signal("never_collected")
    elif status == not_found:
        signal("previously_found" if account.last_success_at is not None else "profile_not_found")
    elif status == enums.RankCollectionStatus.private.value and (profile is None or not profile.is_public):
        # ``private`` is "no competitive rank"; only one whose career is not visible either is closed. A ranked
        # account (``ok``) shows its ranks, which a closed profile hides.
        signal("profile_private")
    # Read by its Blizzard id after the BattleTag stopped resolving: the game now shows another name.
    if profile is not None and status != not_found and is_renamed(account.handle, profile.display_name):
        signal("renamed")

    hours = sum(queue.seconds for queue in account.queues) / 3600
    if account.queues and best_rank is not None and HIGH_RANK is not None and best_rank >= HIGH_RANK:
        if hours < LOW_HOURS:
            signal("low_hours_high_rank", round(hours, 1))
    return signals


def user_signals(
    user_id: int,
    accounts: Sequence[schemas.CareerAccount],
    best_rank: Mapping[int, int],
    *,
    now: datetime,
    user_name: str | None = None,
) -> schemas.CareerUserSignals:
    """The accounts' signals, the player's competitive role shares and when they last played."""
    signals = [
        signal for account in accounts for signal in account_signals(account, best_rank.get(account.social_account_id))
    ]
    last_played_at = max(
        (a.profile.upstream_updated_at for a in accounts if a.profile and a.profile.upstream_updated_at),
        default=None,
    )
    if last_played_at is not None and last_played_at <= now - INACTIVE_AFTER:
        signals.append(schemas.CareerSignal(code="inactive"))

    seconds_by_role: dict[str, float] = {}
    for account in accounts:
        for queue in account.queues:
            if queue.queue != COMPETITIVE:
                continue
            for role in queue.roles:
                seconds_by_role[role.role] = seconds_by_role.get(role.role, 0.0) + role.seconds
    total = sum(seconds_by_role.values())
    return schemas.CareerUserSignals(
        user_id=user_id,
        user_name=user_name,
        competitive_role_shares={role: round(s / total, 4) for role, s in seconds_by_role.items()} if total else {},
        hours=round(sum(q.seconds for a in accounts for q in a.queues) / 3600, 1),
        last_played_at=last_played_at,
        signals=signals,
    )


# ── queries ───────────────────────────────────────────────────────────────────


async def _accounts(
    session: AsyncSession, user_ids: Sequence[int], account_scope: sa.Select | None, *, visible_only: bool
) -> list[Any]:
    acc, state, profile = models.SocialAccount, models.RankAccountState, models.GameAccountProfile
    query = (
        sa.select(acc.user_id, acc.id, acc.username, acc.is_primary, state.status, state.last_success_at, profile)
        .outerjoin(state, sa.and_(state.social_account_id == acc.id, state.discipline == DISCIPLINE))
        .outerjoin(profile, sa.and_(profile.social_account_id == acc.id, profile.discipline == DISCIPLINE))
        .where(acc.user_id.in_(user_ids), acc.provider == SocialProvider.BATTLENET)
        .order_by(acc.user_id, acc.is_primary.desc(), acc.id)
    )
    if account_scope is not None:
        query = query.where(acc.id.in_(account_scope))
    if visible_only:
        # The public profile's rule: an account is shown only with a global (workspace-less) visibility row.
        visibility = models.SocialAccountVisibility
        query = query.where(sa.exists().where(visibility.account_id == acc.id, visibility.workspace_id.is_(None)))
    return list((await session.execute(query)).all())


async def _latest_rows(session: AsyncSession, account_ids: Sequence[int]) -> dict[int, list[SeriesRow]]:
    """The newest row of every career series of the accounts: one ``DISTINCT ON`` over the series index."""
    snap = models.CareerSnapshot
    result = await session.execute(
        sa.select(
            snap.social_account_id,
            snap.platform,
            snap.queue,
            snap.season,
            snap.character,
            snap.stats,
            snap.captured_at,
        )
        .where(snap.discipline == DISCIPLINE, snap.social_account_id.in_(account_ids))
        .ext(distinct_on(snap.social_account_id, snap.platform, snap.queue, snap.character))
        .order_by(
            snap.social_account_id, snap.platform, snap.queue, snap.character, snap.captured_at.desc(), snap.id.desc()
        )
    )
    rows: dict[int, list[SeriesRow]] = {}
    for account_id, platform, queue, season, character, stats, captured_at in result:
        rows.setdefault(account_id, []).append(SeriesRow(platform, queue, season, character, stats, captured_at))
    return rows


async def _class_of(session: AsyncSession) -> dict[str, str]:
    entity = models.CatalogEntity
    result = await session.execute(
        sa.select(entity.slug, entity.attrs["class"].astext).where(
            entity.discipline == DISCIPLINE, entity.kind == "character"
        )
    )
    return {slug: role for slug, role in result if role}


def _fraction(percent: float | None) -> float | None:
    return None if percent is None else round(percent / 100, 4)


async def _latest_rates(session: AsyncSession) -> tuple[date, dict[tuple[str, str | None], dict[str, Rates]]] | None:
    """The newest day of the game's rates over every map, per ``(queue, division)``; ``None`` before the first."""
    rate = models.CharacterRate
    scope = (rate.discipline == DISCIPLINE, rate.platform == RATES_PLATFORM, rate.region == RATES_REGION)
    day = await session.scalar(sa.select(sa.func.max(rate.captured_on)).where(*scope))
    if day is None:
        return None
    result = await session.execute(
        sa.select(rate.queue, rate.division, rate.character, rate.pickrate, rate.winrate, rate.banrate).where(
            *scope, rate.captured_on == day, rate.map.is_(None)
        )
    )
    rates: dict[tuple[str, str | None], dict[str, Rates]] = {}
    for queue, division, character, pick, win, ban in result:
        rates.setdefault((queue or "", division), {})[character] = (_fraction(pick), _fraction(win), _fraction(ban))
    return day, rates


async def _divisions(session: AsyncSession, account_ids: Sequence[int]) -> dict[int, dict[str, str]]:
    """Each account's current rates slice per role on the rates platform; a role it is unranked in has none."""
    snap = models.UserRankSnapshot
    result = await session.execute(
        sa.select(snap.social_account_id, snap.role, snap.division, snap.is_ranked)
        .where(
            snap.discipline == DISCIPLINE,
            snap.social_account_id.in_(account_ids),
            snap.platform == RATES_PLATFORM,
        )
        .ext(distinct_on(snap.social_account_id, snap.role))
        .order_by(snap.social_account_id, snap.role, snap.captured_at.desc(), snap.id.desc())
    )
    divisions: dict[int, dict[str, str]] = {}
    for account_id, role, division, is_ranked in result:
        if role and is_ranked and (slice_ := rate_division(division)) is not None:
            divisions.setdefault(account_id, {})[role] = slice_
    return divisions


async def career_accounts(
    session: AsyncSession,
    user_ids: Sequence[int],
    *,
    account_scope: sa.Select | None = None,
    visible_only: bool = False,
    with_meta: bool = True,
) -> dict[int, list[schemas.CareerAccount]]:
    """Every linked Overwatch account of each user with its profile and portrait, primary account first.

    ``account_scope`` (a subquery of ``social_account`` ids) narrows the accounts to an admin's workspace;
    ``visible_only`` drops the accounts the player hid from their public profile; ``with_meta`` compares each
    character with the game's latest rates at the account's division. A closed profile keeps its name and avatar
    (the game shows them) and loses its career.
    """
    accounts = await _accounts(session, user_ids, account_scope, visible_only=visible_only)
    public_ids = [row[1] for row in accounts if row[6] is not None and row[6].is_public]
    rows = await _latest_rows(session, public_ids) if public_ids else {}
    class_of = await _class_of(session) if rows else {}
    latest = await _latest_rates(session) if rows and with_meta else None
    divisions = await _divisions(session, list(rows)) if latest is not None else {}
    out: dict[int, list[schemas.CareerAccount]] = {user_id: [] for user_id in user_ids}
    for user_id, account_id, handle, is_primary, status, last_success_at, profile in accounts:
        meta = (
            None if latest is None else MetaSource(RATES_PLATFORM, latest[0], latest[1], divisions.get(account_id, {}))
        )
        out[user_id].append(
            schemas.CareerAccount(
                social_account_id=account_id,
                handle=handle,
                is_primary=is_primary,
                status=status,
                last_success_at=last_success_at,
                profile=None
                if profile is None
                else schemas.CareerProfile(
                    display_name=profile.display_name,
                    avatar_url=profile.avatar_url,
                    attrs=profile.attrs,
                    is_public=profile.is_public,
                    upstream_updated_at=profile.upstream_updated_at,
                    fetched_at=profile.fetched_at,
                ),
                queues=queue_portraits(rows.get(account_id, ()), class_of, meta),
            )
        )
    return out


async def career_signals(
    session: AsyncSession, user_ids: Sequence[int], *, now: datetime, account_scope: sa.Select | None = None
) -> list[schemas.CareerUserSignals]:
    """The signals of each user, in the order asked."""
    accounts = await career_accounts(session, user_ids, account_scope=account_scope, with_meta=False)
    names = dict(
        (await session.execute(sa.select(models.User.id, models.User.name).where(models.User.id.in_(user_ids))))
        .tuples()
        .all()
    )
    id_of = {account.handle: account.social_account_id for items in accounts.values() for account in items}
    best_rank: dict[int, int] = {}
    for by_handle in (await fetch_latest_ow_ranks_by_account(session, list(user_ids), discipline=DISCIPLINE)).values():
        for handle, by_role in by_handle.items():
            if handle in id_of and by_role:
                best_rank[id_of[handle]] = max(by_role.values())
    return [
        user_signals(user_id, accounts.get(user_id, []), best_rank, now=now, user_name=names.get(user_id))
        for user_id in user_ids
    ]


@dataclass(frozen=True, slots=True)
class HealthRow:
    social_account_id: int
    user_id: int
    user_name: str
    handle: str
    status: str | None
    last_success_at: datetime | None
    display_name: str | None
    is_public: bool | None
    """``None``: never read."""


def health(rows: Iterable[HealthRow], *, now: datetime) -> schemas.CareerHealth:
    """Coverage of the players' careers and the accounts whose tags an organizer should fix."""
    not_found = enums.RankCollectionStatus.not_found.value
    pending = enums.RankCollectionStatus.pending.value
    players: set[int] = set()
    found: set[int] = set()
    public: set[int] = set()
    counts = {"accounts": 0, "found": 0, "public": 0, "not_found": 0, "pending": 0}
    lost: list[HealthRow] = []
    renamed: list[HealthRow] = []
    for row in rows:
        players.add(row.user_id)
        counts["accounts"] += 1
        if row.status is None or row.status == pending:
            counts["pending"] += 1
        elif row.status == not_found:
            counts["not_found"] += 1
            if row.last_success_at is not None:
                lost.append(row)
        elif row.is_public is not None:
            counts["found"] += 1
            found.add(row.user_id)
            if row.is_public:
                counts["public"] += 1
                public.add(row.user_id)
            if is_renamed(row.handle, row.display_name):
                renamed.append(row)
    lost.sort(key=lambda row: row.last_success_at or now, reverse=True)
    renamed.sort(key=lambda row: row.handle.casefold())
    problems = [
        schemas.CareerProblem(
            kind=kind,
            social_account_id=row.social_account_id,
            user_id=row.user_id,
            user_name=row.user_name,
            handle=row.handle,
            display_name=row.display_name,
            last_success_at=row.last_success_at,
        )
        for kind, group in (("lost", lost), ("renamed", renamed))
        for row in group
    ][:MAX_CAREER_PROBLEMS]
    return schemas.CareerHealth(
        players=len(players),
        players_found=len(found),
        players_public=len(public),
        accounts=counts["accounts"],
        accounts_found=counts["found"],
        accounts_public=counts["public"],
        accounts_not_found=counts["not_found"],
        accounts_pending=counts["pending"],
        lost=len(lost),
        renamed=len(renamed),
        problems=problems,
        generated_at=now,
    )


async def career_health(
    session: AsyncSession, *, now: datetime, account_scope: sa.Select | None = None
) -> schemas.CareerHealth:
    """Coverage of every linked account (of the workspace's players with ``account_scope``)."""
    acc, state, profile, user = models.SocialAccount, models.RankAccountState, models.GameAccountProfile, models.User
    query = (
        sa.select(
            acc.id,
            acc.user_id,
            user.name,
            acc.username,
            state.status,
            state.last_success_at,
            profile.display_name,
            profile.is_public,
        )
        .join(user, user.id == acc.user_id)
        .outerjoin(state, sa.and_(state.social_account_id == acc.id, state.discipline == DISCIPLINE))
        .outerjoin(profile, sa.and_(profile.social_account_id == acc.id, profile.discipline == DISCIPLINE))
        .where(acc.provider == SocialProvider.BATTLENET)
    )
    if account_scope is not None:
        query = query.where(acc.id.in_(account_scope))
    return health((HealthRow(*row) for row in await session.execute(query)), now=now)
