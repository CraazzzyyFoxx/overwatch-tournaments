"""add stage max_rounds.

Revision ID: stagemax001
Revises: matchcode001
Create Date: 2026-04-18 21:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "stagemax001"
down_revision: str | Sequence[str] | None = "matchcode001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stage",
        sa.Column("max_rounds", sa.Integer(), server_default="5", nullable=False),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("stage", "max_rounds", schema="tournament")
