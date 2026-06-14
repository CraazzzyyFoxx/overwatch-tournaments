"""add tournament.team_formation (balancer | draft)

Textual flag describing how teams are formed for a tournament.

Revision ID: draft0002
Revises: draft0001
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "draft0002"
down_revision: str | Sequence[str] | None = "draft0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column("team_formation", sa.String(), server_default="balancer", nullable=False),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("tournament", "team_formation", schema="tournament")
