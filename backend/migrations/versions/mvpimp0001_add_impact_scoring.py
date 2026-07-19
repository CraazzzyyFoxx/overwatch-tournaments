"""add impact scoring: new logstatsname values + stat_baselines table

Revision ID: mvpimp0001
Revises: wsbrand0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "mvpimp0001"
down_revision = "wsbrand0002"
branch_labels = None
depends_on = None

_NEW_STAT_VALUES = (
    "FirstPicks",
    "FirstDeaths",
    "UltimateKills",
    "SupportKills",
    "ImpactPoints",
    "ImpactRank",
    "OverperformanceScore",
)


def upgrade() -> None:
    # PG12+: ADD VALUE is allowed inside a transaction as long as the new
    # value is not used in the same transaction (we don't use it here).
    for value in _NEW_STAT_VALUES:
        op.execute(f"ALTER TYPE logstatsname ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        "stat_baselines",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("formula_version", sa.String(length=64), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(name="heroclass", create_type=False),
            nullable=False,
        ),
        sa.Column("rank_bucket", sa.SmallInteger(), server_default="-1", nullable=False),
        sa.Column(
            "stat",
            postgresql.ENUM(name="logstatsname", create_type=False),
            nullable=False,
        ),
        sa.Column("mean", sa.Float(), nullable=False),
        sa.Column("std", sa.Float(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("formula_version", "role", "rank_bucket", "stat", name="uq_stat_baselines_key"),
        schema="matches",
    )
    op.create_index("ix_stat_baselines_version", "stat_baselines", ["formula_version"], schema="matches")


def downgrade() -> None:
    op.drop_index("ix_stat_baselines_version", table_name="stat_baselines", schema="matches")
    op.drop_table("stat_baselines", schema="matches")
    # Enum values are intentionally NOT removed (PG can't drop enum values).
