"""Draft realtime event publisher.

Thin wrapper over ``shared.services.realtime.emit`` targeting the public
``tournament:{id}:draft`` topic. Pure DATA: a draft pick writes ONLY draft
tables — the public tournament.team / player / standing rows are materialized
by ``TeamMaterializationService``, i.e. exclusively on export — so nothing here
stales a cached read, and nothing here carries an invalidation. The export
paths name their own staleness (``rpc/draft.py``).

Called within the mutation transaction so the persisted event id orders with
the pick; presence is NOT routed here (it has no place in the replay cursor).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.balancer.draft import DraftSession
from shared.models.platform.realtime import WorkspaceEvent
from shared.services.realtime import DomainEvent, Scope, emit

__all__ = ("DRAFT_BOARD_RESOURCE", "last_event_id", "publish_draft_event")


# The client-cache resource these events patch. Mirrors the frontend registry
# key, so a generic applier folds the delta into the cached draft board instead
# of refetching it.
DRAFT_BOARD_RESOURCE = "draft.board"


async def publish_draft_event(
    session: Any,
    *,
    draft_session: DraftSession,
    event_type: str,
    payload: dict[str, Any],
    actor_user_id: int | None = None,
) -> None:
    await emit(
        session,
        scope=Scope.tournament(draft_session.tournament_id),
        data=DomainEvent(
            domain="draft",
            event_type=event_type,
            payload=payload,
            resource=DRAFT_BOARD_RESOURCE,
        ),
        actor_user_id=actor_user_id,
    )


async def last_event_id(session: AsyncSession, tournament_id: int) -> int | None:
    """Newest persisted event on the tournament's draft topic or its invalidation topic.

    What every cached draft read is keyed by. Each draft mutation persists its
    event in its own transaction (above), and a rank or registration edit lands
    on the tournament's INVALIDATION topic (tournament-service, resource
    ``tournament.registrations``) -- roles and ranks are read live, not copied
    into the draft -- so a new id is a new board state.
    """
    scope = Scope.tournament(tournament_id)
    topics = (scope.domain_topic("draft"), scope.invalidation_topic)
    return await session.scalar(sa.select(sa.func.max(WorkspaceEvent.id)).where(WorkspaceEvent.topic.in_(topics)))
