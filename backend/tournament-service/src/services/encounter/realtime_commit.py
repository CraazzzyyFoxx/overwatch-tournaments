"""Realtime signals for encounter map-veto / hero pick-ban rooms.

Both are DATA events: ``encounter:{id}:map-veto`` (kind="map") and
``encounter:{id}:pick-ban:hero`` (kind="hero"). Two topics, not one
parametrized by kind, so the map room's subscribers are never woken by a
hero-only change and vice versa (design:
docs/plans/2026-08-09-generic-pickban-engine.md).

The payload carries no state at all: subscribers refetch the pool on receipt
(``viewer_side`` and friends are per-viewer, so there is nothing broadcastable
to fold in). What changed is already said by the topic and the event type,
which is why the old ``reason: "veto_changed"`` field is gone.

Nothing here invalidates a cache: a pick-ban write touches only pick-ban tables.
The one encounter write that does move a tournament-scoped read is a map report
resolving a map (``map_report.py``), and it names that resource itself.

Staging/persistence/publishing all live in ``shared.services.realtime.emit``:
call this immediately before the commit that owns the pool mutation.
"""

from __future__ import annotations

from typing import Any

from shared.services.realtime import DomainEvent, Scope, emit

__all__ = ("emit_pick_ban_update",)

_DOMAIN_BY_KIND = {"map": "map-veto", "hero": "pick-ban:hero"}
_EVENT_TYPE_BY_KIND = {"map": "map_veto.updated", "hero": "pick_ban.updated"}


async def emit_pick_ban_update(session: Any, encounter_id: int, *, kind: str = "map") -> None:
    """Stage a pick-ban room signal for ``encounter_id`` + ``kind``.

    ``kind`` is ``"map"`` (default) or ``"hero"``.
    """
    await emit(
        session,
        scope=Scope.encounter(int(encounter_id)),
        data=DomainEvent(
            domain=_DOMAIN_BY_KIND.get(kind, "pick-ban:hero"),
            event_type=_EVENT_TYPE_BY_KIND.get(kind, "pick_ban.updated"),
            payload={"encounter_id": int(encounter_id)},
        ),
    )
