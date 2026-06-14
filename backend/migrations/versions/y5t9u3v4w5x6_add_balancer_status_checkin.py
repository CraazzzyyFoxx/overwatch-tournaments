"""add_balancer_status_checkin

Add balancer_status, checked_in, checked_in_at, checked_in_by columns
to balancer.registration. Backfill balancer_status from existing
exclude_from_balancer flag. Add composite index on
(tournament_id, status, balancer_status) for active registrations.

Revision ID: y5t9u3v4w5x6
Revises: x4s8t2u3v4w5
Create Date: 2026-04-13
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "y5t9u3v4w5x6"
down_revision: Union[str, None] = "x4s8t2u3v4w5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- New columns --------------------------------------------------------
    op.add_column(
        "registration",
        sa.Column(
            "balancer_status",
            sa.String(32),
            nullable=False,
            server_default="not_in_balancer",
        ),
        schema="balancer",
    )
    op.add_column(
        "registration",
        sa.Column("checked_in", sa.Boolean(), nullable=False, server_default="false"),
        schema="balancer",
    )
    op.add_column(
        "registration",
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration",
        sa.Column(
            "checked_in_by",
            sa.Integer(),
            sa.ForeignKey("auth.user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema="balancer",
    )

    # -- Backfill balancer_status from exclude_from_balancer ----------------
    op.execute(
        sa.text("""
            UPDATE balancer.registration
            SET balancer_status = 'ready'
            WHERE status = 'approved'
              AND NOT exclude_from_balancer
              AND deleted_at IS NULL
        """)
    )

    # -- Index for new status triple ----------------------------------------
    op.create_index(
        "ix_balancer_registration_tournament_balancer_status",
        "registration",
        ["tournament_id", "status", "balancer_status"],
        schema="balancer",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_balancer_registration_tournament_balancer_status",
        table_name="registration",
        schema="balancer",
    )
    op.drop_column("registration", "checked_in_by", schema="balancer")
    op.drop_column("registration", "checked_in_at", schema="balancer")
    op.drop_column("registration", "checked_in", schema="balancer")
    op.drop_column("registration", "balancer_status", schema="balancer")
