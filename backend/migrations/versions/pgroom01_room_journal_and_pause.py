"""Pre-game room journal + the organizer's pause on a pick-ban session.

Revision ID: pgroom01
Revises: bsplit02
Create Date: 2026-10-02 00:00:00.000000

``tournament.encounter_room_event`` is the room's ordered story (readiness,
session lifecycle, every step, reports, overrides). Keyed by ENCOUNTER rather
than by session on purpose: resetting a session deletes its row, and the reset
is exactly the event whose history matters.

``tournament.pick_ban_session.paused_at`` is the hold an organizer puts on a
live room: non-NULL suspends the step clock without scrapping anything. NULL
for every existing row, which is the current behaviour exactly -- pure expand.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "pgroom01"
down_revision: str | Sequence[str] | None = "bsplit02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "encounter_room_event",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("encounter_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=True),
        sa.Column("actor_auth_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["encounter_id"], ["tournament.encounter.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_auth_user_id"], ["auth.user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="tournament",
    )
    # The only access pattern there is: one encounter's journal, newest first.
    op.create_index(
        "ix_encounter_room_event_encounter_created",
        "encounter_room_event",
        ["encounter_id", "created_at"],
        schema="tournament",
    )
    op.add_column(
        "pick_ban_session",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("pick_ban_session", "paused_at", schema="tournament")
    op.drop_index("ix_encounter_room_event_encounter_created", "encounter_room_event", schema="tournament")
    op.drop_table("encounter_room_event", schema="tournament")
