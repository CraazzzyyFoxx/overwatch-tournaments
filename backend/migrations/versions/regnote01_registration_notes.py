"""Organizer notes with file attachments on registrations and registration teams.

Revision ID: regnote01_registration_notes
Revises: pbprog01_progressive_pool_mode
Create Date: 2026-11-14 00:00:00.000000

``registration.note`` is a staff-only timeline on ONE registration or ONE
registration team (exactly one target, enforced by a check constraint);
``registration.note_attachment`` holds the private S3 objects attached to a note.
``registration.admin_notes`` stays: it is the short summary the table, the sheet
sync and the pool export already read.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "regnote01_registration_notes"
down_revision: str | Sequence[str] | None = "pbprog01_progressive_pool_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "note",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "tournament_id",
            sa.BigInteger(),
            sa.ForeignKey("tournament.tournament.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "registration_id",
            sa.BigInteger(),
            sa.ForeignKey("registration.registration.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "registration_team_id",
            sa.BigInteger(),
            sa.ForeignKey("registration.team.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("author_id", sa.BigInteger(), sa.ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(registration_id IS NULL) <> (registration_team_id IS NULL)",
            name="ck_registration_note_one_target",
        ),
        schema="registration",
    )
    op.create_index("ix_registration_note_tournament_id", "note", ["tournament_id"], schema="registration")
    op.create_index("ix_registration_note_registration_id", "note", ["registration_id"], schema="registration")
    op.create_index(
        "ix_registration_note_registration_team_id", "note", ["registration_team_id"], schema="registration"
    )

    op.create_table(
        "note_attachment",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "note_id",
            sa.BigInteger(),
            sa.ForeignKey("registration.note.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("s3_key", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), sa.ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True),
        schema="registration",
    )
    op.create_index("ix_registration_note_attachment_note_id", "note_attachment", ["note_id"], schema="registration")


def downgrade() -> None:
    op.drop_table("note_attachment", schema="registration")
    op.drop_table("note", schema="registration")
