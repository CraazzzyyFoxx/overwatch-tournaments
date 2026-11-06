"""Rebuild every tournament's flow from current data and move the DRAFT/LIVE phase rows onto nodes (spec §14).

Revision ID: flowP3_01
Revises: flowP2_02_legacy_flows
Create Date: 2026-11-05 00:00:00.000000

``flowP2_02`` planned each graph from the data of its deploy day. Since then stages were created without nodes and
statuses moved, so P2's nodes are a stale snapshot. They are deleted (edges, results and schedules cascade) and planned
again by the same code, ``flowP2_02``'s ``backfill``: every legacy status is re-derived from its planned graph before any
row is written, so a tournament the graph cannot reproduce aborts the upgrade with nothing written.

``flowP2_02`` copied only the REGISTRATION and CHECK_IN phase rows. The two that remain become ``start`` rows:
``DRAFT`` on the formation node whose mode is ``draft``, and ``LIVE`` on every stage node of the tournament's first
``order`` (the wave ``_maybe_auto_start_group_stage`` started).

``tournament_phase_schedule`` itself is dropped later (``flowP3_06``). The controller reruns
``tournament-service/recompute_flows.py`` after deploy.
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "flowP3_01"
down_revision: str | Sequence[str] | None = "flowP2_02_legacy_flows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DRAFT_START = """
INSERT INTO tournament.flow_node_schedule (node_id, phase, starts_at, ends_at)
SELECT n.id, 'start', ps.starts_at, ps.ends_at
FROM tournament.tournament_phase_schedule ps
JOIN tournament.flow_node n
  ON n.tournament_id = ps.tournament_id AND n.kind = 'formation' AND n.config->>'mode' = 'draft'
WHERE ps.status = 'draft'{scope}
"""
_LIVE_START = """
INSERT INTO tournament.flow_node_schedule (node_id, phase, starts_at, ends_at)
SELECT n.id, 'start', ps.starts_at, ps.ends_at
FROM tournament.tournament_phase_schedule ps
JOIN tournament.flow_node n ON n.tournament_id = ps.tournament_id AND n.kind = 'stage'
JOIN tournament.stage s ON s.id = n.stage_id
WHERE ps.status = 'live'
  AND s."order" = (SELECT min(s2."order") FROM tournament.stage s2 WHERE s2.tournament_id = ps.tournament_id){scope}
"""


def _load_p2():
    # Loaded by path, the way alembic loads a revision: P2's module has no ``from __future__ import annotations``
    # because its dataclasses cannot resolve string annotations when it is not in ``sys.modules``.
    path = Path(__file__).with_name("flowP2_02_legacy_flows.py")
    spec = importlib.util.spec_from_file_location("flowP2_02_legacy_flows_for_p3", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rebuild(conn: Connection, tournament_ids: Sequence[int] | None = None) -> int:
    """Replace the flow of ``tournament_ids`` (every tournament when None) with a fresh legacy plan."""

    def run(sql: str, column: str) -> None:
        if tournament_ids is None:
            conn.execute(sa.text(sql.format(scope="")))
            return
        stmt = sa.text(sql.format(scope=f" AND {column} IN :ids")).bindparams(sa.bindparam("ids", expanding=True))
        conn.execute(stmt, {"ids": list(tournament_ids)})

    run("DELETE FROM tournament.flow_node WHERE true{scope}", "tournament_id")
    rebuilt = _load_p2().backfill(conn, tournament_ids)
    run(_DRAFT_START, "ps.tournament_id")
    run(_LIVE_START, "ps.tournament_id")
    return rebuilt


def upgrade() -> None:
    rebuild(op.get_bind())


def downgrade() -> None:
    raise NotImplementedError("flowP3_01 rebuilds P2's snapshot; restore from backup")
