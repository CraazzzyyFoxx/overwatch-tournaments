from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.repository.base import BaseRepository

#: Rows per ``character_rate`` insert statement: a day is a few thousand rows, kept under the driver's bind limit.
_RATE_CHUNK = 1000


def workspace_account_ids(workspace_id: int, *, provider: str) -> sa.Select:
    """Game-account ``social_account`` ids of ``provider`` owned by players of ``workspace_id``.

    Rank rows key on ``players.social_account``, which has no workspace column —
    a game account belongs to a player, and a player reaches a workspace through
    ``workspace_member``. This subquery is that hop, and it is what lets a
    workspace-scoped admin see the collection health of their own roster without
    seeing every other tenant's accounts.
    """
    return (
        sa.select(models.SocialAccount.id)
        .join(models.WorkspaceMember, models.WorkspaceMember.player_id == models.SocialAccount.user_id)
        .where(
            models.WorkspaceMember.workspace_id == workspace_id,
            models.SocialAccount.provider == provider,
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


def compute_per_tick(
    total_in_scope: int,
    *,
    interval_seconds: int,
    tick_seconds: int,
    rate_limit_per_minute: int,
    batch_size: int,
    max_per_tick: int | None,
) -> int:
    """How many tags to claim this tick to cover the population once per interval.

    ``needed`` is the steady rate that spreads the whole in-scope population
    evenly across ``interval_seconds``. It is capped by the per-tick share of the
    upstream's rate budget (and ``batch_size`` / ``max_per_tick``); when ``needed``
    exceeds that cap the effective interval gracefully stretches.
    """
    needed = math.ceil(total_in_scope * tick_seconds / interval_seconds)
    rate_budget = max(1, math.floor(rate_limit_per_minute * tick_seconds / 60))
    cap = batch_size if max_per_tick is None else min(batch_size, max_per_tick)
    cap = min(cap, rate_budget)
    return max(1, min(needed, cap))


def _seed_next_eligible(interval_seconds: int) -> sa.ColumnElement[datetime]:
    """SQL expression spreading a fresh seed across ``[now, now+interval]``.

    Seeding with ``next_eligible_at = NULL`` makes the whole population due at
    once (thundering herd on first enable); a per-row random offset distributes
    the initial cycle evenly instead.
    """
    return sa.func.now() + sa.func.make_interval(0, 0, 0, 0, 0, 0, sa.func.random() * interval_seconds)


class RankSnapshotRepository(BaseRepository[models.UserRankSnapshot]):
    """``rank.rank_snapshot`` — one row per observed rank change."""

    def __init__(self) -> None:
        super().__init__(models.UserRankSnapshot)

    def add_many(self, session: AsyncSession, rows: Sequence[models.UserRankSnapshot]) -> None:
        """Stage snapshots. No flush: they ride the collector's single write transaction."""
        session.add_all(rows)


class RankFetchLogRepository(BaseRepository[models.RankFetchLog]):
    """``rank.fetch_log`` — append-only worker fetch-attempt history."""

    def __init__(self) -> None:
        super().__init__(models.RankFetchLog)

    def add(self, session: AsyncSession, row: models.RankFetchLog) -> models.RankFetchLog:
        """Stage one journal row. No flush — rides the caller's transaction."""
        session.add(row)
        return row

    async def delete_older_than(self, session: AsyncSession, cutoff: datetime, *, discipline: str) -> int:
        """Drop rows created before ``cutoff``; returns how many went.

        The task feed reads the newest few hundred rows and the health dashboard
        the last 24 hours, so nothing older than the retention window is ever
        read. ``ix_fetch_log_created_at`` exists for this range.
        """
        result = await session.execute(
            sa.delete(models.RankFetchLog).where(
                models.RankFetchLog.discipline == discipline, models.RankFetchLog.created_at < cutoff
            )
        )
        return int(result.rowcount or 0)

    async def list_recent(
        self,
        session: AsyncSession,
        *,
        discipline: str,
        provider: str,
        workspace_id: int | None = None,
        status: str | None = None,
        source: str | None = None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Most-recent fetch attempts of one game (newest first), filterable + cursor-paged; ``workspace_id`` is the
        caller's authorization scope (rows of deleted accounts fall out of a scoped read)."""
        log, acc = models.RankFetchLog, models.SocialAccount
        query = (
            sa.select(log, acc.user_id.label("user_id"))
            .outerjoin(acc, acc.id == log.social_account_id)
            .where(log.discipline == discipline)
            .order_by(log.id.desc())
        )
        if workspace_id is not None:
            query = query.where(log.social_account_id.in_(workspace_account_ids(workspace_id, provider=provider)))
        if status:
            query = query.where(log.status == status)
        if source:
            query = query.where(log.source == source)
        if before_id is not None:
            query = query.where(log.id < before_id)
        rows = (await session.execute(query.limit(max(1, min(limit, 200))))).all()
        return [
            {
                "id": row.RankFetchLog.id,
                "social_account_id": row.RankFetchLog.social_account_id,
                "user_id": row.user_id,
                "handle": row.RankFetchLog.handle,
                "status": row.RankFetchLog.status,
                "source": row.RankFetchLog.source,
                "error": row.RankFetchLog.error,
                "snapshots_written": row.RankFetchLog.snapshots_written,
                "created_at": row.RankFetchLog.created_at,
            }
            for row in rows
        ]


class GameAccountProfileRepository(BaseRepository[models.GameAccountProfile]):
    """``rank.account_profile`` — the account as its upstream last showed it, one row per game account."""

    def __init__(self) -> None:
        super().__init__(models.GameAccountProfile)

    async def get_by_social_account_id(
        self, session: AsyncSession, social_account_id: int
    ) -> models.GameAccountProfile | None:
        return await session.scalar(self.select().where(self.model.social_account_id == social_account_id))


class CareerSnapshotRepository(BaseRepository[models.CareerSnapshot]):
    """``rank.career_snapshot`` — one row per observed career change of one character."""

    def __init__(self) -> None:
        super().__init__(models.CareerSnapshot)


class CharacterRateRepository(BaseRepository[models.CharacterRate]):
    """``rank.character_rate`` — the game's own character rates, one day per slice."""

    def __init__(self) -> None:
        super().__init__(models.CharacterRate)

    async def add_day(self, session: AsyncSession, rows: Sequence[Mapping[str, Any]]) -> int:
        """Insert a day's rows; a slice already stored for that day is kept as it is. Returns rows inserted."""
        inserted = 0
        for start in range(0, len(rows), _RATE_CHUNK):
            result = await session.execute(
                pg_insert(models.CharacterRate)
                .values([dict(row) for row in rows[start : start + _RATE_CHUNK]])
                .on_conflict_do_nothing(constraint="uq_character_rate_slice")
                .returning(models.CharacterRate.id)
            )
            # ``rowcount`` is -1 for a multi-row VALUES under the async driver; the returned ids are the count.
            inserted += len(result.all())
        return inserted


class RankAccountStateRepository(BaseRepository[models.RankAccountState]):
    """``rank.account_state`` — collection bookkeeping, one row per collected game account."""

    def __init__(self) -> None:
        super().__init__(models.RankAccountState)

    async def get_by_social_account_id(
        self, session: AsyncSession, social_account_id: int
    ) -> models.RankAccountState | None:
        return await session.scalar(self.select().where(self.model.social_account_id == social_account_id))

    async def create_for_account(
        self,
        session: AsyncSession,
        *,
        discipline: str,
        social_account_id: int,
        handle: str,
        external_id: str | None,
        priority_tier: int = 0,
    ) -> models.RankAccountState:
        return await self.create(
            session,
            models.RankAccountState(
                discipline=discipline,
                social_account_id=social_account_id,
                handle=handle,
                external_id=external_id,
                priority_tier=priority_tier,
            ),
        )

    async def bump_priority(
        self, session: AsyncSession, state: models.RankAccountState, priority_tier: int
    ) -> models.RankAccountState:
        if priority_tier > state.priority_tier:
            state.priority_tier = priority_tier
            await session.flush()
        return state

    async def bulk_seed_missing(
        self,
        session: AsyncSession,
        *,
        discipline: str,
        provider: str,
        external_id: sa.ColumnElement,
        interval_seconds: int,
        target_ids: Sequence[int] | set[int] | None = None,
        priority_tier: int = 0,
        tagged_only: bool = True,
    ) -> int:
        """Insert a state row for every game account in scope that lacks one.

        ``target_ids is None`` seeds every ``provider`` account (tier 0 — the
        ``scope="all"`` collector sweep, ``seed_states_for_all_battle_tags``); a
        concrete ``target_ids`` seeds only that set (tier 1 — the registration
        pool, ``seed_states_from_registrations``). Either way the new rows get a
        jittered ``next_eligible_at`` spread across ``[now, now+interval_seconds]``
        so the first collection cycle is even rather than a thundering herd.
        ``tagged_only`` (the ``scope="all"`` sweep) skips handles without ``#``:
        Overwatch cannot resolve them; League passes ``False`` so a malformed
        Riot ID reaches its collector's permanent-failure path.
        """
        acc = models.SocialAccount
        state = self.model

        columns = ["discipline", "social_account_id", "handle", "external_id"]
        select_cols: list[sa.ColumnElement] = [
            sa.literal(discipline).label("discipline"),
            acc.id.label("social_account_id"),
            acc.username.label("handle"),
            external_id.label("external_id"),
        ]
        if priority_tier:
            columns.append("priority_tier")
            select_cols.append(sa.literal(priority_tier).label("priority_tier"))
        columns.append("next_eligible_at")
        select_cols.append(_seed_next_eligible(interval_seconds).label("next_eligible_at"))

        missing = ~sa.exists().where(state.social_account_id == acc.id)
        if target_ids is not None:
            where_clauses = [acc.id.in_(target_ids), missing]
        else:
            tagged = [acc.username.like("%#%")] if tagged_only else []
            where_clauses = [acc.provider == provider, *tagged, missing]
        result = await session.execute(
            sa.insert(state).from_select(columns, sa.select(*select_cols).where(*where_clauses))
        )
        return result.rowcount or 0

    async def demote_tier1_not_in(
        self, session: AsyncSession, target_ids: Sequence[int] | set[int] | None, *, discipline: str
    ) -> None:
        state = self.model
        demote = sa.update(state).where(state.discipline == discipline, state.priority_tier == 1)
        if target_ids:
            demote = demote.where(state.social_account_id.notin_(target_ids))
        await session.execute(demote.values(priority_tier=0))

    async def promote_tier0_in(
        self, session: AsyncSession, target_ids: Sequence[int] | set[int], *, discipline: str
    ) -> None:
        state = self.model
        await session.execute(
            sa.update(state)
            .where(state.discipline == discipline, state.priority_tier == 0, state.social_account_id.in_(target_ids))
            .values(priority_tier=1)
        )

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        discipline: str,
        limit: int,
        scope: str,
        interval_seconds: int,
        jitter_fraction: float = 0.0,
        now: datetime,
    ) -> Sequence[models.RankAccountState]:
        """Pick the most-due accounts of ``discipline`` and claim them (push out ``next_eligible_at``).

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
            state.discipline == discipline,
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
        discipline: str,
        provider: str,
        interval_seconds: int,
        only_previously_succeeded: bool = False,
        workspace_id: int | None = None,
    ) -> int:
        """Requeue auto-disabled accounts of ``discipline``: ``disabled`` -> ``pending``, reset failures.

        ``next_eligible_at`` is spread across ``[now, now+interval_seconds]``
        (like the seeders) so re-enabling the whole backlog doesn't stampede
        the upstream. ``workspace_id`` limits the recovery to that workspace's
        players, so a workspace-scoped admin cannot requeue another tenant's
        backlog.
        """
        state = self.model
        query = sa.update(state).where(
            state.discipline == discipline, state.status == enums.RankCollectionStatus.disabled.value
        )
        if only_previously_succeeded:
            query = query.where(state.last_success_at.isnot(None))
        if workspace_id is not None:
            query = query.where(state.social_account_id.in_(workspace_account_ids(workspace_id, provider=provider)))
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

    async def defer_many(
        self, session: AsyncSession, social_account_ids: Sequence[int], *, delay_seconds: float, now: datetime
    ) -> None:
        """:meth:`defer` for a whole batch: no failure count, no status change."""
        await session.execute(
            sa.update(self.model)
            .where(self.model.social_account_id.in_(list(social_account_ids)))
            .values(next_eligible_at=now + timedelta(seconds=delay_seconds))
        )

    async def user_collection(
        self, session: AsyncSession, user_id: int, *, provider: str, workspace_id: int | None = None
    ) -> list[dict]:
        """Per-account collection state of a user's ``provider`` accounts (incl. accounts never fetched).

        ``workspace_id`` is the caller's authorization scope: a workspace-scoped
        admin only sees the accounts of a player who is a member of their
        workspace, and gets ``[]`` for anybody else.
        """
        acc, state = models.SocialAccount, self.model
        query = (
            sa.select(acc, state)
            .outerjoin(state, state.social_account_id == acc.id)
            .where(acc.user_id == user_id, acc.provider == provider)
            .order_by(acc.username.asc())
        )
        if workspace_id is not None:
            query = query.where(acc.id.in_(workspace_account_ids(workspace_id, provider=provider)))
        rows = (await session.execute(query)).all()

        result: list[dict] = []
        for tag, st in rows:
            result.append(
                {
                    "social_account_id": tag.id,
                    "handle": tag.username,
                    "status": st.status if st is not None else None,
                    "last_checked_at": st.last_checked_at if st is not None else None,
                    "last_success_at": st.last_success_at if st is not None else None,
                    "last_error": st.last_error if st is not None else None,
                    "consecutive_failures": st.consecutive_failures if st is not None else 0,
                    "next_eligible_at": st.next_eligible_at if st is not None else None,
                    "priority_tier": st.priority_tier if st is not None else 0,
                }
            )
        return result

    async def collection_stats(
        self,
        session: AsyncSession,
        *,
        discipline: str,
        provider: str,
        workspace_id: int | None = None,
        invalid_error: str | None = None,
    ) -> dict:
        """Aggregate collection health of one game (DB layer only; caller adds config).

        Mirrors the manual incident-diagnostic queries: state status/tier mix,
        whole population size, accounts successfully polled over 24h/7d, the
        global last successful capture, and the last-24h ``fetch_log`` outcome mix.

        ``workspace_id`` narrows every aggregate to the ``provider`` accounts of
        that workspace's players (the caller's authorization scope). ``invalid_error``
        is the ``fetch_log.error`` the game's client writes for a handle it refuses
        before any HTTP call; without one, ``invalid_handles_24h`` is ``0``.
        """
        state, log = self.model, models.RankFetchLog
        now = datetime.now(UTC)
        accounts = workspace_account_ids(workspace_id, provider=provider) if workspace_id is not None else None

        def _scoped(stmt: sa.Select, column: sa.ColumnElement, game: sa.ColumnElement) -> sa.Select:
            stmt = stmt.where(game == discipline)
            return stmt if accounts is None else stmt.where(column.in_(accounts))

        by_status = {
            str(status): int(count)
            for status, count in (
                await session.execute(
                    _scoped(
                        sa.select(state.status, sa.func.count()), state.social_account_id, state.discipline
                    ).group_by(state.status)
                )
            ).all()
        }
        by_tier = {
            int(tier): int(count)
            for tier, count in (
                await session.execute(
                    _scoped(
                        sa.select(state.priority_tier, sa.func.count()), state.social_account_id, state.discipline
                    ).group_by(state.priority_tier)
                )
            ).all()
        }
        total = int(
            await session.scalar(
                _scoped(sa.select(sa.func.count()).select_from(state), state.social_account_id, state.discipline)
            )
            or 0
        )
        never_checked = int(
            await session.scalar(
                _scoped(sa.select(sa.func.count()).select_from(state), state.social_account_id, state.discipline).where(
                    state.last_checked_at.is_(None)
                )
            )
            or 0
        )
        last_success_at = await session.scalar(
            _scoped(sa.select(sa.func.max(state.last_success_at)), state.social_account_id, state.discipline)
        )

        async def _coverage(delta: timedelta) -> int:
            # The state row, not ``rank_snapshot``: snapshots record CHANGES, so a
            # steady account writes none for weeks and would read as uncollected.
            return int(
                await session.scalar(
                    _scoped(
                        sa.select(sa.func.count()).select_from(state), state.social_account_id, state.discipline
                    ).where(state.last_success_at > now - delta)
                )
                or 0
            )

        fetch_24h = {
            str(status): int(count)
            for status, count in (
                await session.execute(
                    _scoped(sa.select(log.status, sa.func.count()), log.social_account_id, log.discipline)
                    .where(log.created_at > now - timedelta(hours=24))
                    .group_by(log.status)
                )
            ).all()
        }

        # Handles the client refuses before any HTTP call (shape broken — e.g. a
        # mangled handle stored at registration). They never reach the upstream,
        # so they never recover on their own and need an operator, not a retry.
        invalid_handles_24h = 0
        if invalid_error is not None:
            invalid_handles_24h = int(
                await session.scalar(
                    _scoped(sa.select(sa.func.count()).select_from(log), log.social_account_id, log.discipline).where(
                        log.created_at > now - timedelta(hours=24),
                        log.error == invalid_error,
                    )
                )
                or 0
            )

        return {
            "total": total,
            "never_checked": never_checked,
            "by_status": by_status,
            "by_tier": by_tier,
            "last_success_at": last_success_at,
            "coverage_24h": await _coverage(timedelta(hours=24)),
            "coverage_7d": await _coverage(timedelta(days=7)),
            "fetch_24h": fetch_24h,
            "invalid_handles_24h": invalid_handles_24h,
        }
