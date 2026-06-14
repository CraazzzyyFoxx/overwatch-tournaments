"""add_balancer_registration_status_catalog

Revision ID: z6u0v4w5x6y7
Revises: y5t9u3v4w5x6
Create Date: 2026-04-14 15:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "z6u0v4w5x6y7"
down_revision: Union[str, None] = "y5t9u3v4w5x6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "registration_status",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("icon_slug", sa.String(length=128), nullable=True),
        sa.Column("icon_color", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "scope",
            "slug",
            name="uq_balancer_registration_status_workspace_scope_slug",
        ),
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_registration_status_workspace_scope",
        "registration_status",
        ["workspace_id", "scope"],
        unique=False,
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_balancer_registration_status_workspace_scope",
        table_name="registration_status",
        schema="balancer",
    )
    op.drop_table("registration_status", schema="balancer")
