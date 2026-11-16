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
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core.social import SocialProvider
from shared.schemas import rank_collection as schemas
from shared.services.rank_snapshots import fetch_latest_ow_ranks_by_account

from .domain import map_division_tier_to_rank_value
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


def queue_portraits(rows: Iterable[SeriesRow], class_of: Mapping[str, str]) -> list[schemas.CareerQueue]:
    """One portrait per platform and queue, heroes and roles ordered by time played."""
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
            characters.append(
                schemas.CareerCharacter(
                    character=row.character,
                    role=class_of.get(row.character),
                    seconds=hero_time,
                    share=round(hero_time / seconds, 4),
                    games_played=h_played,
                    games_won=h_won,
                    winrate=h_winrate,
                    rates=_rates(row.stats, hero_time),
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
            )
        )
    return portraits


def account_signals(account: schemas.CareerAccount, best_rank: int | None) -> list[schemas.CareerSignal]:
    """What an organizer should know about one account, most actionable first."""
    sid = account.social_account_id
    status = account.status
    profile = account.profile
    not_found = enums.RankCollectionStatus.not_found.value
    signals: list[schemas.CareerSignal] = []
    if status is None or status == enums.RankCollectionStatus.pending.value:
        signals.append(schemas.CareerSignal(code="never_collected", social_account_id=sid))
    elif status == not_found:
        code = "previously_found" if account.last_success_at is not None else "profile_not_found"
        signals.append(schemas.CareerSignal(code=code, social_account_id=sid))
    elif status == enums.RankCollectionStatus.private.value and (profile is None or not profile.is_public):
        # ``private`` is "no competitive rank"; only one whose career is not visible either is closed. A ranked
        # account (``ok``) shows its ranks, which a closed profile hides.
        signals.append(schemas.CareerSignal(code="profile_private", social_account_id=sid))
    # Read by its Blizzard id after the BattleTag stopped resolving: the game now shows another name.
    if profile is not None and profile.display_name and status != not_found:
        if profile.display_name.casefold() != account.handle.split("#", 1)[0].casefold():
            signals.append(schemas.CareerSignal(code="renamed", social_account_id=sid))

    hours = sum(queue.seconds for queue in account.queues) / 3600
    if account.queues and best_rank is not None and HIGH_RANK is not None and best_rank >= HIGH_RANK:
        if hours < LOW_HOURS:
            signals.append(
                schemas.CareerSignal(code="low_hours_high_rank", social_account_id=sid, value=round(hours, 1))
            )
    return signals


def user_signals(
    user_id: int, accounts: Sequence[schemas.CareerAccount], best_rank: Mapping[int, int], *, now: datetime
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


async def career_accounts(
    session: AsyncSession,
    user_ids: Sequence[int],
    *,
    account_scope: sa.Select | None = None,
    visible_only: bool = False,
) -> dict[int, list[schemas.CareerAccount]]:
    """Every linked Overwatch account of each user with its profile and portrait, primary account first.

    ``account_scope`` (a subquery of ``social_account`` ids) narrows the accounts to an admin's workspace;
    ``visible_only`` drops the accounts the player hid from their public profile. A closed profile keeps its name and
    avatar (the game shows them) and loses its career.
    """
    accounts = await _accounts(session, user_ids, account_scope, visible_only=visible_only)
    public_ids = [row[1] for row in accounts if row[6] is not None and row[6].is_public]
    rows = await _latest_rows(session, public_ids) if public_ids else {}
    class_of = await _class_of(session) if rows else {}
    out: dict[int, list[schemas.CareerAccount]] = {user_id: [] for user_id in user_ids}
    for user_id, account_id, handle, is_primary, status, last_success_at, profile in accounts:
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
                queues=queue_portraits(rows.get(account_id, ()), class_of),
            )
        )
    return out


async def career_signals(
    session: AsyncSession, user_ids: Sequence[int], *, now: datetime, account_scope: sa.Select | None = None
) -> list[schemas.CareerUserSignals]:
    """The signals of each user, in the order asked."""
    accounts = await career_accounts(session, user_ids, account_scope=account_scope)
    id_of = {account.handle: account.social_account_id for items in accounts.values() for account in items}
    best_rank: dict[int, int] = {}
    for by_handle in (await fetch_latest_ow_ranks_by_account(session, list(user_ids), discipline=DISCIPLINE)).values():
        for handle, by_role in by_handle.items():
            if handle in id_of and by_role:
                best_rank[id_of[handle]] = max(by_role.values())
    return [user_signals(user_id, accounts.get(user_id, []), best_rank, now=now) for user_id in user_ids]
