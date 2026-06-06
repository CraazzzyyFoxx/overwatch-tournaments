"""add tournament.standing.score_differential

Persist the map/score differential tie-breaker so the API can surface an
accurate value instead of approximating it as ``win*2 - lose``. The engine
already computes ``RankedStageTeam.score_differential`` for group stages.

Revision ID: tiebreak001
Revises: draft0003
Create Date: 2026-06-07 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tiebreak001"
down_revision: str | Sequence[str] | None = "draft0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "standing",
        sa.Column("score_differential", sa.Integer(), nullable=True),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("standing", "score_differential", schema="tournament")
