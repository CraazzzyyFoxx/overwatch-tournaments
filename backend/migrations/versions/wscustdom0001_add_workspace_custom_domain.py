"""add workspace custom-domain columns

Revision ID: wscustdom0001
Revises: wsdomain0001
Create Date: 2026-07-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wscustdom0001"
down_revision: str | None = "wsdomain0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("custom_domain", sa.String(length=255), nullable=True))
    op.add_column("workspace", sa.Column("custom_domain_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workspace", sa.Column("custom_domain_verification_token", sa.String(length=64), nullable=True))
    op.create_index("ix_workspace_custom_domain", "workspace", ["custom_domain"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_workspace_custom_domain", table_name="workspace")
    op.drop_column("workspace", "custom_domain_verification_token")
    op.drop_column("workspace", "custom_domain_verified_at")
    op.drop_column("workspace", "custom_domain")
