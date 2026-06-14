"""add balancer.workspace_config table

Revision ID: wsbcfg0001
Revises: wsrankmapping0001
Create Date: 2026-06-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wsbcfg0001"
down_revision: str | None = "wsrankmapping0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["auth.user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", name="uq_balancer_workspace_config_workspace"),
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_workspace_config_workspace_id",
        "workspace_config",
        ["workspace_id"],
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_balancer_workspace_config_workspace_id",
        table_name="workspace_config",
        schema="balancer",
    )
    op.drop_table("workspace_config", schema="balancer")
