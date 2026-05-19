"""add_ml_analytics_v2_tables

Adds the storage backing for the v2 ML analytics pipeline:

- ``analytics.ml_features``           — cached feature vectors per granularity
- ``analytics.ml_model_artifact``     — trained model registry
- ``analytics.performance``           — per-(tournament, player) v2 impact score
- ``analytics.standings_distribution``— Monte Carlo standings distribution per team
- ``analytics.match_quality``         — post-hoc encounter quality + anomaly flags
- ``analytics.explanation``           — SHAP-style attribution archive

All tables live in the existing ``analytics`` schema; existing v1 tables
(``algorithms``, ``shifts``, ``predictions``, ``tournament``, etc.) are
untouched. v2 algorithms register alongside v1 in ``analytics.algorithms``
and write into the same ``shifts`` table under new ``algorithm_id`` values.

Revision ID: ml1a2b3c4d5e
Revises: z6u0v4w5x6y7
Create Date: 2026-05-17 21:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ml1a2b3c4d5e"
down_revision: Union[str, None] = "z6u0v4w5x6y7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TIMESTAMP_COLUMNS = (
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    ),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # analytics.ml_features
    # ------------------------------------------------------------------
    op.create_table(
        "ml_features",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        *_TIMESTAMP_COLUMNS,
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("granularity", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("feature_version", sa.String(length=32), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column(
            "log_coverage", sa.Float(), nullable=False, server_default="0"
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tournament_id",
            "granularity",
            "entity_id",
            "feature_version",
            name="uq_analytics_ml_features",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_ml_features_tournament_id",
        "ml_features",
        ["tournament_id"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_ml_features_granularity",
        "ml_features",
        ["granularity"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_ml_features_entity_id",
        "ml_features",
        ["entity_id"],
        unique=False,
        schema="analytics",
    )

    # ------------------------------------------------------------------
    # analytics.ml_model_artifact
    # ------------------------------------------------------------------
    op.create_table(
        "ml_model_artifact",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        *_TIMESTAMP_COLUMNS,
        sa.Column("algorithm_id", sa.Integer(), nullable=False),
        sa.Column("model_kind", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("feature_version", sa.String(length=32), nullable=False),
        sa.Column("training_cutoff_tournament_id", sa.Integer(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("feature_importance", sa.JSON(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.ForeignKeyConstraint(
            ["algorithm_id"], ["analytics.algorithms.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["training_cutoff_tournament_id"],
            ["tournament.tournament.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "algorithm_id",
            "model_kind",
            "role",
            "version",
            name="uq_analytics_ml_model_artifact",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_ml_model_artifact_algorithm_id",
        "ml_model_artifact",
        ["algorithm_id"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_ml_model_artifact_model_kind",
        "ml_model_artifact",
        ["model_kind"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_ml_model_artifact_is_active",
        "ml_model_artifact",
        ["is_active"],
        unique=False,
        schema="analytics",
    )

    # ------------------------------------------------------------------
    # analytics.performance
    # ------------------------------------------------------------------
    op.create_table(
        "performance",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        *_TIMESTAMP_COLUMNS,
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("algorithm_id", sa.Integer(), nullable=False),
        sa.Column("impact_score", sa.Float(), nullable=False),
        sa.Column("raw_value", sa.Float(), nullable=False),
        sa.Column(
            "confidence", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "log_coverage", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("top_features", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["tournament.player.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["algorithm_id"], ["analytics.algorithms.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tournament_id",
            "player_id",
            "algorithm_id",
            name="uq_analytics_performance",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_performance_tournament_id",
        "performance",
        ["tournament_id"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_performance_player_id",
        "performance",
        ["player_id"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_performance_algorithm_id",
        "performance",
        ["algorithm_id"],
        unique=False,
        schema="analytics",
    )

    # ------------------------------------------------------------------
    # analytics.standings_distribution
    # ------------------------------------------------------------------
    op.create_table(
        "standings_distribution",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        *_TIMESTAMP_COLUMNS,
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("algorithm_id", sa.Integer(), nullable=False),
        sa.Column("mean_position", sa.Float(), nullable=False),
        sa.Column("median_position", sa.Float(), nullable=False),
        sa.Column("p10_position", sa.Float(), nullable=False),
        sa.Column("p90_position", sa.Float(), nullable=False),
        sa.Column(
            "prob_top1", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "prob_top3", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "prob_top8", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("position_histogram", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["tournament.team.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["algorithm_id"], ["analytics.algorithms.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tournament_id",
            "team_id",
            "algorithm_id",
            name="uq_analytics_standings_distribution",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_standings_distribution_tournament_id",
        "standings_distribution",
        ["tournament_id"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_standings_distribution_team_id",
        "standings_distribution",
        ["team_id"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_standings_distribution_algorithm_id",
        "standings_distribution",
        ["algorithm_id"],
        unique=False,
        schema="analytics",
    )

    # ------------------------------------------------------------------
    # analytics.match_quality
    # ------------------------------------------------------------------
    op.create_table(
        "match_quality",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        *_TIMESTAMP_COLUMNS,
        sa.Column("encounter_id", sa.Integer(), nullable=False),
        sa.Column("algorithm_id", sa.Integer(), nullable=False),
        sa.Column("competitiveness", sa.Float(), nullable=False),
        sa.Column("predictability", sa.Float(), nullable=False),
        sa.Column("skill_balance", sa.Float(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("anomaly_flags", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["encounter_id"], ["tournament.encounter.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["algorithm_id"], ["analytics.algorithms.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "encounter_id",
            "algorithm_id",
            name="uq_analytics_match_quality",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_match_quality_encounter_id",
        "match_quality",
        ["encounter_id"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_match_quality_algorithm_id",
        "match_quality",
        ["algorithm_id"],
        unique=False,
        schema="analytics",
    )

    # ------------------------------------------------------------------
    # analytics.explanation
    # ------------------------------------------------------------------
    op.create_table(
        "explanation",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        *_TIMESTAMP_COLUMNS,
        sa.Column("algorithm_id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("entity_kind", sa.String(length=16), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("base_value", sa.Float(), nullable=False),
        sa.Column("contributions", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["algorithm_id"], ["analytics.algorithms.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_explanation_algorithm_id",
        "explanation",
        ["algorithm_id"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_explanation_entity_id",
        "explanation",
        ["entity_id"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_explanation_entity_kind",
        "explanation",
        ["entity_kind"],
        unique=False,
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_explanation_tournament_id",
        "explanation",
        ["tournament_id"],
        unique=False,
        schema="analytics",
    )


def downgrade() -> None:
    for table in (
        "explanation",
        "match_quality",
        "standings_distribution",
        "performance",
        "ml_model_artifact",
        "ml_features",
    ):
        op.drop_table(table, schema="analytics")
