"""add_workspace_icon_url

Revision ID: c3d5e7f9a1b2
Revises: b8e2f4a1c903
Create Date: 2026-04-06 03:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c3d5e7f9a1b2"
down_revision: Union[str, None] = "b8e2f4a1c903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("icon_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace", "icon_url")
