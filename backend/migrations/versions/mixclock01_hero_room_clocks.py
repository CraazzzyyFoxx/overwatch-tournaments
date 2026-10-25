"""Mix hero room clocks: the host's seconds per ban and per pick, and Deadlock's two turn-by-turn pick presets.

Revision ID: mixclock01
Revises: strchron01
Create Date: 2026-10-25 18:00:00.000000

Pure expand: ``mix.custom_game`` gains ``hero_ban_seconds`` and ``hero_pick_seconds`` (NULL = the preset's own clock,
10..600 otherwise), nullable and without a default, so the ADD COLUMN is metadata-only and the CHECKs hold for every
existing row.

The downgrade leaves nothing older code cannot read: it unsets ``deadlock_bans_pick_turns`` and
``deadlock_two_phase_draft`` wherever a mix, a lobby or a host's per-game default names one (the old prefs validator
refuses an unknown preset). A room already open on one stays: its member steps are ``mixpick01``'s.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mixclock01"
down_revision: str | Sequence[str] | None = "strchron01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The presets this revision introduces, as an SQL list.
_NEW_PRESETS = "('deadlock_bans_pick_turns', 'deadlock_two_phase_draft')"


def upgrade() -> None:
    for column in ("hero_ban_seconds", "hero_pick_seconds"):
        op.add_column("custom_game", sa.Column(column, sa.Integer(), nullable=True), schema="mix")
        op.create_check_constraint(
            f"ck_custom_game_{column}", "custom_game", f"{column} BETWEEN 10 AND 600", schema="mix"
        )


def downgrade() -> None:
    op.execute(f"UPDATE mix.custom_game SET hero_ban_preset = NULL WHERE hero_ban_preset IN {_NEW_PRESETS}")
    op.execute(f"UPDATE mix.lobby SET live_ban_preset = NULL WHERE live_ban_preset IN {_NEW_PRESETS}")
    op.execute(
        "UPDATE balancer.user_config SET hero_ban_presets = ("
        "SELECT coalesce(jsonb_object_agg(key, value), '{}'::jsonb) FROM jsonb_each(hero_ban_presets)"
        f" WHERE value #>> '{{}}' NOT IN {_NEW_PRESETS})"
        f" WHERE EXISTS (SELECT 1 FROM jsonb_each_text(hero_ban_presets) WHERE value IN {_NEW_PRESETS})"
    )
    for column in ("hero_pick_seconds", "hero_ban_seconds"):
        op.drop_constraint(f"ck_custom_game_{column}", "custom_game", schema="mix", type_="check")
        op.drop_column("custom_game", column, schema="mix")
