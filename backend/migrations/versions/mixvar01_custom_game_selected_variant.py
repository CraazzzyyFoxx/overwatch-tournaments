"""Add ``selected_variant_index`` to ``balancer.custom_game``.

Revision ID: mixvar01
Revises: mixops01
Create Date: 2026-09-13 00:00:00.000000

Which of the stored balance options the mix is *showing*. The pager used to be
browser state, so every viewer read a different matchup than the host was
calling out; it is a fact about the mix, like ``next_map_id``, and lives with
it. ``0`` for every existing mix -- the option every client already opened on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mixvar01"
down_revision: str | Sequence[str] | None = "mixops01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "custom_game",
        sa.Column("selected_variant_index", sa.Integer(), nullable=False, server_default="0"),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("custom_game", "selected_variant_index", schema="balancer")
