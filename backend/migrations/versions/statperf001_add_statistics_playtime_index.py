"""add matches.statistics playtime partial index

Speeds up the global "hero stats across all players" query
(`get_statistics_by_heroes_all_values`). That query filters the eligible stat
rows to (match, user, hero) combos that actually played the hero
(HeroTimePlayed > 60). With no index leading on `match_id` the planner had to
re-probe matches.statistics per candidate row, which pushed the uncached
request past the 30s statement_timeout.

This partial index covers exactly the playtime lookup / semi-join key.

Created CONCURRENTLY (via autocommit_block) so building it does not lock writes
on the large statistics table in production.

Revision ID: statperf001
Revises: anomfb0001
Create Date: 2026-06-20 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "statperf001"
down_revision: str | None = "anomfb0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_match_statistics_playtime_r0",
            "statistics",
            ["match_id", "user_id", "hero_id"],
            schema="matches",
            unique=False,
            # Enum(LogStatsName) persists the member NAME (HeroTimePlayed), not
            # its .value (hero_time_played) — this raw predicate bypasses the
            # type, so it must use the stored label.
            postgresql_where=sa.text("round = 0 AND name = 'HeroTimePlayed'"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_match_statistics_playtime_r0",
            table_name="statistics",
            schema="matches",
            postgresql_concurrently=True,
            if_exists=True,
        )
