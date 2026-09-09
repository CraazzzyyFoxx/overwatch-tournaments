"""Admin operations for OverFast rank collection: status read + force trigger."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.social import SocialProvider
from shared.schemas.events import FetchRankEvent
from shared.services import settings_provider
from src import models

from . import service, tasks

# Manual triggers run at the registration priority tier.
_MANUAL_PRIORITY_TIER = 2


class RankAdminService:
    """Admin operations for OverFast rank collection: status read + force trigger."""

    async def get_user_collection_status(
        self, session: AsyncSession, user_id: int, *, workspace_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Per-battle-tag collection state for a user (incl. tags never fetched).

        ``workspace_id`` is the caller's authorization scope: a workspace-scoped
        admin only sees the tags of a player who is a member of their workspace,
        and gets ``[]`` for anybody else.
        """
        acc = models.SocialAccount
        state = models.BattleTagRankState
        query = (
            sa.select(acc, state)
            .outerjoin(state, state.social_account_id == acc.id)
            .where(acc.user_id == user_id, acc.provider == SocialProvider.BATTLENET)
            .order_by(acc.username.asc())
        )
        if workspace_id is not None:
            query = query.where(acc.id.in_(service.workspace_account_ids(workspace_id)))
        rows = (await session.execute(query)).all()

        result: list[dict[str, Any]] = []
        for tag, st in rows:
            result.append(
                {
                    "social_account_id": tag.id,
                    "battle_tag": tag.username,
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

    async def list_fetch_log(
        self,
        session: AsyncSession,
        *,
        workspace_id: int | None = None,
        status: str | None = None,
        source: str | None = None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Most-recent worker fetch attempts (newest first), filterable + cursor-paged.

        Resolves the owning ``user_id`` (LEFT JOIN — null when the account was
        deleted) so the admin log is clickable through to the player detail view.

        ``workspace_id`` is the caller's authorization scope, not a user-supplied
        filter: a workspace-scoped admin must never page into another tenant's
        fetch history. Rows whose account was deleted (``social_account_id IS NULL``)
        fall out of a scoped read — they can no longer be attributed to a workspace.
        """
        log = models.RankFetchLog
        acc = models.SocialAccount
        query = (
            sa.select(log, acc.user_id.label("user_id"))
            .outerjoin(acc, acc.id == log.social_account_id)
            .order_by(log.id.desc())
        )
        if workspace_id is not None:
            query = query.where(log.social_account_id.in_(service.workspace_account_ids(workspace_id)))
        if status:
            query = query.where(log.status == status)
        if source:
            query = query.where(log.source == source)
        if before_id is not None:
            query = query.where(log.id < before_id)
        query = query.limit(max(1, min(limit, 200)))
        rows = (await session.execute(query)).all()
        return [
            {
                "id": row.RankFetchLog.id,
                "social_account_id": row.RankFetchLog.social_account_id,
                "user_id": row.user_id,
                "battle_tag": row.RankFetchLog.battle_tag,
                "status": row.RankFetchLog.status,
                "source": row.RankFetchLog.source,
                "error": row.RankFetchLog.error,
                "snapshots_written": row.RankFetchLog.snapshots_written,
                "created_at": row.RankFetchLog.created_at,
            }
            for row in rows
        ]

    async def get_collection_stats(self, session: AsyncSession, *, workspace_id: int | None = None) -> dict[str, Any]:
        """Assemble the admin health dashboard: DB aggregates + current config echo.

        ``workspace_id`` scopes the aggregates to that workspace's players; the
        config echo stays global because the collector is one per deployment.
        """
        raw = await service.collection_stats(session, workspace_id=workspace_id)
        cfg = await settings_provider.get_rank_collection_config(session)
        fetch = raw["fetch_24h"]
        fetch_total = sum(fetch.values())
        errors = fetch.get("error", 0) + fetch.get("rate_limited", 0)
        tiers = raw["by_tier"]
        return {
            "total": raw["total"],
            "never_checked": raw["never_checked"],
            "by_status": raw["by_status"],
            "tier0": tiers.get(0, 0),
            "tier1": tiers.get(1, 0),
            "tier2": tiers.get(2, 0),
            "coverage_24h": raw["coverage_24h"],
            "coverage_7d": raw["coverage_7d"],
            "last_success_at": raw["last_success_at"],
            "fetch_24h": fetch,
            "fetch_24h_total": fetch_total,
            "error_rate_24h": round(errors / fetch_total, 4) if fetch_total else 0.0,
            "enabled": cfg.enabled,
            "scope": cfg.scope,
            "interval_seconds": cfg.interval_seconds,
            "rate_limit_per_minute": cfg.rate_limit_per_minute,
            # Live upstream state, read from the worker's own OverFast client: an
            # open circuit means every tag fetch is refused before it leaves the
            # process, which no DB aggregate can show (the fetch_log simply stops
            # growing). ``invalid_battle_tags_24h`` counts handles the client
            # rejects outright — those never recover without an operator.
            "overfast_base_url": tasks.rank_client.base_url,
            "overfast_circuit_state": tasks.rank_client.circuit_state,
            "invalid_battle_tags_24h": raw["invalid_battle_tags_24h"],
        }

    async def _resolve_target_tags(
        self,
        session: AsyncSession,
        *,
        user_id: int | None,
        social_account_ids: Sequence[int] | None,
        workspace_id: int | None = None,
    ) -> list[models.SocialAccount]:
        acc = models.SocialAccount
        query = sa.select(acc).where(acc.provider == SocialProvider.BATTLENET)
        if social_account_ids:
            query = query.where(acc.id.in_(list(social_account_ids)))
            if user_id is not None:
                query = query.where(acc.user_id == user_id)
        elif user_id is not None:
            query = query.where(acc.user_id == user_id)
        else:
            return []
        if workspace_id is not None:
            query = query.where(acc.id.in_(service.workspace_account_ids(workspace_id)))
        return list((await session.scalars(query)).all())

    async def reenable_disabled(
        self,
        session: AsyncSession,
        *,
        only_previously_succeeded: bool = False,
        workspace_id: int | None = None,
    ) -> int:
        """Requeue auto-disabled tags (admin recovery after a transient OverFast outage).

        Uses the configured collection interval to spread the re-enabled backlog.
        Returns the number of tags re-enabled; commits. ``workspace_id`` limits
        the recovery to that workspace's players.
        """
        cfg = await settings_provider.get_rank_collection_config(session)
        count = await service.reenable_disabled(
            session,
            interval_seconds=cfg.interval_seconds,
            only_previously_succeeded=only_previously_succeeded,
            workspace_id=workspace_id,
        )
        await session.commit()
        return count

    async def trigger_collection(
        self,
        session: AsyncSession,
        *,
        user_id: int | None = None,
        social_account_ids: Sequence[int] | None = None,
        workspace_id: int | None = None,
        broker: Any | None = None,
        redis: Any | None = None,
    ) -> int:
        """Force a priority rank fetch for a user's tags (all) or specific tags.

        Ensures a state row per tag (bumping priority), then enqueues a forced
        priority fetch (bypassing dedup) so "collect now" always runs. Returns
        the number of fetches enqueued. ``workspace_id`` is the caller's
        authorization scope: tags of players outside that workspace are never
        touched, so an explicit ``social_account_ids`` list cannot reach another
        tenant.
        """
        tags = await self._resolve_target_tags(
            session, user_id=user_id, social_account_ids=social_account_ids, workspace_id=workspace_id
        )
        if not tags:
            return 0

        for tag in tags:
            await service.ensure_state(session, tag.id, tag.username, priority_tier=_MANUAL_PRIORITY_TIER)
        await session.commit()

        enqueued = 0
        for tag in tags:
            event = FetchRankEvent(
                social_account_id=tag.id,
                battle_tag=tag.username,
                source="manual",
            )
            if await tasks.enqueue_fetch(event, priority=True, force=True, broker=broker, redis=redis):
                enqueued += 1
        return enqueued


rank_admin_service = RankAdminService()

# Module-attribute compatibility seam: rpc/rank.py and tests call/patch these as
# bare ``admin.<name>(...)`` / ``admin.service.<name>`` — see service.py's
# matching note for why this shape (not ``self.``-based injection) is load-bearing.
get_user_collection_status = rank_admin_service.get_user_collection_status
list_fetch_log = rank_admin_service.list_fetch_log
get_collection_stats = rank_admin_service.get_collection_stats
reenable_disabled = rank_admin_service.reenable_disabled
trigger_collection = rank_admin_service.trigger_collection
