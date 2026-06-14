"""add_challonge_sync_log

Creates tournament.challonge_sync_log table for bidirectional sync audit trail.

Revision ID: v2q6r0s1t2u3
Revises: u1p5q9r0s1t2
Create Date: 2026-04-10 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "v2q6r0s1t2u3"
down_revision: Union[str, None] = "u1p5q9r0s1t2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "challonge_sync_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("challonge_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        schema="tournament",
    )
    op.create_index(
        "ix_challonge_sync_log_tournament_id",
        "challonge_sync_log",
        ["tournament_id"],
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_index("ix_challonge_sync_log_tournament_id", table_name="challonge_sync_log", schema="tournament")
    op.drop_table("challonge_sync_log", schema="tournament")
