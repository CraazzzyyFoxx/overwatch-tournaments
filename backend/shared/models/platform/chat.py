"""Room chat: the messages, the per-room settings, the mutes.

One set of tables serves every live room. A room is addressed by the pair
``(room_kind, room_ref_id)`` -- ``('encounter', encounter.id)`` for the pre-game
room, ``('draft', balancer.draft_session.id)`` for a draft -- so a second room
kind costs a resolver in its owning service and nothing here. The pair is not a
foreign key for the reason stated on each table below.

Design: docs/plans/2026-09-21-shared-room-chat.md.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("ChatMessage", "ChatMute", "ChatRoomSettings")


class ChatMessage(db.Base):
    """One thing somebody said in a room.

    ``db.Base`` and not ``db.TimeStampIntegerMixin``: a message is never edited,
    so an ``updated_at`` here could only ever hold a lie -- the same reasoning
    ``AuditLog`` and ``Notification`` state. Removal is ``deleted_at``, not a
    DELETE, so a moderator's action stays auditable and the row keeps ordering
    the ids around it.

    The table carries NO foreign keys, the convention ``audit_log``,
    ``event_outbox``, ``notification`` and ``realtime.workspace_event`` already
    follow: ``ON DELETE CASCADE`` on the tournament would take the record of
    what was said away with it, and a chat is most worth reading precisely when
    the thing it was about has gone wrong. Rows are collected by the retention
    job instead.

    ``author_name`` and ``author_role`` are SNAPSHOTS. Resolving either at read
    time would rewrite a whole history the moment a player renames or an
    organizer swaps a captain -- "who said this, as what" is a fact about the
    moment it was said.
    """

    __tablename__ = "chat_message"
    __table_args__ = (
        # History and "load older": both walk one room's ids.
        Index("ix_chat_message_room", "room_kind", "room_ref_id", "id"),
        # The throttle probe: one author's nth-newest message in one room.
        Index("ix_chat_message_author", "room_kind", "room_ref_id", "auth_user_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=True)
    room_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    room_ref_id: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    auth_user_id: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    author_name: Mapped[str] = mapped_column(Text(), nullable=False)
    #: home | away | captain | staff -- never ``spectator``: they cannot write.
    author_role: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_auth_user_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)


class ChatRoomSettings(db.Base):
    """What an organizer changed about one room. Absent row = the kind's default.

    Lazily materialized on purpose: the default differs per room kind (a draft
    is a show and spectators read it; a pre-game room is where custom-lobby
    codes are exchanged and they do not), and a room nobody reconfigures should
    cost no row. The composite primary key makes the toggle a plain upsert.
    """

    __tablename__ = "chat_room_settings"

    room_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    room_ref_id: Mapped[int] = mapped_column(BigInteger(), primary_key=True)
    spectators_can_read: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    updated_by_auth_user_id: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class ChatMute(db.Base):
    """One account silenced in one room.

    Scoped to the room, never global: a captain who had to be silenced in one
    draft has done nothing in the next tournament's pre-game room, and a global
    list would be a ban system with none of a ban system's review process.

    ``muted_until IS NULL`` is the indefinite mute. Expiry is evaluated at read
    time (``muted_until IS NULL OR muted_until > now()``) and never by a
    sweeper: an elapsed row is simply inert, which means a clock skew or a
    missed job can only fail open on schedule, never keep somebody muted past
    their time. The retention job collects long-dead rows.
    """

    __tablename__ = "chat_mute"

    room_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    room_ref_id: Mapped[int] = mapped_column(BigInteger(), primary_key=True)
    auth_user_id: Mapped[int] = mapped_column(BigInteger(), primary_key=True)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_by_auth_user_id: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
