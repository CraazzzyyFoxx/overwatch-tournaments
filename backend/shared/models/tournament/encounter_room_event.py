"""Append-only journal of an encounter's pre-game room.

The room already had three partial stories -- ``encounter_result_audit`` (what
the SERIES score did), ``admin_audit`` (what an organizer clicked) and the
pick-ban submission log (what each side answered) -- and none of them answers
the question staff actually ask: "what happened in this room, in order". This
table is that one ordered story, written by every readiness, session, step,
report and override path.

Keyed by ENCOUNTER, never by session: a session reset deletes the
``pick_ban_session`` row, and the reset is exactly the moment whose history
matters most. Rows are never updated or deleted; the encounter's
``ON DELETE CASCADE`` is the only thing that removes them. A NULL
``actor_auth_user_id`` means the clock or the engine acted, not a person.
"""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db
from shared.models.identity.auth_user import AuthUser
from shared.models.tournament.encounter import Encounter

__all__ = ("EncounterRoomEvent",)


class EncounterRoomEvent(db.TimeStampIntegerMixin):
    """One thing that happened in a pre-game room."""

    __tablename__ = "encounter_room_event"
    __table_args__ = (
        # The only access pattern: this encounter's journal, newest first.
        Index("ix_encounter_room_event_encounter_created", "encounter_id", "created_at"),
        {"schema": "tournament"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"))
    #: ``"map"``/``"hero"``; NULL for a room-level row (readiness, reports)
    #: that belongs to neither pick-ban phase.
    kind: Mapped[str | None] = mapped_column(String(8), nullable=True)
    #: Free vocabulary rather than a PG enum: the room grows actions far faster
    #: than the result states an enum is worth gating, and a journal that
    #: refuses to record an action it has not migrated for is worse than useless.
    action: Mapped[str] = mapped_column(String(64))
    #: ``"captain"``/``"admin"``/``"system"``.
    source: Mapped[str] = mapped_column(String(16))
    #: The side acted BY or FOR -- a captain's own action and an admin's action
    #: on their behalf are the same side.
    side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # SET NULL so a deleted account leaves the row that says what it did.
    actor_auth_user_id: Mapped[int | None] = mapped_column(ForeignKey(AuthUser.id, ondelete="SET NULL"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    #: Action-specific payload (see ``services/encounter/room_journal.py`` for
    #: the per-action keys). Always an object, never NULL: a reader branches on
    #: the keys it finds, not on whether there is a document at all.
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
