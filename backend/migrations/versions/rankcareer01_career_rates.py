"""Game-account profiles, career snapshots and the game's own character rates in the ``rank`` schema.

Revision ID: rankcareer01_career_rates
Revises: regnote01_registration_notes
Create Date: 2026-11-16 00:00:00.000000

The Overwatch collector already reads each BattleTag's OverFast summary every poll for its ranks; it now reads the
whole profile, which costs Blizzard the same page. ``rank.account_profile`` keeps the account's current name, avatar,
attributes and its rename-proof upstream id; ``rank.career_snapshot`` keeps the cumulative career statistics per
character as a series of changes (a row only when the poll differs); ``rank.character_rate`` keeps the game's daily
pick, win and ban rates per slice of its ladder. New tables only: nothing is backfilled, history starts at the first
poll after the deploy.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "rankcareer01_career_rates"
down_revision: str | Sequence[str] | None = "regnote01_registration_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "rank"


def upgrade() -> None:
    op.create_table(
        "account_profile",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discipline", sa.String(length=32), nullable=False),
        sa.Column(
            "social_account_id",
            sa.BigInteger(),
            sa.ForeignKey("players.social_account.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("attrs", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("canonical_id", sa.String(length=255), nullable=True),
        sa.Column("canonical_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upstream_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )

    op.create_table(
        "career_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("discipline", sa.String(length=32), nullable=False),
        sa.Column(
            "social_account_id",
            sa.BigInteger(),
            sa.ForeignKey("players.social_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(length=16), nullable=True),
        sa.Column("queue", sa.String(length=16), nullable=True),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("character", sa.String(length=64), nullable=False),
        sa.Column("stats", JSONB(), nullable=False),
        sa.Column("digest", sa.String(length=32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_career_snapshot_series_captured",
        "career_snapshot",
        ["social_account_id", "platform", "queue", "character", sa.literal_column("captured_at DESC")],
        schema=SCHEMA,
    )

    op.create_table(
        "character_rate",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("discipline", sa.String(length=32), nullable=False),
        sa.Column("captured_on", sa.Date(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=True),
        sa.Column("queue", sa.String(length=16), nullable=True),
        sa.Column("region", sa.String(length=16), nullable=True),
        sa.Column("division", sa.String(length=32), nullable=True),
        sa.Column("map", sa.String(length=64), nullable=True),
        sa.Column("character", sa.String(length=64), nullable=False),
        sa.Column("pickrate", sa.Float(), nullable=True),
        sa.Column("winrate", sa.Float(), nullable=True),
        sa.Column("banrate", sa.Float(), nullable=True),
        sa.UniqueConstraint(
            "discipline",
            "captured_on",
            "platform",
            "queue",
            "region",
            "division",
            "map",
            "character",
            name="uq_character_rate_slice",
            postgresql_nulls_not_distinct=True,
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("character_rate", schema=SCHEMA)
    op.drop_table("career_snapshot", schema=SCHEMA)
    op.drop_table("account_profile", schema=SCHEMA)
