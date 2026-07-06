"""add_analytics_job_unified

Adds:
- ``analytics.algorithms.produces_shifts`` (bool, default true) — flag that
  splits shift-producing algorithms (v1 linear/points, ``OpenSkill + ML``)
  from augmentation pipelines (Performance ML v2,
  Standings MC v2, Match Quality v1) that materialise into dedicated tables.
- ``analytics.job`` table — unified tracker for the new single-pipeline
  "Run analytics" UX. Replaces the ad-hoc Recalculate / Train ML / Run
  inference triggers. Partial unique index on ``workspace_id`` WHERE
  ``status IN ('pending', 'running')`` enforces one running job per
  workspace.

Revision ID: anjob0001
Revises: mergeheads001
Create Date: 2026-05-18 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anjob0001"
down_revision: str | None = "mergeheads001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Names of v2 augmentation algorithms — do NOT produce shifts.
_AUGMENT_ONLY_NAMES = (
    "Performance ML v2",
    "Standings MC v2",
    "Match Quality v1",
)


def upgrade() -> None:
    # 1. analytics.algorithms.produces_shifts
    op.add_column(
        "algorithms",
        sa.Column(
            "produces_shifts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        schema="analytics",
    )
    # Mark v2 augmentation algorithms as non-shift-producing if they already exist.
    bind = op.get_bind()
    for name in _AUGMENT_ONLY_NAMES:
        bind.execute(
            sa.text("UPDATE analytics.algorithms SET produces_shifts = false WHERE name = :name"),
            {"name": name},
        )

    # 2. analytics.job
    op.create_table(
        "job",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("algorithms", sa.JSON(), nullable=True),
        sa.Column(
            "progress",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["auth.user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_job_workspace_id",
        "job",
        ["workspace_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_job_tournament_id",
        "job",
        ["tournament_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_job_requested_by_user_id",
        "job",
        ["requested_by_user_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_job_status",
        "job",
        ["status"],
        schema="analytics",
    )
    # Partial unique — at most one pending/running job per workspace.
    op.create_index(
        "uq_analytics_job_one_running_per_workspace",
        "job",
        ["workspace_id"],
        unique=True,
        schema="analytics",
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_analytics_job_one_running_per_workspace",
        table_name="job",
        schema="analytics",
    )
    op.drop_index("ix_analytics_job_status", table_name="job", schema="analytics")
    op.drop_index("ix_analytics_job_requested_by_user_id", table_name="job", schema="analytics")
    op.drop_index("ix_analytics_job_tournament_id", table_name="job", schema="analytics")
    op.drop_index("ix_analytics_job_workspace_id", table_name="job", schema="analytics")
    op.drop_table("job", schema="analytics")
    op.drop_column("algorithms", "produces_shifts", schema="analytics")
