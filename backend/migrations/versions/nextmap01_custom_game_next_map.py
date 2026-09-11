"""Add ``next_map_id`` to ``balancer.custom_game``.

Revision ID: nextmap01
Revises: regteam0004
Create Date: 2026-09-11 00:00:00.000000

The map the mix's *next* match is played on -- rolled or picked by the host
before the lobby loads in, shown to every viewer, and consumed by
``record_outcome`` as the recorded match's map. Nullable: a mix with nothing
rolled yet records matches exactly as before. ``ON DELETE SET NULL`` because a
catalogue map disappearing must not take a live mix down with it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "nextmap01"
down_revision: str | Sequence[str] | None = "regteam0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "custom_game",
        sa.Column(
            "next_map_id",
            sa.Integer(),
            sa.ForeignKey("overwatch.map.id", ondelete="SET NULL", name="fk_custom_game_next_map"),
            nullable=True,
        ),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("custom_game", "next_map_id", schema="balancer")
