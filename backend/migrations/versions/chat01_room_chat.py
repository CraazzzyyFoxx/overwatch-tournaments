"""Room chat: messages, per-room settings, mutes.

Revision ID: chat01
Revises: regform01
Create Date: 2026-09-21 00:00:00.000000

One chat for every live room, addressed by ``(room_kind, room_ref_id)``:
``('encounter', encounter.id)`` for the pre-game room, ``('draft',
balancer.draft_session.id)`` for a draft. See
``docs/plans/2026-09-21-shared-room-chat.md``.

The pre-game chat that shipped on 2026-09-21 stored each message as a durable
``realtime.workspace_event`` row on ``encounter:{id}:chat``. Those rows are
copied into ``chat_message`` here rather than dropped: if the feature is already
deployed, its messages are real. The originals are left where they are and age
out through ``purge_stale_realtime_events``, which gains the ``%:chat`` pattern
in the same change -- deleting them here would make ``downgrade()`` lossy.

The copy reads ``payload->>'author_side'`` into ``author_role`` and falls back
to ``'staff'``: a null side in the old payload meant exactly "an organizer, not
a captain of either team", which is what ``staff`` names now.

No foreign keys on any of the three tables -- the convention ``audit_log``,
``event_outbox``, ``notification`` and ``realtime.workspace_event`` already
follow, and the models spell out why.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "chat01"
down_revision: str | Sequence[str] | None = "regform01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_message",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("room_kind", sa.String(length=16), nullable=False),
        sa.Column("room_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("auth_user_id", sa.BigInteger(), nullable=False),
        sa.Column("author_name", sa.Text(), nullable=False),
        sa.Column("author_role", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_auth_user_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_message_room", "chat_message", ["room_kind", "room_ref_id", "id"], unique=False)
    op.create_index(
        "ix_chat_message_author",
        "chat_message",
        ["room_kind", "room_ref_id", "auth_user_id", "id"],
        unique=False,
    )

    op.create_table(
        "chat_room_settings",
        sa.Column("room_kind", sa.String(length=16), nullable=False),
        sa.Column("room_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("spectators_can_read", sa.Boolean(), nullable=False),
        sa.Column("updated_by_auth_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("room_kind", "room_ref_id"),
    )

    op.create_table(
        "chat_mute",
        sa.Column("room_kind", sa.String(length=16), nullable=False),
        sa.Column("room_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("auth_user_id", sa.BigInteger(), nullable=False),
        sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_auth_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("room_kind", "room_ref_id", "auth_user_id"),
    )

    # The topic pattern is BOUND, never inlined: a literal ``:`` inside
    # ``text()`` is a bind-parameter marker, so ``'^encounter:[0-9]+:chat$'``
    # is read as the parameter ``:chat`` and the statement fails at execute
    # time with nothing supplied. ``purge_stale_realtime_events`` carries the
    # same warning for the same reason.
    op.execute(
        sa.text(
            """
            INSERT INTO chat_message (
                room_kind, room_ref_id, auth_user_id, author_name, author_role, body, created_at
            )
            SELECT 'encounter',
                   split_part(topic, ':', 2)::bigint,
                   actor_user_id,
                   COALESCE(NULLIF(payload->>'author_name', ''), 'unknown'),
                   COALESCE(NULLIF(payload->>'author_side', ''), 'staff'),
                   payload->>'text',
                   occurred_at
            FROM realtime.workspace_event
            WHERE event_type = 'chat.message'
              AND actor_user_id IS NOT NULL
              AND payload ? 'text'
              AND NULLIF(payload->>'text', '') IS NOT NULL
              AND topic ~ :topic_pattern
            ORDER BY id
            """
        ).bindparams(topic_pattern="^encounter:[0-9]+:chat$")
    )


def downgrade() -> None:
    op.drop_table("chat_mute")
    op.drop_table("chat_room_settings")
    op.drop_index("ix_chat_message_author", table_name="chat_message")
    op.drop_index("ix_chat_message_room", table_name="chat_message")
    op.drop_table("chat_message")
