"""DB layer for OverFast rank collection: state bookkeeping + snapshot writes.

Transaction-neutral — functions mutate/flush the session; the caller commits.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from shared.core import enums
from shared.schemas.settings import RankCollectionConfig
from sqlalchemy.ext.asyncio import AsyncSession

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


def battle_tag_to_slug(battle_tag: str) -> str:
    return battle_tag.replace("#", "-")


async def ensure_state(
    session: AsyncSession,
    battle_tag_id: int,
    battle_tag: str,
    *,
    priority_tier: int = 0,
) -> models.BattleTagRankState:
    """Get-or-create the collection state for a battle tag, bumping priority."""
    state = await session.scalar(
        sa.select(models.BattleTagRankState).where(
            models.BattleTagRankState.battle_tag_id == battle_tag_id
        )
    )
    if state is None:
        state = models.BattleTagRankState(
            battle_tag_id=battle_tag_id,
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


async def promote_user_tags(
    session: AsyncSession, user_id: int, *, tier: int
) -> list[tuple[int, str]]:
    """Ensure + promote every battle tag of ``user_id`` to at least ``tier``.

    Returns the list of ``(battle_tag_id, battle_tag)`` touched.
    """
    rows = (
        await session.execute(
            sa.select(models.UserBattleTag.id, models.UserBattleTag.battle_tag).where(
                models.UserBattleTag.user_id == user_id
            )
        )
    ).all()
    tags = [(battle_tag_id, battle_tag) for battle_tag_id, battle_tag in rows]
    for battle_tag_id, battle_tag in tags:
        await ensure_state(session, battle_tag_id, battle_tag, priority_tier=tier)
    return tags


async def seed_states_for_all_battle_tags(session: AsyncSession) -> int:
    """Insert a (tier 0) state row for every battle tag that lacks one."""
    bt = models.UserBattleTag
    state = models.BattleTagRankState
    missing = (
        sa.select(
            bt.id.label("battle_tag_id"),
            bt.battle_tag.label("battle_tag"),
            sa.func.replace(bt.battle_tag, "#", "-").label("player_id_slug"),
        )
        .where(~sa.exists().where(state.battle_tag_id == bt.id))
    )
    result = await session.execute(
        sa.insert(state).from_select(
            ["battle_tag_id", "battle_tag", "player_id_slug"], missing
        )
    )
    return result.rowcount or 0


async def seed_states_from_registrations(session: AsyncSession) -> int:
    """Backfill (tier 1) state rows for battle tags referenced by registrations.

    Covers the ``registrations_only`` scope: any ``UserBattleTag`` belonging to a
    user who has a (non-deleted) registration in an **active** tournament (not
    ``completed``/``archived``), or whose tag matches such a registration, gets a
    state row so it becomes eligible. The approval hook only promotes tags on
    *new* approvals — this picks up the existing backlog so enabling collection
    starts working immediately. Finished/archived tournaments are excluded so the
    collector doesn't poll their players forever.
    """
    bt = models.UserBattleTag
    reg = models.BalancerRegistration
    tournament = models.Tournament
    state = models.BattleTagRankState

    active_regs = (
        sa.select(reg.user_id, reg.battle_tag)
        .join(tournament, tournament.id == reg.tournament_id)
        .where(
            reg.deleted_at.is_(None),
            tournament.status.notin_(INACTIVE_TOURNAMENT_STATUSES),
        )
        .subquery()
    )
    reg_user_ids = sa.select(active_regs.c.user_id).where(active_regs.c.user_id.isnot(None))
    reg_tags = sa.select(active_regs.c.battle_tag).where(active_regs.c.battle_tag.isnot(None))
    missing = sa.select(
        bt.id.label("battle_tag_id"),
        bt.battle_tag.label("battle_tag"),
        sa.func.replace(bt.battle_tag, "#", "-").label("player_id_slug"),
        sa.literal(1).label("priority_tier"),
    ).where(
        sa.or_(bt.user_id.in_(reg_user_ids), bt.battle_tag.in_(reg_tags)),
        ~sa.exists().where(state.battle_tag_id == bt.id),
    )
    result = await session.execute(
        sa.insert(state).from_select(
            ["battle_tag_id", "battle_tag", "player_id_slug", "priority_tier"], missing
        )
    )
    return result.rowcount or 0


async def select_and_claim_due(
    session: AsyncSession,
    *,
    limit: int,
    scope: str,
    interval_seconds: int,
    now: datetime | None = None,
) -> Sequence[models.BattleTagRankState]:
    """Pick the most-due tags, claim them (push out ``next_eligible_at``), return them.

    Ordering: highest ``priority_tier`` first, then least-recently-checked. The
    claim prevents the next scheduler tick from re-selecting a tag before its
    fetch has been processed (Redis dedup is the second line of defense).
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
    if rows:
        claim_until = now + timedelta(seconds=interval_seconds)
        await session.execute(
            sa.update(state)
            .where(state.id.in_([r.id for r in rows]))
            .values(next_eligible_at=claim_until)
        )
    return rows


async def _user_id_for_tag(session: AsyncSession, battle_tag_id: int) -> int | None:
    return await session.scalar(
        sa.select(models.UserBattleTag.user_id).where(models.UserBattleTag.id == battle_tag_id)
    )


async def record_result(
    session: AsyncSession,
    *,
    battle_tag_id: int,
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
    state = await ensure_state(session, battle_tag_id, battle_tag)
    state.last_checked_at = now
    state.last_error = None

    status = result.status
    written = 0

    if status == enums.RankCollectionStatus.ok:
        user_id = await _user_id_for_tag(session, battle_tag_id)
        last_snapshot: models.UserRankSnapshot | None = None
        if user_id is not None:
            for parsed in result.ranks:
                rank_value = mapping.map_division_tier_to_rank_value(
                    parsed.division, parsed.tier, lookup
                )
                snapshot = models.UserRankSnapshot(
                    user_id=user_id,
                    battle_tag_id=battle_tag_id,
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
        state.next_eligible_at = now + timedelta(seconds=config.interval_seconds)
    elif status == enums.RankCollectionStatus.private:
        state.status = enums.RankCollectionStatus.private.value
        state.consecutive_failures = 0
        state.next_eligible_at = now + timedelta(
            seconds=config.interval_seconds * PRIVATE_INTERVAL_FACTOR
        )
    elif status == enums.RankCollectionStatus.not_found:
        state.status = enums.RankCollectionStatus.not_found.value
        state.consecutive_failures = 0
        state.next_eligible_at = now + timedelta(
            seconds=config.interval_seconds * NOT_FOUND_INTERVAL_FACTOR
        )
    else:  # error
        return await record_failure(
            session,
            battle_tag_id=battle_tag_id,
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
    battle_tag_id: int,
    battle_tag: str,
    status: enums.RankCollectionStatus,
    error: str | None,
    config: RankCollectionConfig,
    now: datetime | None = None,
) -> int:
    """Apply exponential backoff for a transient failure; auto-disable dead tags."""
    now = now or _now()
    state = await ensure_state(session, battle_tag_id, battle_tag)
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
    battle_tag_id: int,
    delay_seconds: int,
    now: datetime | None = None,
) -> None:
    """Push a tag's next eligibility out (used when a global cooldown is active)."""
    now = now or _now()
    await session.execute(
        sa.update(models.BattleTagRankState)
        .where(models.BattleTagRankState.battle_tag_id == battle_tag_id)
        .values(next_eligible_at=now + timedelta(seconds=delay_seconds))
    )
