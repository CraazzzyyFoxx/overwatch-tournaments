"""add_pg_trgm_extension

Revision ID: e5f7a9b3c4d5
Revises: d4e6f8a2b3c4
Create Date: 2026-04-09 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f7a9b3c4d5"
down_revision: str | None = "d4e6f8a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
