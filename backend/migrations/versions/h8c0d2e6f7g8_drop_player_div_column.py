"""drop_player_div_column

Revision ID: h8c0d2e6f7g8
Revises: g7b9c1d5e6f7
Create Date: 2026-04-09 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "h8c0d2e6f7g8"
down_revision: Union[str, None] = "g7b9c1d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("player", "div", schema="tournament")


def downgrade() -> None:
    op.add_column(
        "player",
        sa.Column("div", sa.Integer(), nullable=True),
        schema="tournament",
    )
