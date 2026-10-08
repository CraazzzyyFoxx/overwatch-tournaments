"""Per-mix voice channels: the general voice and each lobby's two team voices.

Revision ID: mixvoice01
Revises: mixlobby02
Create Date: 2026-10-08 00:00:00.000000

Snowflakes, so BIGINT. Nullable: a mix that never picked voices has none, and
the move refuses that lobby with ``not_configured`` rather than guessing.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mixvoice01"
down_revision: str | Sequence[str] | None = "mixlobby02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "custom_game", sa.Column("general_voice_channel_id", sa.BigInteger(), nullable=True), schema="balancer"
    )
    for column in ("team1_voice_channel_id", "team2_voice_channel_id"):
        op.add_column("custom_game_lobby", sa.Column(column, sa.BigInteger(), nullable=True), schema="balancer")


def downgrade() -> None:
    for column in ("team2_voice_channel_id", "team1_voice_channel_id"):
        op.drop_column("custom_game_lobby", column, schema="balancer")
    op.drop_column("custom_game", "general_voice_channel_id", schema="balancer")
