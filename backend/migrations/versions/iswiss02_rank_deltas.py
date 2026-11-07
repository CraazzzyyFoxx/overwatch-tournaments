"""Individual Swiss moves a player's rank by the stage's results.

``tournament.stage`` gains ``rank_win_delta`` / ``rank_loss_delta`` (``individual_swiss`` only, NULL elsewhere):
the rank a player gains per won and loses per lost encounter. Existing individual Swiss stages get 0 / 0, so
nothing they already computed moves.

``tournament.player_standing`` gains ``start_rank``, the rank frozen when the stage started; ``rank`` becomes the
current one derived from it. Every existing row is still at its frozen value, so ``start_rank`` is copied from it.

Downgrade drops the columns; ``rank`` is put back to the frozen value it meant before.

Revision ID: iswiss02_rank_deltas
Revises: flowP7_01_drop_team_formation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with ``^revision:\s*str\s*=``.
revision: str = "iswiss02_rank_deltas"
down_revision: str | Sequence[str] | None = "flowP7_01_drop_team_formation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("rank_win_delta", "rank_loss_delta"):
        op.add_column("stage", sa.Column(column, sa.Integer(), nullable=True), schema="tournament")
        op.create_check_constraint(
            f"ck_stage_{column}", "stage", f"{column} IS NULL OR {column} >= 0", schema="tournament"
        )
    op.execute(
        "UPDATE tournament.stage SET rank_win_delta = 0, rank_loss_delta = 0 WHERE stage_type = 'individual_swiss'"
    )

    op.add_column("player_standing", sa.Column("start_rank", sa.Integer(), nullable=True), schema="tournament")
    op.execute("UPDATE tournament.player_standing SET start_rank = rank")
    op.alter_column("player_standing", "start_rank", nullable=False, schema="tournament")


def downgrade() -> None:
    op.execute("UPDATE tournament.player_standing SET rank = start_rank")
    op.drop_column("player_standing", "start_rank", schema="tournament")
    for column in ("rank_loss_delta", "rank_win_delta"):
        op.drop_constraint(f"ck_stage_{column}", "stage", schema="tournament")
        op.drop_column("stage", column, schema="tournament")
