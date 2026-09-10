from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core.social import SocialProvider
from shared.repository.base import BaseRepository


def workspace_account_ids(workspace_id: int) -> sa.Select:
    """Battle-tag ``social_account`` ids owned by players of ``workspace_id``.

    Rank rows key on ``players.social_account``, which has no workspace column —
    a battle tag belongs to a player, and a player reaches a workspace through
    ``workspace_member``. This subquery is that hop, and it is what lets a
    workspace-scoped admin see the collection health of their own roster without
    seeing every other tenant's accounts.
    """
    return (
        sa.select(models.SocialAccount.id)
        .join(models.WorkspaceMember, models.WorkspaceMember.player_id == models.SocialAccount.user_id)
        .where(
            models.WorkspaceMember.workspace_id == workspace_id,
            models.SocialAccount.provider == SocialProvider.BATTLENET,
        )
    )


def jittered_interval(base_seconds: float, jitter_fraction: float) -> float:
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


class RankSnapshotRepository(BaseRepository[models.UserRankSnapshot]):
    """``overwatch_rank.rank_snapshot`` — one row per observed rank change, per role/platform."""

    def __init__(self) -> None:
        super().__init__(models.UserRankSnapshot)


class RankFetchLogRepository(BaseRepository[models.RankFetchLog]):
    """``ranks.rank_fetch_log`` — append-only worker fetch-attempt history."""

    def __init__(self) -> None:
        super().__init__(models.RankFetchLog)

    async def delete_older_than(self, session: AsyncSession, cutoff: datetime) -> int:
        """Drop rows created before ``cutoff``; returns how many went.

        The task feed reads the newest few hundred rows and the health dashboard
        the last 24 hours, so nothing older than the retention window is ever
        read. ``ix_fetch_log_created_at`` exists for this range.
        """
        result = await session.execute(sa.delete(models.RankFetchLog).where(models.RankFetchLog.created_at < cutoff))
        return int(result.rowcount or 0)


class BattleTagRankStateRepository(BaseRepository[models.BattleTagRankState]):
    """``ranks.battle_tag_rank_state`` — collection bookkeeping, one row per
    collected battlenet account.
    """

    def __init__(self) -> None:
        super().__init__(models.BattleTagRankState)

    async def get_by_social_account_id(
        self, session: AsyncSession, social_account_id: int
    ) -> models.BattleTagRankState | None:
        return await session.scalar(self.select().where(self.model.social_account_id == social_account_id))

    async def create_for_tag(
        self,
        session: AsyncSession,
        *,
        social_account_id: int,
        battle_tag: str,
        player_id_slug: str,
        priority_tier: int = 0,
    ) -> models.BattleTagRankState:
        return await self.create(
            session,
            models.BattleTagRankState(
                social_account_id=social_account_id,
                battle_tag=battle_tag,
                player_id_slug=player_id_slug,
                priority_tier=priority_tier,
            ),
        )

    async def bump_priority(
        self, session: AsyncSession, state: models.BattleTagRankState, priority_tier: int
    ) -> models.BattleTagRankState:
        if priority_tier > state.priority_tier:
            state.priority_tier = priority_tier
            await session.flush()
        return state

    async def bulk_seed_missing(
        self,
        session: AsyncSession,
        *,
        interval_seconds: int,
        target_ids: Sequence[int] | set[int] | None = None,
        priority_tier: int = 0,
    ) -> int:
        """Insert a state row for every battle tag in scope that lacks one.

        ``target_ids is None`` seeds every battlenet account (tier 0 — the
        ``scope="all"`` collector sweep, ``seed_states_for_all_battle_tags``); a
        concrete ``target_ids`` seeds only that set (tier 1 — the registration
        pool, ``seed_states_from_registrations``). Either way the new rows get a
        jittered ``next_eligible_at`` spread across ``[now, now+interval_seconds]``
        so the first collection cycle is even rather than a thundering herd.
        """
        acc = models.SocialAccount
        state = self.model

        columns = ["social_account_id", "battle_tag", "player_id_slug"]
        select_cols: list[sa.ColumnElement] = [
            acc.id.label("social_account_id"),
            acc.username.label("battle_tag"),
            sa.func.replace(acc.username, "#", "-").label("player_id_slug"),
        ]
        if priority_tier:
            columns.append("priority_tier")
            select_cols.append(sa.literal(priority_tier).label("priority_tier"))
        columns.append("next_eligible_at")
        select_cols.append(_seed_next_eligible(interval_seconds).label("next_eligible_at"))

        if target_ids is not None:
            where_clauses = [acc.id.in_(target_ids), ~sa.exists().where(state.social_account_id == acc.id)]
        else:
            where_clauses = [
                acc.provider == SocialProvider.BATTLENET,
                acc.username.like("%#%"),
                ~sa.exists().where(state.social_account_id == acc.id),
            ]
        missing = sa.select(*select_cols).where(*where_clauses)
        result = await session.execute(sa.insert(state).from_select(columns, missing))
        return result.rowcount or 0

    async def demote_tier1_not_in(self, session: AsyncSession, target_ids: Sequence[int] | set[int] | None) -> None:
        state = self.model
        demote = sa.update(state).where(state.priority_tier == 1)
        if target_ids:
            demote = demote.where(state.social_account_id.notin_(target_ids))
        await session.execute(demote.values(priority_tier=0))

    async def promote_tier0_in(self, session: AsyncSession, target_ids: Sequence[int] | set[int]) -> None:
        state = self.model
        await session.execute(
            sa.update(state)
            .where(state.priority_tier == 0, state.social_account_id.in_(target_ids))
            .values(priority_tier=1)
        )

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        limit: int,
        scope: str,
        interval_seconds: int,
        jitter_fraction: float = 0.0,
        now: datetime,
    ) -> Sequence[models.BattleTagRankState]:
        """Pick the most-due tags and claim them (push out ``next_eligible_at``).

        Ordering: highest ``priority_tier`` first, then least-recently-checked.
        The claim prevents the next scheduler tick from re-selecting a tag before
        its fetch has been processed (Redis dedup is the second line of defense).
        The claim is the reschedule path for events a worker never processes
        (lost message / worker down), so it is jittered too — otherwise that
        recovery path would re-cluster the batch. This does not flush; the
        caller (``scheduler.run_collection_tick``) commits once for the whole
        tick (seed + claim).
        """
        state = self.model
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
            row.next_eligible_at = now + timedelta(seconds=jittered_interval(interval_seconds, jitter_fraction))
        return rows

    async def reenable_disabled(
        self,
        session: AsyncSession,
        *,
        interval_seconds: int,
        only_previously_succeeded: bool = False,
        workspace_id: int | None = None,
    ) -> int:
        """Requeue auto-disabled tags: ``disabled`` -> ``pending``, reset failures.

        ``next_eligible_at`` is spread across ``[now, now+interval_seconds]``
        (like the seeders) so re-enabling the whole backlog doesn't stampede
        OverFast. ``workspace_id`` limits the recovery to that workspace's
        players, so a workspace-scoped admin cannot requeue another tenant's
        backlog.
        """
        state = self.model
        query = sa.update(state).where(state.status == enums.RankCollectionStatus.disabled.value)
        if only_previously_succeeded:
            query = query.where(state.last_success_at.isnot(None))
        if workspace_id is not None:
            query = query.where(state.social_account_id.in_(workspace_account_ids(workspace_id)))
        result = await session.execute(
            query.values(
                status=enums.RankCollectionStatus.pending.value,
                consecutive_failures=0,
                last_error=None,
                next_eligible_at=_seed_next_eligible(interval_seconds),
            )
        )
        return result.rowcount or 0

    async def defer(
        self,
        session: AsyncSession,
        *,
        social_account_id: int,
        delay_seconds: int,
        now: datetime,
    ) -> None:
        """Push a tag's next eligibility out (used when a global cooldown is active)."""
        await session.execute(
            sa.update(self.model)
            .where(self.model.social_account_id == social_account_id)
            .values(next_eligible_at=now + timedelta(seconds=delay_seconds))
        )
