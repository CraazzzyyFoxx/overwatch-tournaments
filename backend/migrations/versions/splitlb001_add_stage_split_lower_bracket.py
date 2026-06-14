"""add tournament.stage.split_lower_bracket

Boolean flag on double-elimination playoff stages: when true, the teams
advancing from each group (advance_count) are split evenly between the Upper
and Lower bracket on activate-and-generate auto-wiring. Defaults to false, so
existing stages keep sending all advancing teams to the Upper bracket.

Revision ID: splitlb001
Revises: advcount001
Create Date: 2026-06-07 01:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "splitlb001"
down_revision: str | Sequence[str] | None = "advcount001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stage",
        sa.Column(
            "split_lower_bracket",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("stage", "split_lower_bracket", schema="tournament")
