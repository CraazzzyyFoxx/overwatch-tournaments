"""Mix hero room pickers: a free pick order and captains-only picks.

Revision ID: mixpickers01
Revises: mixcode01
Create Date: 2026-10-26 12:00:00.000000

Pure expand: ``mix.custom_game`` gains ``hero_free_order`` and ``hero_captains_only``, NOT NULL with a constant
``false`` default, so the ADD COLUMN is metadata-only and every existing mix keeps picking as it did.

The downgrade drops the rooms older code cannot read -- a snapshotted ruleset with a free-order step (``member: any``)
or a captains-only one -- as ``mixpick01``'s does for member steps, then the columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mixpickers01"
down_revision: str | Sequence[str] | None = "mixcode01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("hero_free_order", "hero_captains_only")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column(
            "custom_game",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()),
            schema="mix",
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM encounter.pick_ban_session WHERE jsonb_path_exists("
        "ruleset_json::jsonb, '$.phases[*].steps[*] ? (@.member == \"any\" || @.captains_only == true)')"
    )
    for column in reversed(_COLUMNS):
        op.drop_column("custom_game", column, schema="mix")
