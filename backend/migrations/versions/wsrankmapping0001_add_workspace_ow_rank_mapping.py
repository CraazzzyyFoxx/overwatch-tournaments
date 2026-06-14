"""add ow_rank_min/ow_rank_max to division_grid_tier

Revision ID: wsrankmapping0001
Revises: tcomp001
Create Date: 2026-06-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wsrankmapping0001"
down_revision: str | None = "tcomp001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("division_grid_tier", sa.Column("ow_rank_min", sa.BigInteger(), nullable=True))
    op.add_column("division_grid_tier", sa.Column("ow_rank_max", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("division_grid_tier", "ow_rank_max")
    op.drop_column("division_grid_tier", "ow_rank_min")
