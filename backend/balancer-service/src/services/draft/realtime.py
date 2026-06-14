"""Draft realtime event publisher.

Thin wrapper over ``shared.services.realtime_publisher.publish_event`` that
targets the public ``tournament:{id}:draft`` topic. Called within the mutation
transaction so the persisted WorkspaceEvent id orders with the pick. Redis
publish failures are swallowed by ``publish_event`` (clients self-heal on
reconnect/snapshot); presence is NOT routed here (Redis-only, to keep the
replay cursor clean).
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.draft import DraftSession
from shared.services import realtime_topics
from shared.services.realtime_publisher import publish_event

__all__ = ("publish_draft_event",)


async def publish_draft_event(
    session: AsyncSession,
    redis: Redis | None,
    *,
    draft_session: DraftSession,
    event_type: str,
    payload: dict[str, Any],
    actor_user_id: int | None = None,
) -> None:
    await publish_event(
        session,
        redis,
        topic=realtime_topics.draft(draft_session.tournament_id),
        event_type=event_type,
        tournament_id=draft_session.tournament_id,
        workspace_id=draft_session.workspace_id,
        payload=payload,
        actor_user_id=actor_user_id,
    )
