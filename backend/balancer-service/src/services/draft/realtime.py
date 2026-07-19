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

from shared.models.balancer.draft import DraftSession
from shared.services import realtime_topics
from shared.services.realtime_publisher import publish_patch

__all__ = ("DRAFT_BOARD_RESOURCE", "publish_draft_event")


# The client-cache resource that draft realtime events patch. Mirrors the
# frontend registry key; publish_patch tags every emitted event with it so a
# generic applier folds the delta into the cached draft board instead of
# refetching it.
DRAFT_BOARD_RESOURCE = "draft.board"


async def publish_draft_event(
    session: AsyncSession,
    redis: Redis | None,
    *,
    draft_session: DraftSession,
    event_type: str,
    payload: dict[str, Any],
    actor_user_id: int | None = None,
) -> None:
    await publish_patch(
        session,
        redis,
        topic=realtime_topics.draft(draft_session.tournament_id),
        resource=DRAFT_BOARD_RESOURCE,
        event_type=event_type,
        payload=payload,
        tournament_id=draft_session.tournament_id,
        workspace_id=draft_session.workspace_id,
        actor_user_id=actor_user_id,
    )
