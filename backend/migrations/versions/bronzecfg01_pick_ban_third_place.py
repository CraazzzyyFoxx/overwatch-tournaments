"""Let the bronze match carry its own pick-ban config.

Revision ID: bronzecfg01_pick_ban_third_place
Revises: bronzematch01_stage_option

The third-place match shares its round with the final, so ``(stage, round)`` could not tell them apart.
``third_place`` joins the level key and makes a bronze config its own round-level scope.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bronzecfg01_pick_ban_third_place"
down_revision: str | Sequence[str] | None = "bronzematch01_stage_option"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "pick_ban_config"
SCHEMA = "tournament"
INDEX = "uq_pick_ban_config_level"
CHECK = "ck_pick_ban_config_third_place_requires_round"


def _level_index(columns: list[str]) -> None:
    op.create_index(INDEX, TABLE, columns, unique=True, schema=SCHEMA, postgresql_nulls_not_distinct=True)


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("third_place", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema=SCHEMA,
    )
    op.create_check_constraint(CHECK, TABLE, "NOT third_place OR round IS NOT NULL", schema=SCHEMA)
    op.drop_index(INDEX, table_name=TABLE, schema=SCHEMA)
    _level_index(["tournament_id", "kind", "stage_id", "round", "third_place"])


def downgrade() -> None:
    """A bronze config shares the final's round level again, so it cannot outlive the narrower key."""
    op.execute(f"DELETE FROM {SCHEMA}.{TABLE} WHERE third_place")
    op.drop_index(INDEX, table_name=TABLE, schema=SCHEMA)
    _level_index(["tournament_id", "kind", "stage_id", "round"])
    op.drop_constraint(CHECK, TABLE, schema=SCHEMA, type_="check")
    op.drop_column(TABLE, "third_place", schema=SCHEMA)
