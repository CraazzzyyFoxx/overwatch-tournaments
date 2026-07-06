"""Admin operations for OverFast rank collection: status read + force trigger."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.social import SocialProvider
from shared.schemas.events import FetchRankEvent
from src import models

from . import service, tasks

# Manual triggers run at the registration priority tier.
_MANUAL_PRIORITY_TIER = 2


async def get_user_collection_status(session: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    """Per-battle-tag collection state for a user (incl. tags never fetched)."""
    acc = models.SocialAccount
    state = models.BattleTagRankState
    rows = (
        await session.execute(
            sa.select(acc, state)
            .outerjoin(state, state.social_account_id == acc.id)
            .where(acc.user_id == user_id, acc.provider == SocialProvider.BATTLENET)
            .order_by(acc.username.asc())
        )
    ).all()

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
    session: AsyncSession,
    *,
    status: str | None = None,
    source: str | None = None,
    before_id: int | None = None,
    limit: int = 50,
) -> list[models.RankFetchLog]:
    """Most-recent worker fetch attempts (newest first), filterable + cursor-paged."""
    log = models.RankFetchLog
    query = sa.select(log).order_by(log.id.desc())
    if status:
        query = query.where(log.status == status)
    if source:
        query = query.where(log.source == source)
    if before_id is not None:
        query = query.where(log.id < before_id)
    query = query.limit(max(1, min(limit, 200)))
    return list((await session.scalars(query)).all())


async def _resolve_target_tags(
    session: AsyncSession,
    *,
    user_id: int | None,
    social_account_ids: Sequence[int] | None,
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
    return list((await session.scalars(query)).all())


async def trigger_collection(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    social_account_ids: Sequence[int] | None = None,
    broker: Any | None = None,
    redis: Any | None = None,
) -> int:
    """Force a priority rank fetch for a user's tags (all) or specific tags.

    Ensures a state row per tag (bumping priority), then enqueues a forced
    priority fetch (bypassing dedup) so "collect now" always runs. Returns the
    number of fetches enqueued.
    """
    tags = await _resolve_target_tags(session, user_id=user_id, social_account_ids=social_account_ids)
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
