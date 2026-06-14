"""add_achievement_image_url

Revision ID: d4e6f8a2b3c4
Revises: c3d5e7f9a1b2
Create Date: 2026-04-08 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d4e6f8a2b3c4"
down_revision: Union[str, None] = "c3d5e7f9a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "achievement",
        sa.Column("image_url", sa.String(), nullable=True),
        schema="achievements",
    )


def downgrade() -> None:
    op.drop_column("achievement", "image_url", schema="achievements")
