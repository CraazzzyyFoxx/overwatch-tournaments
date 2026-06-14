"""merge_division_grid_and_auth_sessions

Revision ID: merge0001
Revises: a1b2c3d4e5f6, b9w1x5y6z7a8
Create Date: 2026-04-14 23:51:28.995821

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'merge0001'
down_revision: Union[str, None] = ('a1b2c3d4e5f6', 'b9w1x5y6z7a8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
