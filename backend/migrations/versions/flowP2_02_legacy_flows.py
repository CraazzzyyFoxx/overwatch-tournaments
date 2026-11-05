"""Build the flow graph of every existing tournament (spec §14).

Revision ID: flowP2_02_legacy_flows
Revises: flowP2_01_flow_tables

The graph is planned by the pure ``shared.domain.flow.legacy`` planner (the same way ``wsplyr02`` uses its shared
planner). Every tournament is planned and its legacy status re-derived from the planned graph BEFORE any row is
written, so a tournament whose status the graph cannot reproduce aborts the whole upgrade with nothing written.
Tournaments that already own a flow node are skipped: re-running is a no-op. Downgrade deletes every flow node
(edges, results and schedules cascade).
"""

import json
from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

from shared.domain.flow.legacy import (
    LEGACY_STATUS_TARGET,
    LegacyFlowPlan,
    LegacySchedule,
    LegacySourceRef,
    LegacyStage,
    LegacyStageItem,
    LegacyStatusMismatch,
    LegacyTournament,
    assert_status_reproduced,
    plan_legacy_flow,
)

revision: str = "flowP2_02_legacy_flows"
down_revision: str | Sequence[str] | None = "flowP2_01_flow_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TOURNAMENTS = """
SELECT t.id, t.status::text AS status, t.team_formation,
       EXISTS (SELECT 1 FROM tournament.team tm WHERE tm.tournament_id = t.id) AS has_teams,
       (EXISTS (SELECT 1 FROM tournament.tournament_phase_schedule ps
                WHERE ps.tournament_id = t.id AND ps.status = 'check_in')
        OR t.status = 'check_in'
        OR EXISTS (SELECT 1 FROM registration.registration r
                   WHERE r.tournament_id = t.id AND r.checked_in AND r.deleted_at IS NULL)) AS check_in_used
FROM tournament.tournament t
WHERE NOT EXISTS (SELECT 1 FROM tournament.flow_node n WHERE n.tournament_id = t.id){scope}
ORDER BY t.id
"""
_STAGES = """
SELECT s.tournament_id, s.id, s.name, s.stage_type::text AS stage_type, s."order", s.is_active, s.is_published,
       s.is_completed, s.advance_count, s.qualification_locked_at IS NOT NULL AS qualification_locked,
       (SELECT count(*) FROM tournament.player_standing ps WHERE ps.stage_id = s.id AND ps.is_qualified)
           AS qualified_count
FROM tournament.stage s
WHERE true{scope}
ORDER BY s.tournament_id, s."order", s.id
"""
_ITEMS = """
SELECT si.stage_id, si.id, si."order", si.advance_count
FROM tournament.stage_item si
JOIN tournament.stage s ON s.id = si.stage_id
WHERE true{scope}
ORDER BY si.stage_id, si."order", si.id
"""
_REFS = """
SELECT DISTINCT s.tournament_id, si.stage_id AS target_stage_id, sii.source_stage_item_id, sii.source_position
FROM tournament.stage_item_input sii
JOIN tournament.stage_item si ON si.id = sii.stage_item_id
JOIN tournament.stage s ON s.id = si.stage_id
WHERE sii.source_stage_item_id IS NOT NULL AND sii.source_position IS NOT NULL{scope}
"""
_SCHEDULES = """
SELECT ps.tournament_id, ps.status::text AS status, ps.starts_at, ps.ends_at
FROM tournament.tournament_phase_schedule ps
JOIN tournament.tournament t ON t.id = ps.tournament_id
WHERE ps.status IN ('registration', 'check_in'){scope}
ORDER BY ps.tournament_id, ps.starts_at
"""


def _rows(conn: Connection, sql: str, scope_column: str, ids: Sequence[int] | None):
    if ids is None:
        return conn.execute(sa.text(sql.format(scope=""))).all()
    stmt = sa.text(sql.format(scope=f" AND {scope_column} IN :ids")).bindparams(sa.bindparam("ids", expanding=True))
    return conn.execute(stmt, {"ids": list(ids)}).all()


def load_legacy_tournaments(conn: Connection, tournament_ids: Sequence[int] | None = None) -> list[LegacyTournament]:
    if tournament_ids is not None and not tournament_ids:
        return []
    items: dict[int, list[LegacyStageItem]] = defaultdict(list)
    for r in _rows(conn, _ITEMS, "s.tournament_id", tournament_ids):
        items[r.stage_id].append(LegacyStageItem(id=r.id, order=r.order, advance_count=r.advance_count))
    stages: dict[int, list[LegacyStage]] = defaultdict(list)
    for r in _rows(conn, _STAGES, "s.tournament_id", tournament_ids):
        stages[r.tournament_id].append(
            LegacyStage(
                id=r.id,
                name=r.name,
                stage_type=r.stage_type,
                order=r.order,
                is_active=r.is_active,
                is_published=r.is_published,
                is_completed=r.is_completed,
                advance_count=r.advance_count,
                qualification_locked=r.qualification_locked,
                qualified_count=r.qualified_count,
                items=tuple(items[r.id]),
            )
        )
    refs: dict[int, list[LegacySourceRef]] = defaultdict(list)
    for r in _rows(conn, _REFS, "s.tournament_id", tournament_ids):
        refs[r.tournament_id].append(LegacySourceRef(r.target_stage_id, r.source_stage_item_id, r.source_position))
    schedules: dict[int, list[LegacySchedule]] = defaultdict(list)
    for r in _rows(conn, _SCHEDULES, "t.id", tournament_ids):
        schedules[r.tournament_id].append(LegacySchedule(r.status, r.starts_at, r.ends_at))

    tournaments = []
    for r in _rows(conn, _TOURNAMENTS, "t.id", tournament_ids):
        if r.status not in LEGACY_STATUS_TARGET:
            raise LegacyStatusMismatch(f"tournament {r.id}: unknown legacy status {r.status!r}")
        tournaments.append(
            LegacyTournament(
                id=r.id,
                status=r.status,
                team_formation=r.team_formation,
                has_teams=r.has_teams,
                check_in_used=r.check_in_used,
                stages=tuple(stages[r.id]),
                source_refs=tuple(refs[r.id]),
                schedules=tuple(schedules[r.id]),
            )
        )
    return tournaments


def write_legacy_flow(conn: Connection, plan: LegacyFlowPlan) -> None:
    insert_node = sa.text(
        """
        INSERT INTO tournament.flow_node (tournament_id, kind, name, status, config, stage_id, position_x, position_y)
        VALUES (:tournament_id, :kind, :name, :status, CAST(:config AS jsonb), :stage_id, :position_x, :position_y)
        RETURNING id
        """
    )
    node_ids: dict[int, int] = {}
    for n in plan.nodes:
        node_ids[n.key] = conn.execute(
            insert_node,
            {
                "tournament_id": plan.tournament_id,
                "kind": n.kind.value,
                "name": n.name,
                "status": n.status.value,
                "config": json.dumps(n.config),
                "stage_id": n.stage_id,
                "position_x": n.position_x,
                "position_y": n.position_y,
            },
        ).scalar_one()
    if plan.edges:
        conn.execute(
            sa.text(
                """
                INSERT INTO tournament.flow_edge (tournament_id, source_node_id, source_port, target_node_id, target_port)
                VALUES (:tournament_id, :source_node_id, :source_port, :target_node_id, :target_port)
                """
            ),
            [
                {
                    "tournament_id": plan.tournament_id,
                    "source_node_id": node_ids[e.source_key],
                    "source_port": e.source_port,
                    "target_node_id": node_ids[e.target_key],
                    "target_port": e.target_port,
                }
                for e in plan.edges
            ],
        )
    if plan.schedules:
        conn.execute(
            sa.text(
                """
                INSERT INTO tournament.flow_node_schedule (node_id, phase, starts_at, ends_at)
                VALUES (:node_id, :phase, :starts_at, :ends_at)
                """
            ),
            [
                {"node_id": node_ids[s.node_key], "phase": s.phase, "starts_at": s.starts_at, "ends_at": s.ends_at}
                for s in plan.schedules
            ],
        )


def backfill(conn: Connection, tournament_ids: Sequence[int] | None = None) -> int:
    plans = []
    for tournament in load_legacy_tournaments(conn, tournament_ids):
        plan = plan_legacy_flow(tournament)
        assert_status_reproduced(tournament, plan)
        plans.append(plan)
    for plan in plans:
        write_legacy_flow(conn, plan)
    return len(plans)


def upgrade() -> None:
    backfill(op.get_bind())


def downgrade() -> None:
    op.execute("DELETE FROM tournament.flow_node")
