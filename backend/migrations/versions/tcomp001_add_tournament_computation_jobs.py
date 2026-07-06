"""add durable tournament computation jobs

Revision ID: tcomp001
Revises: splitlb001
Create Date: 2026-06-07 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tcomp001"
down_revision: str | Sequence[str] | None = "splitlb001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "computation_job",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("operation", sa.String(length=48), nullable=False),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("stage_id", sa.BigInteger(), nullable=True),
        sa.Column("stage_item_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("payload_json", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["auth.user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_item_id"], ["tournament.stage_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="tournament",
    )
    op.create_index("ix_tournament_computation_job_status", "computation_job", ["status"], schema="tournament")
    op.create_index(
        "ix_tournament_computation_job_tournament_kind",
        "computation_job",
        ["tournament_id", "kind"],
        schema="tournament",
    )
    op.create_index(
        "uq_tournament_computation_job_active_key",
        "computation_job",
        ["idempotency_key"],
        unique=True,
        schema="tournament",
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_index("ix_tournament_computation_job_stage_id", "computation_job", ["stage_id"], schema="tournament")
    op.create_index(
        "ix_tournament_computation_job_stage_item_id",
        "computation_job",
        ["stage_item_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_tournament_computation_job_requested_by_user_id",
        "computation_job",
        ["requested_by_user_id"],
        schema="tournament",
    )
    op.create_table(
        "recalculation_state",
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_generation", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("completed_generation", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tournament_id"),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_table("recalculation_state", schema="tournament")
    op.drop_index(
        "ix_tournament_computation_job_requested_by_user_id", table_name="computation_job", schema="tournament"
    )
    op.drop_index("ix_tournament_computation_job_stage_item_id", table_name="computation_job", schema="tournament")
    op.drop_index("ix_tournament_computation_job_stage_id", table_name="computation_job", schema="tournament")
    op.drop_index("uq_tournament_computation_job_active_key", table_name="computation_job", schema="tournament")
    op.drop_index("ix_tournament_computation_job_tournament_kind", table_name="computation_job", schema="tournament")
    op.drop_index("ix_tournament_computation_job_status", table_name="computation_job", schema="tournament")
    op.drop_table("computation_job", schema="tournament")
