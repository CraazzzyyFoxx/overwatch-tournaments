"""add overwatch rank tables

Rank telemetry collected from OverFast: a per-run time series of competitive
ranks (overwatch_rank.rank_snapshot) and per-battle-tag collection bookkeeping
(overwatch_rank.battle_tag_state). Isolated in its own schema so the feature is
self-contained and player-identity tables stay untouched.

Revision ID: owrank0001
Revises: reghero0001
Create Date: 2026-06-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "owrank0001"
down_revision: str | Sequence[str] | None = "reghero0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS overwatch_rank")

    op.create_table(
        "rank_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("battle_tag_id", sa.BigInteger(), nullable=False),
        sa.Column("battle_tag", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("division", sa.String(length=32), nullable=True),
        sa.Column("tier", sa.SmallInteger(), nullable=True),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("rank_value", sa.Integer(), nullable=True),
        sa.Column("mapping_version", sa.String(length=64), nullable=True),
        sa.Column("is_ranked", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(length=32), server_default="scheduled", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["battle_tag_id"], ["players.battle_tag.id"], ondelete="CASCADE"),
        schema="overwatch_rank",
    )
    op.create_index(
        "ix_overwatch_rank_rank_snapshot_captured_at",
        "rank_snapshot",
        ["captured_at"],
        schema="overwatch_rank",
    )
    op.create_index(
        "ix_rank_snapshot_user_captured",
        "rank_snapshot",
        ["user_id", "captured_at"],
        schema="overwatch_rank",
    )
    op.create_index(
        "ix_rank_snapshot_series_captured",
        "rank_snapshot",
        ["battle_tag_id", "role", "platform", "captured_at"],
        schema="overwatch_rank",
    )

    op.create_table(
        "battle_tag_state",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("battle_tag_id", sa.BigInteger(), nullable=False),
        sa.Column("battle_tag", sa.String(length=255), nullable=False),
        sa.Column("player_id_slug", sa.String(length=255), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_eligible_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("priority_tier", sa.SmallInteger(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["battle_tag_id"], ["players.battle_tag.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["last_snapshot_id"], ["overwatch_rank.rank_snapshot.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("battle_tag_id", name="uq_battle_tag_state_battle_tag_id"),
        schema="overwatch_rank",
    )
    op.create_index(
        "ix_battle_tag_state_due",
        "battle_tag_state",
        ["status", "next_eligible_at", "last_checked_at"],
        schema="overwatch_rank",
    )
    op.create_index(
        "ix_battle_tag_state_priority",
        "battle_tag_state",
        ["priority_tier", "last_checked_at"],
        schema="overwatch_rank",
    )


def downgrade() -> None:
    op.drop_index("ix_battle_tag_state_priority", table_name="battle_tag_state", schema="overwatch_rank")
    op.drop_index("ix_battle_tag_state_due", table_name="battle_tag_state", schema="overwatch_rank")
    op.drop_table("battle_tag_state", schema="overwatch_rank")
    op.drop_index("ix_rank_snapshot_series_captured", table_name="rank_snapshot", schema="overwatch_rank")
    op.drop_index("ix_rank_snapshot_user_captured", table_name="rank_snapshot", schema="overwatch_rank")
    op.drop_index("ix_overwatch_rank_rank_snapshot_captured_at", table_name="rank_snapshot", schema="overwatch_rank")
    op.drop_table("rank_snapshot", schema="overwatch_rank")
    op.execute("DROP SCHEMA IF EXISTS overwatch_rank")
