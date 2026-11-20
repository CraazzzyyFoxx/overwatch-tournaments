"""Opt into a third-place match on an elimination stage.

Revision ID: bronzematch01_stage_option
Revises: rankcareer02_profile_public
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bronzematch01_stage_option"
down_revision: str | Sequence[str] | None = "rankcareer02_profile_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stage",
        sa.Column("third_place_match", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("stage", "third_place_match", schema="tournament")
