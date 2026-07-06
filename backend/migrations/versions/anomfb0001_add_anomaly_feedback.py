"""add analytics.anomaly_feedback

Reviewer verdicts (confirmed / dismissed) on player anomalies — the labels that
let detector thresholds be tuned by precision/recall instead of magic numbers.

Revision ID: anomfb0001
Revises: purge0001
Create Date: 2026-06-14 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anomfb0001"
down_revision: str | None = "purge0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "anomaly_feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["tournament.player.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["auth.user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tournament_id",
            "player_id",
            "kind",
            name="uq_analytics_anomaly_feedback",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_anomaly_feedback_tournament_id",
        "anomaly_feedback",
        ["tournament_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_anomaly_feedback_player_id",
        "anomaly_feedback",
        ["player_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_anomaly_feedback_kind",
        "anomaly_feedback",
        ["kind"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_anomaly_feedback_reviewer_user_id",
        "anomaly_feedback",
        ["reviewer_user_id"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analytics_anomaly_feedback_reviewer_user_id",
        table_name="anomaly_feedback",
        schema="analytics",
    )
    op.drop_index(
        "ix_analytics_anomaly_feedback_kind",
        table_name="anomaly_feedback",
        schema="analytics",
    )
    op.drop_index(
        "ix_analytics_anomaly_feedback_player_id",
        table_name="anomaly_feedback",
        schema="analytics",
    )
    op.drop_index(
        "ix_analytics_anomaly_feedback_tournament_id",
        table_name="anomaly_feedback",
        schema="analytics",
    )
    op.drop_table("anomaly_feedback", schema="analytics")
