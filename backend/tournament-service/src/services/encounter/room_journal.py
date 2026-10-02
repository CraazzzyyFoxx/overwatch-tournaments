"""The pre-game room's journal: what every path writes down, and how staff read
it back.

``EncounterRoomEvent`` is the room's own trail. Readiness, session lifecycle,
every step a captain or the clock settles, every map claim, every organizer
override -- all of it lands here, so an organizer opening a room reads ONE
ordered story instead of reconstructing it from the submission log, the admin
audit and the result audit at once.

:func:`record_room_event` is the only write API. It ``session.add``s and
nothing else -- no flush, no commit -- so a mutation and its journal row land
together or not at all. Call it BEFORE the commit that owns the change.

The read merges this table with ``encounter_result_audit``: the room decides
the draft, the result audit decides the score, and an organizer asking "what
happened here" means both.

Action vocabulary (``data`` keys are fixed; keys that do not apply are omitted):

==================== ======== ============== ===============================================
action               kind     source         data
==================== ======== ============== ===============================================
ready_marked         --       captain/admin  {}
ready_cleared        --       admin          {}
readiness_reset      --       system         {}
session_opened       map/hero system         first_side, seed_source, home_seed, away_seed
session_reset        map/hero admin/system   {}
session_completed    map/hero system         {}
round_opened         map/hero system         round, first_side
opener_elected       map/hero captain/admin  round, first_side
acted                map/hero captain/admin  step_index, round, action, item_id, target_player_id
draft_locked         map/hero captain/admin  step_index, round, items
draft_set            map/hero admin          step_index, round, items
step_revealed        map/hero system         step_index, round
step_auto_resolved   map/hero system         step_index, round, action, item_ids
step_timed_out       map/hero system         step_index, round, policy, sides
step_disputed        map/hero captain        step_index, attempt
step_reopened        map/hero admin          step_index
undo_requested       map/hero captain        step_index
undo_withdrawn       map/hero captain        step_index
undo_applied         map/hero captain        step_index
map_reported         --       captain        position, home_score, away_score, game_id
map_disputed         --       system         position, game_id
series_reported      --       captain        home_score, away_score
paused               map/hero admin          {}
resumed              map/hero admin          paused_seconds
timer_extended       map/hero admin          seconds, step_index
session_cancelled    map/hero admin          {} + reason
technical_loss       --       admin          loser_side, home_score, away_score + reason
==================== ======== ============== ===============================================
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.tournament.encounter_result_audit import EncounterResultAudit
from shared.models.tournament.encounter_room_event import EncounterRoomEvent
from shared.repository import EncounterResultAuditRepository, EncounterRoomEventRepository
from src.schemas import pregame_rooms as schemas

__all__ = (
    "HISTORY_LIMIT_DEFAULT",
    "HISTORY_LIMIT_MAX",
    "RoomHistoryService",
    "record_room_event",
    "room_history_service",
)

HISTORY_LIMIT_DEFAULT = 200
HISTORY_LIMIT_MAX = 500


async def record_room_event(
    session: AsyncSession,
    encounter_id: int,
    *,
    action: str,
    source: str,
    kind: str | None = None,
    side: str | None = None,
    actor_auth_user_id: int | None = None,
    reason: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Append one journal row to the caller's transaction. Never commits."""
    session.add(
        EncounterRoomEvent(
            encounter_id=encounter_id,
            action=action,
            source=source,
            kind=kind,
            side=side,
            actor_auth_user_id=actor_auth_user_id,
            # A reason that is only whitespace is no reason at all, and NULL is
            # what every reader branches on.
            reason=(reason or "").strip() or None,
            data=data or {},
        )
    )


class RoomHistoryService:
    """The organizer's read of a room's whole story."""

    def __init__(
        self,
        *,
        event_repo: EncounterRoomEventRepository = EncounterRoomEventRepository(),
        audit_repo: EncounterResultAuditRepository = EncounterResultAuditRepository(),
    ) -> None:
        self.event_repo = event_repo
        self.audit_repo = audit_repo

    async def list_history(
        self, session: AsyncSession, encounter_id: int, *, limit: int = HISTORY_LIMIT_DEFAULT
    ) -> schemas.PregameRoomHistoryRead:
        """Both journals of one encounter, merged newest first.

        One query per table, each taking ``limit`` rows: the merge can only drop
        rows, so neither side can hide behind the other's head. Sorting the two
        heads in Python costs a 400-element sort and saves the UNION a database
        would have to re-plan over two different row shapes.
        """
        limit = max(1, min(limit, HISTORY_LIMIT_MAX))
        room_rows = await self.event_repo.list_with_actor(session, encounter_id, limit=limit)
        result_rows = await self.audit_repo.list_with_actor(session, encounter_id, limit=limit)
        # Sorted on the NUMERIC id, not the ``room:``/``result:`` key the entry
        # carries: both tables stamp ``created_at`` from the transaction clock,
        # so rows written by one request share it to the microsecond and the id
        # is what breaks the tie into the order they were appended in -- which
        # "room:9" vs "room:12" would get backwards.
        merged = [(row.created_at, row.id, _room_entry(row, actor_name)) for row, actor_name in room_rows]
        merged += [
            (row.created_at, row.id, _result_entry(row, actor_name, position))
            for row, actor_name, position in result_rows
        ]
        merged.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return schemas.PregameRoomHistoryRead(
            encounter_id=encounter_id, entries=[entry for _at, _id, entry in merged[:limit]]
        )


def _room_entry(row: EncounterRoomEvent, actor_name: str | None) -> schemas.PregameRoomHistoryEntry:
    return schemas.PregameRoomHistoryEntry(
        id=f"room:{row.id}",
        at=row.created_at,
        origin="room",
        action=row.action,
        kind=row.kind,
        source=row.source,
        side=row.side,
        actor_auth_user_id=row.actor_auth_user_id,
        actor_name=actor_name,
        reason=row.reason,
        data=dict(row.data or {}),
    )


def _result_entry(
    row: EncounterResultAudit, actor_name: str | None, position: int | None
) -> schemas.PregameRoomHistoryEntry:
    """A result-audit row in the room journal's shape.

    ``actor_auth_user_id`` stays NULL even when the row has an actor: that
    column is a PLAYER identity, and handing it out as an auth id would make
    two different id spaces look like one. The name still renders.
    """
    data: dict[str, Any] = {
        "home_score_before": row.home_score_before,
        "away_score_before": row.away_score_before,
        "home_score": row.home_score_after,
        "away_score": row.away_score_after,
        "result_status": str(getattr(row.to_result_status, "value", row.to_result_status)),
    }
    if position is not None:
        data["position"] = position
    if row.game_id is not None:
        data["game_id"] = row.game_id
    return schemas.PregameRoomHistoryEntry(
        id=f"result:{row.id}",
        at=row.created_at,
        origin="result",
        action=str(getattr(row.action, "value", row.action)),
        kind=None,
        # The audit's ``source`` is a finalize/game-result source, a wider
        # vocabulary than the room's three actors: everything that is not a
        # person acting as one of the two is the machine deciding.
        source=row.source if row.source in ("admin", "captain") else "system",
        side=None,
        actor_auth_user_id=None,
        actor_name=actor_name,
        reason=row.reason,
        data=data,
    )


room_history_service = RoomHistoryService()
