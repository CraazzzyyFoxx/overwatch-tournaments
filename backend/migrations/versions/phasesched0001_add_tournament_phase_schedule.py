"""tournament phase schedule + time-driven state machine

Revision ID: phasesched0001
Revises: teamsr0001
Create Date: 2026-07-17 00:00:00.000000

Reworks the tournament lifecycle:

- New ``tournament.tournament_phase_schedule`` table — one row per phase with
  ``starts_at`` (drives the automated status transition) and optional
  ``ends_at`` (closes the phase's action window early; never changes status).
- ``tournament.auto_transitions_enabled`` — the worker tick only touches
  tournaments with this flag on. Existing tournaments are backfilled to
  ``false`` (deploy safety: nothing flips status on release); new rows default
  to ``true``.
- ``tournament.allow_late_registration`` — registration stays open past the
  REGISTRATION phase until the tournament finishes.
- ``tournament.status`` default changes ``draft`` -> ``registration`` (a fresh
  tournament starts in REGISTRATION; DRAFT is the team-draft phase).
- The flat window columns (``registration_opens_at/closes_at``,
  ``check_in_opens_at/closes_at``) are converted into schedule rows and
  dropped, as are ``balancer.registration_form.opens_at/closes_at`` — the
  schedule table is now the single home for phase timing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "phasesched0001"
down_revision: str | Sequence[str] | None = "teamsr0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_ENUM = postgresql.ENUM(name="tournamentstatus", schema="tournament", create_type=False)


def upgrade() -> None:
    op.create_table(
        "tournament_phase_schedule",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "tournament_id",
            sa.BigInteger(),
            sa.ForeignKey("tournament.tournament.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", _STATUS_ENUM, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tournament_id", "status", name="uq_tournament_phase_schedule_phase"),
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_tournament_phase_schedule_window"),
        schema="tournament",
    )
    op.create_index(
        "ix_tournament_tournament_phase_schedule_tournament_id",
        "tournament_phase_schedule",
        ["tournament_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_tournament_tournament_phase_schedule_starts_at",
        "tournament_phase_schedule",
        ["starts_at"],
        schema="tournament",
    )

    # Existing tournaments: automation OFF (deploy safety); new rows: ON.
    op.add_column(
        "tournament",
        sa.Column("auto_transitions_enabled", sa.Boolean(), nullable=False, server_default="false"),
        schema="tournament",
    )
    op.alter_column("tournament", "auto_transitions_enabled", server_default="true", schema="tournament")
    op.add_column(
        "tournament",
        sa.Column("allow_late_registration", sa.Boolean(), nullable=False, server_default="false"),
        schema="tournament",
    )
    op.alter_column("tournament", "status", server_default="registration", schema="tournament")

    # Convert the flat window columns into schedule rows. ``starts_at`` is NOT
    # NULL, so a close-only window anchors on the tournament's creation time.
    op.execute(
        sa.text(
            """
            INSERT INTO tournament.tournament_phase_schedule (tournament_id, status, starts_at, ends_at)
            SELECT id, 'registration', COALESCE(registration_opens_at, created_at), registration_closes_at
            FROM tournament.tournament
            WHERE (registration_opens_at IS NOT NULL OR registration_closes_at IS NOT NULL)
              AND (registration_closes_at IS NULL
                   OR registration_closes_at > COALESCE(registration_opens_at, created_at))
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO tournament.tournament_phase_schedule (tournament_id, status, starts_at, ends_at)
            SELECT id, 'check_in', COALESCE(check_in_opens_at, created_at), check_in_closes_at
            FROM tournament.tournament
            WHERE (check_in_opens_at IS NOT NULL OR check_in_closes_at IS NOT NULL)
              AND (check_in_closes_at IS NULL
                   OR check_in_closes_at > COALESCE(check_in_opens_at, created_at))
            """
        )
    )

    op.drop_column("tournament", "registration_opens_at", schema="tournament")
    op.drop_column("tournament", "registration_closes_at", schema="tournament")
    op.drop_column("tournament", "check_in_opens_at", schema="tournament")
    op.drop_column("tournament", "check_in_closes_at", schema="tournament")

    op.drop_column("registration_form", "opens_at", schema="balancer")
    op.drop_column("registration_form", "closes_at", schema="balancer")


def downgrade() -> None:
    op.add_column(
        "registration_form", sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True), schema="balancer"
    )
    op.add_column(
        "registration_form", sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True), schema="balancer"
    )

    for column in (
        "registration_opens_at",
        "registration_closes_at",
        "check_in_opens_at",
        "check_in_closes_at",
    ):
        op.add_column(
            "tournament", sa.Column(column, sa.DateTime(timezone=True), nullable=True), schema="tournament"
        )

    op.execute(
        sa.text(
            """
            UPDATE tournament.tournament t
            SET registration_opens_at = s.starts_at, registration_closes_at = s.ends_at
            FROM tournament.tournament_phase_schedule s
            WHERE s.tournament_id = t.id AND s.status = 'registration'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE tournament.tournament t
            SET check_in_opens_at = s.starts_at, check_in_closes_at = s.ends_at
            FROM tournament.tournament_phase_schedule s
            WHERE s.tournament_id = t.id AND s.status = 'check_in'
            """
        )
    )

    op.alter_column("tournament", "status", server_default="draft", schema="tournament")
    op.drop_column("tournament", "allow_late_registration", schema="tournament")
    op.drop_column("tournament", "auto_transitions_enabled", schema="tournament")

    op.drop_index(
        "ix_tournament_tournament_phase_schedule_starts_at",
        table_name="tournament_phase_schedule",
        schema="tournament",
    )
    op.drop_index(
        "ix_tournament_tournament_phase_schedule_tournament_id",
        table_name="tournament_phase_schedule",
        schema="tournament",
    )
    op.drop_table("tournament_phase_schedule", schema="tournament")
