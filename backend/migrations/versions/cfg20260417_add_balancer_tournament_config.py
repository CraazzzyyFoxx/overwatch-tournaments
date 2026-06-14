"""add_balancer_tournament_config

Revision ID: cfg20260417
Revises: merge0002, a7v1w5x6y7z8
Create Date: 2026-04-17 21:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "cfg20260417"
down_revision: Union[str, Sequence[str], None] = ("merge0002", "a7v1w5x6y7z8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tournament_config",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("config_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["auth.user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament_id", name="uq_balancer_tournament_config_tournament"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_tournament_config_tournament_id"),
        "tournament_config",
        ["tournament_id"],
        unique=False,
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_tournament_config_workspace_id"),
        "tournament_config",
        ["workspace_id"],
        unique=False,
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_balancer_tournament_config_workspace_id"),
        table_name="tournament_config",
        schema="balancer",
    )
    op.drop_index(
        op.f("ix_balancer_tournament_config_tournament_id"),
        table_name="tournament_config",
        schema="balancer",
    )
    op.drop_table("tournament_config", schema="balancer")
