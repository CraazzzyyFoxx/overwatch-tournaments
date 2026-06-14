"""add_user_avatar_url

Revision ID: i9d1e3f7g8h9
Revises: h8c0d2e6f7g8
Create Date: 2026-04-09 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "i9d1e3f7g8h9"
down_revision: Union[str, None] = "h8c0d2e6f7g8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("avatar_url", sa.String(500), nullable=True), schema="players")


def downgrade() -> None:
    op.drop_column("user", "avatar_url", schema="players")
