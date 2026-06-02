"""Admin operations for OverFast rank collection: status read + force trigger."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from shared.schemas.events import FetchRankEvent
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from . import service, tasks

# Manual triggers run at the registration priority tier.
_MANUAL_PRIORITY_TIER = 2


async def get_user_collection_status(
    session: AsyncSession, user_id: int
) -> list[dict[str, Any]]:
    """Per-battle-tag collection state for a user (incl. tags never fetched)."""
    bt = models.UserBattleTag
    state = models.BattleTagRankState
    rows = (
        await session.execute(
            sa.select(bt, state)
            .outerjoin(state, state.battle_tag_id == bt.id)
            .where(bt.user_id == user_id)
            .order_by(bt.battle_tag.asc())
        )
    ).all()

    result: list[dict[str, Any]] = []
    for tag, st in rows:
        result.append(
            {
                "battle_tag_id": tag.id,
                "battle_tag": tag.battle_tag,
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


async def _resolve_target_tags(
    session: AsyncSession,
    *,
    user_id: int | None,
    battle_tag_ids: Sequence[int] | None,
) -> list[models.UserBattleTag]:
    bt = models.UserBattleTag
    query = sa.select(bt)
    if battle_tag_ids:
        query = query.where(bt.id.in_(list(battle_tag_ids)))
        if user_id is not None:
            query = query.where(bt.user_id == user_id)
    elif user_id is not None:
        query = query.where(bt.user_id == user_id)
    else:
        return []
    return list((await session.scalars(query)).all())


async def trigger_collection(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    battle_tag_ids: Sequence[int] | None = None,
    broker: Any | None = None,
    redis: Any | None = None,
) -> int:
    """Force a priority rank fetch for a user's tags (all) or specific tags.

    Ensures a state row per tag (bumping priority), then enqueues a forced
    priority fetch (bypassing dedup) so "collect now" always runs. Returns the
    number of fetches enqueued.
    """
    tags = await _resolve_target_tags(session, user_id=user_id, battle_tag_ids=battle_tag_ids)
    if not tags:
        return 0

    for tag in tags:
        await service.ensure_state(
            session, tag.id, tag.battle_tag, priority_tier=_MANUAL_PRIORITY_TIER
        )
    await session.commit()

    enqueued = 0
    for tag in tags:
        event = FetchRankEvent(
            battle_tag_id=tag.id,
            battle_tag=tag.battle_tag,
            source="manual",
        )
        if await tasks.enqueue_fetch(
            event, priority=True, force=True, broker=broker, redis=redis
        ):
            enqueued += 1
    return enqueued
