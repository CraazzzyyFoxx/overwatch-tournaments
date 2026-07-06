"""merge_division_grid_and_auth_sessions

Revision ID: merge0001
Revises: a1b2c3d4e5f6, b9w1x5y6z7a8
Create Date: 2026-04-14 23:51:28.995821

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "merge0001"
down_revision: str | None = ("a1b2c3d4e5f6", "b9w1x5y6z7a8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
