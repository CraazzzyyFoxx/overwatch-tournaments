"""Stage seats name the flow result row they came from; wiring columns and tentative inputs go.

Revision ID: flowP4_01_source_result
Revises: flowP3_06
Create Date: 2026-11-06 00:00:00.000000

``stage_item_input.source_result_id`` (FK ``flow_node_result``, ``SET NULL``) replaces ``source_stage_item_id`` /
``source_position``. Every input with a team is backfilled with the row of the node that feeds its stage (the edge into
the stage's ``participants`` port) holding that team; a FINAL input that carried a wiring source and finds no row aborts
the upgrade and lists the input ids, so ``recompute_flows.py`` must have filled the results first (P2/P3 contract).
The double-elimination split the wiring read from ``advance_upper_count`` is copied into the legacy filters
(``upper`` / ``per_item_upper``) before Task 7 drops those columns. TENTATIVE inputs become EMPTY (``team_id`` NULL) and
the enum is recreated without the value; ``ck_stage_seed_ranking`` accepts ``source``, ``cross`` and ``snake``.
Downgrade restores the schema only: columns come back NULL, the wired data, the filter ``upper`` copy and the TENTATIVE
rows are not restored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "flowP4_01_source_result"
down_revision: str | Sequence[str] | None = "flowP3_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RANKINGS_OLD = "'slot', 'avg_sr', 'total_sr', 'random'"
_RANKINGS_NEW = "'slot', 'source', 'avg_sr', 'total_sr', 'random', 'cross', 'snake'"
_INDEX = "ix_tournament_stage_item_input_source_result_id"

_BACKFILL = """
UPDATE tournament.stage_item_input sii SET source_result_id = r.id
FROM tournament.stage_item si
JOIN tournament.flow_node tn ON tn.stage_id = si.stage_id
JOIN tournament.flow_edge e ON e.target_node_id = tn.id AND e.target_port = 'participants'
JOIN tournament.flow_node_result r ON r.node_id = e.source_node_id AND r.port = e.source_port
WHERE si.id = sii.stage_item_id AND sii.team_id IS NOT NULL AND r.team_id = sii.team_id
"""
_UNMATCHED = """
SELECT id FROM tournament.stage_item_input
WHERE source_stage_item_id IS NOT NULL AND input_type = 'final' AND source_result_id IS NULL
ORDER BY id
"""
# Source stages' advance_upper_count -> the filter that reads them; a per-item value wins in ``per_item_upper``.
_FILTER_UPPER = """
UPDATE tournament.flow_node f SET config = f.config || jsonb_build_object('upper', st.advance_upper_count)
FROM tournament.flow_edge e
JOIN tournament.flow_node sn ON sn.id = e.source_node_id AND sn.kind = 'stage'
JOIN tournament.stage st ON st.id = sn.stage_id
WHERE f.kind = 'filter' AND f.config ->> 'mode' IN ('per_item_top', 'top') AND e.target_node_id = f.id
  AND st.advance_upper_count IS NOT NULL
"""
_FILTER_PER_ITEM_UPPER = """
UPDATE tournament.flow_node f SET config = f.config || jsonb_build_object('per_item_upper', u.per_item)
FROM (
  SELECT e.target_node_id AS node_id, jsonb_object_agg(si.id::text, si.advance_upper_count) AS per_item
  FROM tournament.flow_edge e
  JOIN tournament.flow_node sn ON sn.id = e.source_node_id AND sn.kind = 'stage'
  JOIN tournament.stage_item si ON si.stage_id = sn.stage_id
  WHERE si.advance_upper_count IS NOT NULL
  GROUP BY e.target_node_id
) u
WHERE f.id = u.node_id AND f.kind = 'filter' AND f.config ->> 'mode' IN ('per_item_top', 'top')
"""


def _recreate_input_type(values: str) -> None:
    op.execute("ALTER TYPE tournament.stageiteminputtype RENAME TO stageiteminputtype_old")
    op.execute(f"CREATE TYPE tournament.stageiteminputtype AS ENUM ({values})")
    op.execute(
        "ALTER TABLE tournament.stage_item_input ALTER COLUMN input_type DROP DEFAULT, "
        "ALTER COLUMN input_type TYPE tournament.stageiteminputtype "
        "USING input_type::text::tournament.stageiteminputtype"
    )
    op.execute("DROP TYPE tournament.stageiteminputtype_old")


def _seed_ranking_check(values: str) -> None:
    op.drop_constraint("ck_stage_seed_ranking", "stage", schema="tournament", type_="check")
    op.create_check_constraint("ck_stage_seed_ranking", "stage", f"seed_ranking IN ({values})", schema="tournament")


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column(
        "stage_item_input",
        sa.Column("source_result_id", sa.BigInteger(), nullable=True),
        schema="tournament",
    )
    op.create_foreign_key(
        "stage_item_input_source_result_id_fkey",
        "stage_item_input",
        "flow_node_result",
        ["source_result_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="tournament",
        ondelete="SET NULL",
    )
    op.create_index(_INDEX, "stage_item_input", ["source_result_id"], schema="tournament")

    conn.execute(sa.text(_BACKFILL))
    unmatched = conn.execute(sa.text(_UNMATCHED)).scalars().all()
    if unmatched:
        raise RuntimeError(
            f"stage_item_input {list(unmatched)} were wired from a group but no flow result row holds their team; "
            "run tournament-service/recompute_flows.py on the previous revision first"
        )

    conn.execute(sa.text(_FILTER_UPPER))
    conn.execute(sa.text(_FILTER_PER_ITEM_UPPER))

    conn.execute(
        sa.text(
            "UPDATE tournament.stage_item_input SET input_type = 'empty', team_id = NULL WHERE input_type = 'tentative'"
        )
    )
    _recreate_input_type("'final', 'empty'")
    op.drop_column("stage_item_input", "source_stage_item_id", schema="tournament")
    op.drop_column("stage_item_input", "source_position", schema="tournament")
    _seed_ranking_check(_RANKINGS_NEW)


def downgrade() -> None:
    conn = op.get_bind()
    # Seed rankings only the new check accepts fall back to the input order the old ones know.
    conn.execute(
        sa.text("UPDATE tournament.stage SET seed_ranking = 'slot' WHERE seed_ranking IN ('source', 'cross', 'snake')")
    )
    _seed_ranking_check(_RANKINGS_OLD)
    op.add_column("stage_item_input", sa.Column("source_position", sa.Integer(), nullable=True), schema="tournament")
    op.add_column(
        "stage_item_input",
        sa.Column("source_stage_item_id", sa.BigInteger(), nullable=True),
        schema="tournament",
    )
    op.create_foreign_key(
        "stage_item_input_source_stage_item_id_fkey",
        "stage_item_input",
        "stage_item",
        ["source_stage_item_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="tournament",
        ondelete="SET NULL",
    )
    _recreate_input_type("'final', 'tentative', 'empty'")
    op.drop_index(_INDEX, "stage_item_input", schema="tournament")
    op.drop_column("stage_item_input", "source_result_id", schema="tournament")
