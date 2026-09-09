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

__all__ = ("DRAFT_BOARD_RESOURCE", "DRAFT_PROGRESS_REASON", "publish_draft_event")


# The client-cache resource that draft realtime events patch. Mirrors the
# frontend registry key; publish_patch tags every emitted event with it so a
# generic applier folds the delta into the cached draft board instead of
# refetching it.
DRAFT_BOARD_RESOURCE = "draft.board"

# Scoping hint for the gateway's response cache, which consumes this topic as a
# second subscriber (respcache.go::Broadcast). A draft pick writes ONLY draft
# tables — the public tournament.team / player / standing rows are materialized
# by TeamMaterializationService, i.e. exclusively on export — so no cached
# public read goes stale here. Without a reason the payload landed in
# respcache's unknown-reason branch, which drops EVERY cached entry for the
# tournament: on a draft day that was 250+ full-tournament evictions
# (draft.pick_made + draft.pick_started per pick), each one during peak
# spectating. The export paths announce their own staleness through
# `enqueue_tournament_structure_changed`, not through this topic.
DRAFT_PROGRESS_REASON = "draft_progress"


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
        # Stamped last so it always wins: `reason` is the gateway's scoping
        # field and must mean exactly one thing. `draft.blocked` used to put
        # its business reason ("role_shortage") here — that now rides as
        # `blocked_reason` (see rpc/draft.py::_publish_result).
        payload={**payload, "reason": DRAFT_PROGRESS_REASON},
        tournament_id=draft_session.tournament_id,
        workspace_id=draft_session.workspace_id,
        actor_user_id=actor_user_id,
    )
