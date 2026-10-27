"""Draft realtime event publisher.

Thin wrapper over ``shared.services.realtime.emit`` targeting the session's own ``draft:{session_id}:board`` topic
(spec §9.6): one topic per draft whichever its owner, watched like the room it shows. Pure DATA: a draft pick writes
ONLY draft tables -- a tournament's public team rows are materialized on export, a mix's lineup on the last pick --
so nothing here stales a cached read. The export paths name their own staleness (``rpc/draft.py``).

Called within the mutation transaction so the persisted event id orders with the pick; presence is NOT routed here
(it has no place in the replay cursor).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.draft import DraftSession
from shared.repository.realtime import WorkspaceEventRepository
from shared.services.pickup_mix_realtime import emit_pickup_mix_changed
from shared.services.realtime import DomainEvent, Scope, emit

__all__ = (
    "DRAFT_BOARD_DOMAIN",
    "DRAFT_BOARD_RESOURCE",
    "MOVED_BOARDS_KEY",
    "last_event_id",
    "mix_changed",
    "publish_draft_event",
)

#: The topic suffix of a session's board: ``draft:{session_id}:board``.
DRAFT_BOARD_DOMAIN = "board"

# The client-cache resource these events patch. Mirrors the frontend registry
# key, so a generic applier folds the delta into the cached draft board instead
# of refetching it.
DRAFT_BOARD_RESOURCE = "draft.board"

#: ``session.info`` key: the draft sessions whose board this transaction moved; ``board`` builds each once it commits.
MOVED_BOARDS_KEY = "draft_moved_boards"

_events = WorkspaceEventRepository()


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
        scope=Scope.draft(draft_session.id),
        data=DomainEvent(
            domain=DRAFT_BOARD_DOMAIN,
            event_type=event_type,
            payload=payload,
            resource=DRAFT_BOARD_RESOURCE,
        ),
        actor_user_id=actor_user_id,
    )
    session.info.setdefault(MOVED_BOARDS_KEY, set()).add(draft_session.id)


async def last_event_id(session: AsyncSession, draft_session_id: int) -> int | None:
    """Newest persisted event on the session's board topic: what every cached draft read is keyed by.

    Each draft mutation persists its event in its own transaction (above), so a new id is a new board state. Roles
    and ranks are read live, not copied into the draft; an edit made elsewhere reaches a cached board when its short
    TTL runs out (``board._BOARD_CACHE_TTL_SECONDS``).
    """
    return await _events.last_id_for_topics(session, (Scope.draft(draft_session_id).domain_topic(DRAFT_BOARD_DOMAIN),))


async def mix_changed(session: Any, draft_session: DraftSession, *, actor_user_id: int | None = None) -> None:
    """A mix lobby's draft moved a stage its cards show (spec §5): the mix overview re-reads. A tournament draft has
    nothing to tell the mixes."""
    if draft_session.custom_game_id is not None:
        await emit_pickup_mix_changed(
            session,
            draft_session.workspace_id,
            custom_game_id=draft_session.custom_game_id,
            change="draft",
            actor_user_id=actor_user_id,
        )
