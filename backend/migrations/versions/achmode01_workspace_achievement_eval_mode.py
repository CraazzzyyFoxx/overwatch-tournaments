"""Add workspace.achievement_eval_mode: when data changes re-run achievements on their own.

Revision ID: achmode01
Revises: bronzecfg01_pick_ban_third_place

``live`` (default, today's behavior), ``stage_end`` or ``manual``; see ``shared.models.achievements.AchievementEvalMode``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "achmode01"
down_revision: str | Sequence[str] | None = "bronzecfg01_pick_ban_third_place"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace",
        sa.Column("achievement_eval_mode", sa.String(16), nullable=False, server_default="live"),
    )


def downgrade() -> None:
    op.drop_column("workspace", "achievement_eval_mode")
