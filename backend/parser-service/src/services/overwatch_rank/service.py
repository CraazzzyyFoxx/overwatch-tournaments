"""DB layer for OverFast rank collection: state bookkeeping + snapshot writes.

Transaction-neutral — functions mutate/flush the session; the caller commits.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums
from shared.core.social import SocialProvider, normalize_social_handle
from shared.schemas.settings import RankCollectionConfig
from src import models

from . import mapping
from .schemas import RankFetchResult

# Multipliers applied to the base interval for non-error terminal states so we
# poll quiet accounts less often.
PRIVATE_INTERVAL_FACTOR = 4
NOT_FOUND_INTERVAL_FACTOR = 8
MAX_BACKOFF_SECONDS = 6 * 60 * 60

# Tournament statuses whose registrations we do NOT backfill — finished events
# shouldn't keep the collector polling their players forever.
INACTIVE_TOURNAMENT_STATUSES = (
    enums.TournamentStatus.COMPLETED.value,
    enums.TournamentStatus.ARCHIVED.value,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _jittered_interval(base_seconds: float, jitter_fraction: float) -> float:
    """Spread a reschedule delay over ``[base, base*(1+fraction)]``.

    Keeps tags that were processed in the same tick from recurring at the same
    instant (standing waves). ``jitter_fraction <= 0`` returns ``base`` unchanged.
    """
    if jitter_fraction <= 0:
        return float(base_seconds)
    return base_seconds + random.random() * base_seconds * jitter_fraction


def _seed_next_eligible(interval_seconds: int) -> sa.ColumnElement[datetime]:
    """SQL expression spreading a fresh seed across ``[now, now+interval]``.

    Seeding with ``next_eligible_at = NULL`` makes the whole population due at
    once (thundering herd on first enable); a per-row random offset distributes
    the initial cycle evenly instead.
    """
    return sa.func.now() + sa.func.make_interval(0, 0, 0, 0, 0, 0, sa.func.random() * interval_seconds)


async def log_fetch(
    session: AsyncSession,
    *,
    social_account_id: int | None,
    battle_tag: str,
    status: str,
    source: str,
    error: str | None = None,
    snapshots_written: int = 0,
) -> None:
    """Append a worker fetch attempt to the task-history log (caller commits)."""
    session.add(
        models.RankFetchLog(
            social_account_id=social_account_id,
            battle_tag=battle_tag,
            status=str(status),
            source=source,
            error=error[:2000] if error else None,
            snapshots_written=snapshots_written,
        )
    )


def battle_tag_to_slug(battle_tag: str) -> str:
    return battle_tag.replace("#", "-")


async def ensure_state(
    session: AsyncSession,
    social_account_id: int,
    battle_tag: str,
    *,
    priority_tier: int = 0,
) -> models.BattleTagRankState:
    """Get-or-create the collection state for a battle tag, bumping priority."""
    state = await session.scalar(
        sa.select(models.BattleTagRankState).where(models.BattleTagRankState.social_account_id == social_account_id)
    )
    if state is None:
        state = models.BattleTagRankState(
            social_account_id=social_account_id,
            battle_tag=battle_tag,
            player_id_slug=battle_tag_to_slug(battle_tag),
            priority_tier=priority_tier,
        )
        session.add(state)
        await session.flush()
        return state

    if priority_tier > state.priority_tier:
        state.priority_tier = priority_tier
        await session.flush()
    return state


async def resolve_user_registration_targets(
    session: AsyncSession,
    user_id: int,
    registered_normalized: set[str],
    extra_accounts: int,
) -> list[tuple[int, str]]:
    """A user's collection pool: their registered tags + up to N extra accounts.

    ``registered_normalized`` is the set of normalized battlenet handles the
    player entered (main + smurfs). Every matching ``social_account`` is
    included; then up to ``extra_accounts`` of their *other* battlenet accounts
    (lowest id first, deterministic).
    """
    rows = (
        await session.execute(
            sa.select(
                models.SocialAccount.id,
                models.SocialAccount.username,
                models.SocialAccount.username_normalized,
            )
            .where(
                models.SocialAccount.user_id == user_id,
                models.SocialAccount.provider == SocialProvider.BATTLENET,
            )
            .order_by(models.SocialAccount.id.asc())
        )
    ).all()
    targets: list[tuple[int, str]] = []
    extras = 0
    for account_id, username, normalized in rows:
        if normalized and normalized in registered_normalized:
            targets.append((account_id, username))
        elif extras < extra_accounts:
            targets.append((account_id, username))
            extras += 1
    return targets


async def resolve_registration_targets(
    session: AsyncSession,
    *,
    registration_id: int | None,
    fallback_battle_tag: str | None,
    user_id: int,
    extra_accounts: int,
) -> list[tuple[int, str]]:
    """Collection pool for one approved registration (registered tags + N extra)."""
    registered_normalized: set[str] = set()
    registration = (
        await session.get(models.BalancerRegistration, registration_id) if registration_id is not None else None
    )
    if registration is not None:
        if registration.battle_tag:
            registered_normalized.add(normalize_social_handle(SocialProvider.BATTLENET, registration.battle_tag))
        for smurf in registration.smurf_tags_json or []:
            if smurf:
                registered_normalized.add(normalize_social_handle(SocialProvider.BATTLENET, str(smurf)))
    elif fallback_battle_tag:
        registered_normalized.add(normalize_social_handle(SocialProvider.BATTLENET, fallback_battle_tag))

    return await resolve_user_registration_targets(session, user_id, registered_normalized, extra_accounts)


async def seed_states_for_all_battle_tags(session: AsyncSession, *, interval_seconds: int) -> int:
    """Insert a (tier 0) state row for every battle tag that lacks one.

    New rows are seeded with a jittered ``next_eligible_at`` spread across
    ``[now, now+interval_seconds]`` so the first collection cycle is even rather
    than a thundering herd.
    """
    acc = models.SocialAccount
    state = models.BattleTagRankState
    missing = sa.select(
        acc.id.label("social_account_id"),
        acc.username.label("battle_tag"),
        sa.func.replace(acc.username, "#", "-").label("player_id_slug"),
        _seed_next_eligible(interval_seconds).label("next_eligible_at"),
    ).where(
        acc.provider == SocialProvider.BATTLENET,
        acc.username.like("%#%"),
        ~sa.exists().where(state.social_account_id == acc.id),
    )
    result = await session.execute(
        sa.insert(state).from_select(
            ["social_account_id", "battle_tag", "player_id_slug", "next_eligible_at"],
            missing,
        )
    )
    return result.rowcount or 0


async def _registration_collection_targets(session: AsyncSession, extra_accounts: int) -> set[int]:
    """``social_account_id`` set to collect under ``registrations_only``.

    For active-tournament registrations: the tags the player *entered* (main +
    smurfs), matched to battlenet ``social_account`` rows, plus up to
    ``extra_accounts`` of each registrant's *other* battle.net accounts.
    Tournaments that are ``completed``/``archived`` are excluded.
    """
    reg = models.BalancerRegistration
    tournament = models.Tournament
    acc = models.SocialAccount

    # Registrations are anchored on workspace_member (dbarch02 dropped
    # user_id); LEFT JOIN so member-less rows still contribute their entered
    # battle tags (their player_id resolves to None, exactly like the old
    # NULL user_id).
    member = models.WorkspaceMember
    rows = (
        await session.execute(
            sa.select(member.player_id, reg.battle_tag, reg.smurf_tags_json)
            .select_from(reg)
            .join(tournament, tournament.id == reg.tournament_id)
            .outerjoin(member, member.id == reg.workspace_member_id)
            .where(
                reg.deleted_at.is_(None),
                tournament.status.notin_(INACTIVE_TOURNAMENT_STATUSES),
            )
        )
    ).all()

    registered_normalized: set[str] = set()
    user_ids: set[int] = set()
    for user_id, battle_tag, smurfs in rows:
        if user_id is not None:
            user_ids.add(user_id)
        if battle_tag:
            registered_normalized.add(normalize_social_handle(SocialProvider.BATTLENET, battle_tag))
        for smurf in smurfs or []:
            if smurf:
                registered_normalized.add(normalize_social_handle(SocialProvider.BATTLENET, str(smurf)))

    target_ids: set[int] = set()

    # Tags explicitly registered (matches by normalized handle; covers regs without a user).
    if registered_normalized:
        ids = (
            await session.scalars(
                sa.select(acc.id).where(
                    acc.provider == SocialProvider.BATTLENET,
                    acc.username_normalized.in_(registered_normalized),
                )
            )
        ).all()
        target_ids.update(ids)

    # Per registrant user: registered accounts + up to N extra accounts (lowest id first).
    if user_ids:
        user_rows = (
            await session.execute(
                sa.select(acc.user_id, acc.id, acc.username_normalized)
                .where(
                    acc.user_id.in_(user_ids),
                    acc.provider == SocialProvider.BATTLENET,
                )
                .order_by(acc.user_id.asc(), acc.id.asc())
            )
        ).all()
        extras_per_user: dict[int, int] = {}
        for uid, account_id, normalized in user_rows:
            if normalized and normalized in registered_normalized:
                target_ids.add(account_id)
            elif extras_per_user.get(uid, 0) < extra_accounts:
                target_ids.add(account_id)
                extras_per_user[uid] = extras_per_user.get(uid, 0) + 1

    return target_ids


async def seed_states_from_registrations(
    session: AsyncSession, *, interval_seconds: int, extra_accounts: int = 0
) -> int:
    """Sync tier-1 state to the registration collection pool (registrations_only).

    Keeps ``priority_tier == 1`` equal to the registered tags (main + smurfs) of
    active-tournament registrations plus up to ``extra_accounts`` other accounts
    per registrant:

    - inserts a tier-1 state row for newly-targeted tags,
    - promotes an existing tier-0 row back to tier 1 when its tag enters the pool,
    - demotes tier-1 rows that leave the pool (e.g. tournament completed) to tier 0.

    Tier 2 (manual triggers / approval hook) is never touched. Returns the number
    of new state rows inserted.
    """
    acc = models.SocialAccount
    state = models.BattleTagRankState

    target_ids = await _registration_collection_targets(session, extra_accounts)

    # Demote tier-1 rows that are no longer in the registration pool.
    demote = sa.update(state).where(state.priority_tier == 1)
    if target_ids:
        demote = demote.where(state.social_account_id.notin_(target_ids))
    await session.execute(demote.values(priority_tier=0))

    if not target_ids:
        return 0

    # Promote existing tier-0 rows that are now in the pool.
    await session.execute(
        sa.update(state)
        .where(state.priority_tier == 0, state.social_account_id.in_(target_ids))
        .values(priority_tier=1)
    )

    # Insert tier-1 rows for pool accounts that have no state row yet, spread
    # across the interval (see ``seed_states_for_all_battle_tags``).
    missing = sa.select(
        acc.id.label("social_account_id"),
        acc.username.label("battle_tag"),
        sa.func.replace(acc.username, "#", "-").label("player_id_slug"),
        sa.literal(1).label("priority_tier"),
        _seed_next_eligible(interval_seconds).label("next_eligible_at"),
    ).where(
        acc.id.in_(target_ids),
        ~sa.exists().where(state.social_account_id == acc.id),
    )
    result = await session.execute(
        sa.insert(state).from_select(
            [
                "social_account_id",
                "battle_tag",
                "player_id_slug",
                "priority_tier",
                "next_eligible_at",
            ],
            missing,
        )
    )
    return result.rowcount or 0


async def count_in_scope(session: AsyncSession, *, scope: str) -> int:
    """Count non-disabled tags eligible for collection under ``scope``.

    Sizes the self-pacing batch off the *whole* in-scope population (not the
    currently-due subset, which would self-amplify into bursts during a backlog).
    """
    state = models.BattleTagRankState
    query = (
        sa.select(sa.func.count()).select_from(state).where(state.status != enums.RankCollectionStatus.disabled.value)
    )
    if scope == "registrations_only":
        query = query.where(state.priority_tier > 0)
    return int(await session.scalar(query) or 0)


async def select_and_claim_due(
    session: AsyncSession,
    *,
    limit: int,
    scope: str,
    interval_seconds: int,
    jitter_fraction: float = 0.0,
    now: datetime | None = None,
) -> Sequence[models.BattleTagRankState]:
    """Pick the most-due tags, claim them (push out ``next_eligible_at``), return them.

    Ordering: highest ``priority_tier`` first, then least-recently-checked. The
    claim prevents the next scheduler tick from re-selecting a tag before its
    fetch has been processed (Redis dedup is the second line of defense). The
    claim is the reschedule path for events a worker never processes (lost
    message / worker down), so it is jittered too — otherwise that recovery path
    would re-cluster the batch.
    """
    now = now or _now()
    state = models.BattleTagRankState
    query = sa.select(state).where(
        state.status != enums.RankCollectionStatus.disabled.value,
        sa.or_(state.next_eligible_at.is_(None), state.next_eligible_at <= now),
    )
    if scope == "registrations_only":
        query = query.where(state.priority_tier > 0)
    query = query.order_by(
        state.priority_tier.desc(),
        state.last_checked_at.asc().nulls_first(),
    ).limit(limit)

    rows = (await session.scalars(query)).all()
    for row in rows:
        row.next_eligible_at = now + timedelta(seconds=_jittered_interval(interval_seconds, jitter_fraction))
    return rows


async def _user_id_for_tag(session: AsyncSession, social_account_id: int) -> int | None:
    return await session.scalar(
        sa.select(models.SocialAccount.user_id).where(models.SocialAccount.id == social_account_id)
    )


async def record_result(
    session: AsyncSession,
    *,
    social_account_id: int,
    battle_tag: str,
    source: str,
    result: RankFetchResult,
    lookup: mapping.RankLookup,
    mapping_version: str,
    config: RankCollectionConfig,
    now: datetime | None = None,
) -> int:
    """Persist a fetch outcome: snapshot rows (on success) + state update.

    Returns the number of snapshot rows written.
    """
    now = now or _now()
    state = await ensure_state(session, social_account_id, battle_tag)
    state.last_checked_at = now
    state.last_error = None

    status = result.status
    written = 0

    if status == enums.RankCollectionStatus.ok:
        user_id = await _user_id_for_tag(session, social_account_id)
        last_snapshot: models.UserRankSnapshot | None = None
        if user_id is not None:
            for parsed in result.ranks:
                rank_value = mapping.map_division_tier_to_rank_value(parsed.division, parsed.tier, lookup)
                snapshot = models.UserRankSnapshot(
                    user_id=user_id,
                    social_account_id=social_account_id,
                    battle_tag=battle_tag,
                    platform=parsed.platform,
                    role=parsed.role,
                    division=parsed.division,
                    tier=parsed.tier,
                    season=parsed.season,
                    rank_value=rank_value,
                    mapping_version=mapping_version,
                    is_ranked=parsed.is_ranked,
                    raw_payload=parsed.raw,
                    captured_at=now,
                    source=source,
                )
                session.add(snapshot)
                last_snapshot = snapshot
                written += 1
            await session.flush()
        state.status = enums.RankCollectionStatus.ok.value
        state.last_success_at = now
        state.consecutive_failures = 0
        if last_snapshot is not None:
            state.last_snapshot_id = last_snapshot.id
        state.next_eligible_at = now + timedelta(
            seconds=_jittered_interval(config.interval_seconds, config.jitter_fraction)
        )
    elif status == enums.RankCollectionStatus.private:
        state.status = enums.RankCollectionStatus.private.value
        state.consecutive_failures = 0
        state.next_eligible_at = now + timedelta(
            seconds=_jittered_interval(
                config.interval_seconds * PRIVATE_INTERVAL_FACTOR,
                config.jitter_fraction,
            )
        )
    elif status == enums.RankCollectionStatus.not_found:
        state.status = enums.RankCollectionStatus.not_found.value
        state.consecutive_failures = 0
        state.next_eligible_at = now + timedelta(
            seconds=_jittered_interval(
                config.interval_seconds * NOT_FOUND_INTERVAL_FACTOR,
                config.jitter_fraction,
            )
        )
    else:  # error
        return await record_failure(
            session,
            social_account_id=social_account_id,
            battle_tag=battle_tag,
            status=enums.RankCollectionStatus.error,
            error=result.error,
            config=config,
            now=now,
        )

    await session.flush()
    return written


async def record_failure(
    session: AsyncSession,
    *,
    social_account_id: int,
    battle_tag: str,
    status: enums.RankCollectionStatus,
    error: str | None,
    config: RankCollectionConfig,
    now: datetime | None = None,
) -> int:
    """Apply exponential backoff for a transient failure; auto-disable dead tags."""
    now = now or _now()
    state = await ensure_state(session, social_account_id, battle_tag)
    state.last_checked_at = now
    state.last_error = (error or "")[:2000] or None
    state.consecutive_failures = (state.consecutive_failures or 0) + 1

    if state.consecutive_failures >= config.max_consecutive_failures:
        state.status = enums.RankCollectionStatus.disabled.value
        state.next_eligible_at = None
    else:
        backoff = min(
            config.backoff_base_seconds * (2 ** (state.consecutive_failures - 1)),
            MAX_BACKOFF_SECONDS,
        )
        state.status = status.value
        state.next_eligible_at = now + timedelta(seconds=backoff)
    await session.flush()
    return 0


async def defer_tag(
    session: AsyncSession,
    *,
    social_account_id: int,
    delay_seconds: int,
    now: datetime | None = None,
) -> None:
    """Push a tag's next eligibility out (used when a global cooldown is active)."""
    now = now or _now()
    await session.execute(
        sa.update(models.BattleTagRankState)
        .where(models.BattleTagRankState.social_account_id == social_account_id)
        .values(next_eligible_at=now + timedelta(seconds=delay_seconds))
    )
