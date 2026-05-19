"""add_training_workspace_scope

Revision ID: trainws0001
Revises: playersig0001
Create Date: 2026-05-18 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "trainws0001"
down_revision: str | None = "playersig0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job",
        sa.Column("training_workspace_ids", sa.JSON(), nullable=True),
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_column("job", "training_workspace_ids", schema="analytics")
