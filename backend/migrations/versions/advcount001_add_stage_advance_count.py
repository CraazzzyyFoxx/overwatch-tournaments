"""add tournament.stage.advance_count

Configurable number of teams advancing from each group of a group stage to the
next (playoff) stage. NULL = unset (frontend derives from bracket wiring or
falls back to a default), so existing stages keep their current behaviour.

Revision ID: advcount001
Revises: tiebreak001
Create Date: 2026-06-07 00:30:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "advcount001"
down_revision: str | Sequence[str] | None = "tiebreak001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stage",
        sa.Column("advance_count", sa.Integer(), nullable=True),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("stage", "advance_count", schema="tournament")
