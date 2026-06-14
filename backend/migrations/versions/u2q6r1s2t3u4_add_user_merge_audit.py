"""add_user_merge_audit

Revision ID: u2q6r1s2t3u4
Revises: stagemax001
Create Date: 2026-04-20 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "u2q6r1s2t3u4"
down_revision: Union[str, Sequence[str], None] = "stagemax001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_merge_audit",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_user_id", sa.BigInteger(), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=False),
        sa.Column("operator_auth_user_id", sa.BigInteger(), nullable=True),
        sa.Column("field_policy_json", sa.JSON(), nullable=False),
        sa.Column("moved_identity_ids_json", sa.JSON(), nullable=False),
        sa.Column("deduped_identity_ids_json", sa.JSON(), nullable=False),
        sa.Column("affected_counts_json", sa.JSON(), nullable=False),
        sa.Column("preview_snapshot_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["operator_auth_user_id"], ["auth.user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="players",
    )
    op.create_index(
        op.f("ix_players_user_merge_audit_source_user_id"),
        "user_merge_audit",
        ["source_user_id"],
        unique=False,
        schema="players",
    )
    op.create_index(
        op.f("ix_players_user_merge_audit_target_user_id"),
        "user_merge_audit",
        ["target_user_id"],
        unique=False,
        schema="players",
    )
    op.create_index(
        op.f("ix_players_user_merge_audit_operator_auth_user_id"),
        "user_merge_audit",
        ["operator_auth_user_id"],
        unique=False,
        schema="players",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_players_user_merge_audit_operator_auth_user_id"),
        table_name="user_merge_audit",
        schema="players",
    )
    op.drop_index(
        op.f("ix_players_user_merge_audit_target_user_id"),
        table_name="user_merge_audit",
        schema="players",
    )
    op.drop_index(
        op.f("ix_players_user_merge_audit_source_user_id"),
        table_name="user_merge_audit",
        schema="players",
    )
    op.drop_table("user_merge_audit", schema="players")
