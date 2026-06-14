"""add match.code column for captain-reported OW lobby codes.

Revision ID: matchcode001
Revises: phasec0001
Create Date: 2026-04-18 08:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "matchcode001"
down_revision: Union[str, Sequence[str], None] = "phasec0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "match",
        sa.Column("code", sa.String(), nullable=True),
        schema="matches",
    )


def downgrade() -> None:
    op.drop_column("match", "code", schema="matches")
