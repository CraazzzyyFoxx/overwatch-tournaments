"""player_signal_engine

Revision ID: playersig0001
Revises: anjobmerge001
Create Date: 2026-05-18 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "playersig0001"
down_revision: str | None = "anjobmerge001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in (
        sa.Column("local_mean", sa.Float(), nullable=False, server_default="0"),
        sa.Column("local_std", sa.Float(), nullable=False, server_default="1"),
        sa.Column("local_residual", sa.Float(), nullable=False, server_default="0"),
        sa.Column("local_zscore", sa.Float(), nullable=False, server_default="0"),
        sa.Column("local_percentile", sa.Float(), nullable=False, server_default="50"),
        sa.Column("local_reference_n", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("local_band_min_div", sa.Integer(), nullable=True),
        sa.Column("local_band_max_div", sa.Integer(), nullable=True),
    ):
        op.add_column("performance", column, schema="analytics")

    op.create_table(
        "player_anomaly",
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
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("source_encounter_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["tournament.player.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_encounter_id"],
            ["tournament.encounter.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tournament_id",
            "player_id",
            "kind",
            "source_encounter_id",
            name="uq_analytics_player_anomaly",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_player_anomaly_tournament_id",
        "player_anomaly",
        ["tournament_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_player_anomaly_player_id",
        "player_anomaly",
        ["player_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_player_anomaly_kind",
        "player_anomaly",
        ["kind"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_player_anomaly_source_encounter_id",
        "player_anomaly",
        ["source_encounter_id"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analytics_player_anomaly_source_encounter_id",
        table_name="player_anomaly",
        schema="analytics",
    )
    op.drop_index(
        "ix_analytics_player_anomaly_kind",
        table_name="player_anomaly",
        schema="analytics",
    )
    op.drop_index(
        "ix_analytics_player_anomaly_player_id",
        table_name="player_anomaly",
        schema="analytics",
    )
    op.drop_index(
        "ix_analytics_player_anomaly_tournament_id",
        table_name="player_anomaly",
        schema="analytics",
    )
    op.drop_table("player_anomaly", schema="analytics")

    for column in (
        "local_band_max_div",
        "local_band_min_div",
        "local_reference_n",
        "local_percentile",
        "local_zscore",
        "local_residual",
        "local_std",
        "local_mean",
    ):
        op.drop_column("performance", column, schema="analytics")
