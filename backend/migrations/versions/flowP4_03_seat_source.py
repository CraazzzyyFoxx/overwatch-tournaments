"""Stage seats record who wrote them; completed stage nodes get the time they completed.

Revision ID: flowP4_03_seat_source
Revises: flowP6_02_drop_is_league
Create Date: 2026-11-07 00:00:00.000000

``stage_item_input.seat_source`` (``flow`` | ``manual``, default ``flow``): requalification re-plans only ``flow`` seats,
so an admin's seeding (``manual``) survives a result change. A seat with a team and no source result row was hand-seeded
before this revision, so it becomes ``manual``.

``flow_node.completed_at`` is the recency an aggregate orders its inputs by. The P2 legacy rebuild and the P6 league
merge left completed stage nodes without it: they get the time of the stage's latest encounter (ended, confirmed,
started, scheduled -- the first one set). A stage with no timed encounter stays NULL (the engine then ranks it last).
Downgrade drops the column and the constraint; the backfilled timestamps stay (a completed node always carries one).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "flowP4_03_seat_source"
down_revision: str | Sequence[str] | None = "flowP6_02_drop_is_league"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_stage_item_input_seat_source"

_BACKFILL_COMPLETED_AT = """
UPDATE tournament.flow_node n SET completed_at = t.ended
FROM (
  SELECT be.stage_id, max(coalesce(e.ended_at, e.confirmed_at, e.started_at, e.scheduled_at)) AS ended
  FROM tournament.bracket_encounter be
  JOIN encounter.encounter e ON e.id = be.encounter_id
  GROUP BY be.stage_id
) t
WHERE n.kind = 'stage' AND n.status = 'completed' AND n.completed_at IS NULL
  AND n.stage_id = t.stage_id AND t.ended IS NOT NULL
"""


def upgrade() -> None:
    op.add_column(
        "stage_item_input",
        sa.Column("seat_source", sa.String(8), nullable=False, server_default="flow"),
        schema="tournament",
    )
    op.create_check_constraint(_CHECK, "stage_item_input", "seat_source IN ('flow', 'manual')", schema="tournament")
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE tournament.stage_item_input SET seat_source = 'manual' "
            "WHERE team_id IS NOT NULL AND source_result_id IS NULL"
        )
    )
    conn.execute(sa.text(_BACKFILL_COMPLETED_AT))


def downgrade() -> None:
    op.drop_constraint(_CHECK, "stage_item_input", schema="tournament", type_="check")
    op.drop_column("stage_item_input", "seat_source", schema="tournament")
