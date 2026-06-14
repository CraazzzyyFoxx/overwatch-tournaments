"""add_linear_analytics_fields

Revision ID: a1c3e5g7i9k1
Revises: z6u0v4w5x6y7
Create Date: 2026-04-15 18:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1c3e5g7i9k1"
down_revision: Union[str, None] = "z6u0v4w5x6y7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shifts",
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        schema="analytics",
    )
    op.add_column(
        "shifts",
        sa.Column("effective_evidence", sa.Float(), nullable=False, server_default="0"),
        schema="analytics",
    )
    op.add_column(
        "shifts",
        sa.Column("sample_tournaments", sa.Integer(), nullable=False, server_default="0"),
        schema="analytics",
    )
    op.add_column(
        "shifts",
        sa.Column("sample_matches", sa.Integer(), nullable=False, server_default="0"),
        schema="analytics",
    )
    op.add_column(
        "shifts",
        sa.Column("log_coverage", sa.Float(), nullable=False, server_default="0"),
        schema="analytics",
    )

    op.execute(
        sa.text(
            """
            INSERT INTO analytics.algorithms (name)
            VALUES
              ('Linear Stable'),
              ('Linear Trend'),
              ('Linear Hybrid')
            ON CONFLICT (name) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM analytics.algorithms
            WHERE name IN ('Linear Stable', 'Linear Trend', 'Linear Hybrid')
            """
        )
    )

    op.drop_column("shifts", "log_coverage", schema="analytics")
    op.drop_column("shifts", "sample_matches", schema="analytics")
    op.drop_column("shifts", "sample_tournaments", schema="analytics")
    op.drop_column("shifts", "effective_evidence", schema="analytics")
    op.drop_column("shifts", "confidence", schema="analytics")
