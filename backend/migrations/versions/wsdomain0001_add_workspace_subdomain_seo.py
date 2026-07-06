"""add workspace subdomain + seo columns

Revision ID: wsdomain0001
Revises: wsbrand0001
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wsdomain0001"
down_revision: str | None = "wsbrand0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("subdomain", sa.String(length=63), nullable=True))
    op.add_column("workspace", sa.Column("seo_title", sa.String(), nullable=True))
    op.add_column("workspace", sa.Column("seo_description", sa.String(), nullable=True))
    op.create_index("ix_workspace_subdomain", "workspace", ["subdomain"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_workspace_subdomain", table_name="workspace")
    op.drop_column("workspace", "seo_description")
    op.drop_column("workspace", "seo_title")
    op.drop_column("workspace", "subdomain")
