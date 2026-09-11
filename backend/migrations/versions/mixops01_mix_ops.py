"""Add ``casual.match.points_per_win_applied`` and ``balancer.custom_game.discord_channel_id``.

Revision ID: mixops01
Revises: nextmap01
Create Date: 2026-09-11 00:00:00.000000

``points_per_win_applied`` freezes how far a recorded match actually moved both
teams' ranks, so undoing it rolls back that exact amount rather than whatever
``points_per_win`` happens to say later. NULL for a draw, for a match recorded
while the knob was off, and for every row written before this column existed.

``discord_channel_id`` is where a mix announces itself; storage only for now,
no API reads or writes it yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mixops01"
down_revision: str | Sequence[str] | None = "nextmap01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("match", sa.Column("points_per_win_applied", sa.Integer(), nullable=True), schema="casual")
    op.add_column("custom_game", sa.Column("discord_channel_id", sa.BigInteger(), nullable=True), schema="balancer")


def downgrade() -> None:
    op.drop_column("custom_game", "discord_channel_id", schema="balancer")
    op.drop_column("match", "points_per_win_applied", schema="casual")
