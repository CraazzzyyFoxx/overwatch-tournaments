"""Add the ``progressive`` pool shape to ``tournament.pickbanmode``.

Revision ID: pbprog01_progressive_pool_mode
Revises: flowP8_01_result_role
Create Date: 2026-11-07 00:00:00.000000

One shared map pool played one round per map: round 1 opens before the first
game, every later round after the previous game's result, and maps already
played drop out of the pool. The engine grows rounds the way slot mode does;
only the config needs the new label.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "pbprog01_progressive_pool_mode"
down_revision: str | Sequence[str] | None = "flowP8_01_result_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE tournament.pickbanmode ADD VALUE IF NOT EXISTS 'progressive'")


def downgrade() -> None:
    """PostgreSQL cannot drop an enum label; move any progressive config back to the flat pool instead."""
    op.execute("UPDATE tournament.pick_ban_config SET mode = 'pool' WHERE mode = 'progressive'")
