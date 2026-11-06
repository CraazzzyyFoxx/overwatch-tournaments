"""The flow decides how teams form: ``tournament.team_formation`` and ``tournament.draft_format_json`` go.

Revision ID: flowP7_01_drop_team_formation
Revises: flowP4_03_seat_source
Create Date: 2026-11-08 00:00:00.000000

Authority moves to the flow graph: the formation node's ``config.mode`` (``balancer | draft | registered | manual``)
says how teams form, the registration node's ``config.intake`` (``solo | team``) how players enter, and the draft
format becomes ``config.draft_format`` of the draft formation node.

Upgrade copies ``draft_format_json`` into the config of each draft-mode formation node of the tournament. A tournament
with a format but no draft node (it was not drafting, or its flow changed since) keeps it on its first formation node
-- it is inert there until the mode becomes ``draft`` -- and the move is logged; with no formation node at all the
format is dropped (and logged). Then both columns are dropped.

Downgrade re-adds the columns and rebuilds them from the nodes: ``team_formation`` from the first formation node's
mode (``registered`` or a registration node with ``intake = team`` -> ``registration``, ``manual`` -> ``solo``),
``draft_format_json`` from its first draft node; the ``draft_format`` key is stripped from every node config so the
previous release's strict config validation accepts them.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "flowP7_01_drop_team_formation"
down_revision: str | Sequence[str] | None = "flowP4_03_seat_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_log = logging.getLogger("alembic.runtime.migration")

_COPY_TO_DRAFT_NODES = """
UPDATE tournament.flow_node n
SET config = n.config || jsonb_build_object('draft_format', t.draft_format_json)
FROM tournament.tournament t
WHERE t.draft_format_json IS NOT NULL
  AND n.tournament_id = t.id AND n.kind = 'formation' AND n.config->>'mode' = 'draft'
"""

_COPY_TO_NODE = """
UPDATE tournament.flow_node n
SET config = n.config || jsonb_build_object('draft_format', t.draft_format_json)
FROM tournament.tournament t
WHERE n.id = :node AND t.id = :tournament
"""

# Tournaments with a format and no draft formation node: their first formation node (NULL when there is none).
_HOMELESS = """
SELECT t.id, (SELECT min(n.id) FROM tournament.flow_node n WHERE n.tournament_id = t.id AND n.kind = 'formation')
FROM tournament.tournament t
WHERE t.draft_format_json IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM tournament.flow_node n
    WHERE n.tournament_id = t.id AND n.kind = 'formation' AND n.config->>'mode' = 'draft'
  )
"""

_RESTORE_TEAM_FORMATION = """
UPDATE tournament.tournament t
SET team_formation = CASE
    WHEN f.mode = 'registered' OR r.intake = 'team' THEN 'registration'
    WHEN f.mode = 'draft' THEN 'draft'
    WHEN f.mode = 'manual' THEN 'solo'
    ELSE 'balancer'
END
FROM (
  SELECT DISTINCT ON (tournament_id) tournament_id, config->>'mode' AS mode
  FROM tournament.flow_node WHERE kind = 'formation' ORDER BY tournament_id, id
) f
LEFT JOIN (
  SELECT DISTINCT ON (tournament_id) tournament_id, config->>'intake' AS intake
  FROM tournament.flow_node WHERE kind = 'registration' ORDER BY tournament_id, id
) r ON r.tournament_id = f.tournament_id
WHERE f.tournament_id = t.id
"""

_RESTORE_DRAFT_FORMAT = """
UPDATE tournament.tournament t
SET draft_format_json = d.fmt
FROM (
  SELECT DISTINCT ON (tournament_id) tournament_id, config->'draft_format' AS fmt
  FROM tournament.flow_node
  WHERE kind = 'formation' AND config->>'mode' = 'draft' AND config->'draft_format' IS NOT NULL
  ORDER BY tournament_id, id
) d
WHERE d.tournament_id = t.id AND jsonb_typeof(d.fmt) = 'object'
"""


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(_COPY_TO_DRAFT_NODES))
    for tournament_id, node_id in conn.execute(sa.text(_HOMELESS)).all():
        if node_id is None:
            _log.warning("tournament %s: draft_format_json dropped, it has no formation node", tournament_id)
            continue
        conn.execute(sa.text(_COPY_TO_NODE), {"node": node_id, "tournament": tournament_id})
        _log.warning(
            "tournament %s: no draft formation node, draft_format_json kept on its first formation node %s",
            tournament_id,
            node_id,
        )
    op.drop_column("tournament", "draft_format_json", schema="tournament")
    op.drop_column("tournament", "team_formation", schema="tournament")


def downgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column("team_formation", sa.String(), server_default="balancer", nullable=False),
        schema="tournament",
    )
    op.add_column(
        "tournament",
        sa.Column("draft_format_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="tournament",
    )
    conn = op.get_bind()
    conn.execute(sa.text(_RESTORE_TEAM_FORMATION))
    conn.execute(sa.text(_RESTORE_DRAFT_FORMAT))
    conn.execute(
        sa.text(
            "UPDATE tournament.flow_node SET config = config - 'draft_format' "
            "WHERE kind = 'formation' AND config ? 'draft_format'"
        )
    )
