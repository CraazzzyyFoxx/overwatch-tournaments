"""add_division_grid_json

Revision ID: g7b9c1d5e6f7
Revises: f6a8b0c4d5e6
Create Date: 2026-04-09 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers, used by Alembic.
revision: str = "g7b9c1d5e6f7"
down_revision: Union[str, None] = "f6a8b0c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("division_grid_json", JSON, nullable=True))
    op.add_column(
        "tournament",
        sa.Column("division_grid_json", JSON, nullable=True),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("tournament", "division_grid_json", schema="tournament")
    op.drop_column("workspace", "division_grid_json")
