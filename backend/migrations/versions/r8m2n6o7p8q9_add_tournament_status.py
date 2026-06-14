"""add_tournament_status

Adds tournament status state machine, registration/check-in timestamps,
and configurable scoring points to tournament table.

Revision ID: r8m2n6o7p8q9
Revises: q7l9m1n5o6p7
Create Date: 2026-04-10 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "r8m2n6o7p8q9"
down_revision: Union[str, None] = "q7l9m1n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_tournament_status_enum = sa.Enum(
    "registration",
    "draft",
    "check_in",
    "live",
    "playoffs",
    "completed",
    "archived",
    name="tournamentstatus",
    schema="tournament",
)


def upgrade() -> None:
    _tournament_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tournament",
        sa.Column(
            "status",
            _tournament_status_enum,
            server_default="draft",
            nullable=False,
        ),
        schema="tournament",
    )
    op.add_column(
        "tournament",
        sa.Column("registration_opens_at", sa.DateTime(timezone=True), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "tournament",
        sa.Column("registration_closes_at", sa.DateTime(timezone=True), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "tournament",
        sa.Column("check_in_opens_at", sa.DateTime(timezone=True), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "tournament",
        sa.Column("check_in_closes_at", sa.DateTime(timezone=True), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "tournament",
        sa.Column("win_points", sa.Float(), server_default="1.0", nullable=False),
        schema="tournament",
    )
    op.add_column(
        "tournament",
        sa.Column("draw_points", sa.Float(), server_default="0.5", nullable=False),
        schema="tournament",
    )
    op.add_column(
        "tournament",
        sa.Column("loss_points", sa.Float(), server_default="0.0", nullable=False),
        schema="tournament",
    )

    # Backfill status from is_finished
    op.execute("""
        UPDATE tournament.tournament
        SET status = CASE
            WHEN is_finished = true THEN 'completed'
            ELSE 'live'
        END::tournament.tournamentstatus
    """)

    op.create_index(
        "ix_tournament_tournament_status",
        "tournament",
        ["status"],
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_index("ix_tournament_tournament_status", table_name="tournament", schema="tournament")
    op.drop_column("tournament", "loss_points", schema="tournament")
    op.drop_column("tournament", "draw_points", schema="tournament")
    op.drop_column("tournament", "win_points", schema="tournament")
    op.drop_column("tournament", "check_in_closes_at", schema="tournament")
    op.drop_column("tournament", "check_in_opens_at", schema="tournament")
    op.drop_column("tournament", "registration_closes_at", schema="tournament")
    op.drop_column("tournament", "registration_opens_at", schema="tournament")
    op.drop_column("tournament", "status", schema="tournament")
    _tournament_status_enum.drop(op.get_bind(), checkfirst=True)
