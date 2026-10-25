"""Stream chronology: the ``stream`` schema with ``stream.session``, and a per-tournament POV stream delay.

Revision ID: strchron01
Revises: anlsd01
Create Date: 2026-10-25 12:00:00.000000

``stream.session`` is the first table stream-service owns: one row per participant POV broadcast a poll tick saw
live, per tournament, unique on ``(tournament_id, stream_id)`` so every tick of the same broadcast upserts one row.
``vod_id`` is resolved later from Helix; ``vod_gone_at`` hides a VOD that expired or was deleted. No backfill: only
broadcasts observed after this revision exist.

``tournament.tournament`` gains ``pov_stream_delay_s`` (0..900, Twitch's maximum delay): how far behind real time the
participants' streams run, per the tournament's rules, added to every chapter timestamp. ``DEFAULT 0`` with
``NOT NULL`` is a metadata-only ADD COLUMN on PostgreSQL 11+, and the CHECK holds for the default, so the table is
not rewritten; ``lock_timeout`` keeps the ACCESS EXCLUSIVE wait from queueing every tournament read behind it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "strchron01"
down_revision: str | Sequence[str] | None = "anlsd01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS stream")

    op.create_table(
        "session",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("broadcaster_id", sa.String(length=32), nullable=False),
        sa.Column("stream_id", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vod_id", sa.String(length=32), nullable=True),
        sa.Column("vod_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vod_gone_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament_id", "stream_id", name="uq_stream_session_tournament_stream"),
        schema="stream",
    )
    op.create_index("ix_stream_session_tournament_started", "session", ["tournament_id", "started_at"], schema="stream")

    op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    op.add_column(
        "tournament",
        sa.Column("pov_stream_delay_s", sa.Integer(), server_default="0", nullable=False),
        schema="tournament",
    )
    op.create_check_constraint(
        "ck_tournament_pov_stream_delay_s",
        "tournament",
        "pov_stream_delay_s BETWEEN 0 AND 900",
        schema="tournament",
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    op.drop_constraint("ck_tournament_pov_stream_delay_s", "tournament", type_="check", schema="tournament")
    op.drop_column("tournament", "pov_stream_delay_s", schema="tournament")

    op.drop_index("ix_stream_session_tournament_started", table_name="session", schema="stream")
    op.drop_table("session", schema="stream")
    op.execute("DROP SCHEMA IF EXISTS stream")
