"""drop stored team.avg_sr/total_sr (now computed from roster)

Revision ID: teamsr0001
Revises: draft0005
Create Date: 2026-07-16 00:00:00.000000

``Team.avg_sr``/``Team.total_sr`` are now ``column_property`` aggregates over
``tournament.player.rank`` (non-substitute rows only), so the stored columns
are dropped. ``balancer.team`` keeps its own ``avg_sr``/``total_sr`` — that
table is a historical snapshot of a balance result, not live roster state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "teamsr0001"
down_revision: str | Sequence[str] | None = "draft0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("team", "avg_sr", schema="tournament")
    op.drop_column("team", "total_sr", schema="tournament")


def downgrade() -> None:
    op.add_column("team", sa.Column("avg_sr", sa.Float(), nullable=True), schema="tournament")
    op.add_column("team", sa.Column("total_sr", sa.Integer(), nullable=True), schema="tournament")
    # Backfill from the roster so the NOT NULL constraints of the original
    # schema can be restored. Matches the computed-property semantics.
    op.execute(
        sa.text(
            """
            UPDATE tournament.team t
            SET avg_sr = COALESCE(r.avg_rank, 0),
                total_sr = COALESCE(r.sum_rank, 0)
            FROM (
                SELECT team_id, AVG(rank) AS avg_rank, SUM(rank) AS sum_rank
                FROM tournament.player
                WHERE is_substitution = false
                GROUP BY team_id
            ) r
            WHERE r.team_id = t.id
            """
        )
    )
    op.execute(sa.text("UPDATE tournament.team SET avg_sr = 0, total_sr = 0 WHERE avg_sr IS NULL"))
    op.alter_column("team", "avg_sr", nullable=False, schema="tournament")
    op.alter_column("team", "total_sr", nullable=False, schema="tournament")
