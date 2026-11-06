"""DB-backed tests for the tournament readiness aggregate (Phase 1, D13/§7.1).

Seeds a throwaway workspace/tournament with the sync ``db`` fixture (mirrors
``test_tournament_visibility_reads.py``) and exercises both the pure
``compute_readiness`` aggregate and the ``rpc.tournament.tournament_readiness``
subscriber, including permission masking (ANY(tournament.read, team.read) gate;
tournament/team/match/achievement ``read`` each unmask one group, a missing
group -> None fields).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.models.catalog.role import CatalogRole, RoleDimension
from shared.models.encounter import ScoringRule
from shared.models.registration.registration import (
    Registration,
    RegistrationForm,
    RegistrationRole,
)
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament import Stage, Tournament
from tests.encounter_seed import seed_encounter, seed_scoring_rule

TOPIC = "rpc.tournament.tournament_readiness"


@pytest.fixture
def seeded(db):
    """Workspace + tournament with: 1 schedule row, 1 empty stage, open form,
    3 approved regs (2 checked-in; pool: ready/incomplete/not_in_balancer),
    1 pending reg, 2 regs with saved rank data, no encounters/balance/draft."""
    suffix = uuid.uuid4().hex[:12]
    ws = Workspace(slug=f"ready-{suffix}", name=f"Ready {suffix}")
    db.add(ws)
    db.flush()
    t = Tournament(
        workspace_id=ws.id,
        name=f"Readiness {suffix}",
        slug=f"readiness-{suffix}",
        status=enums.TournamentStatus.LIVE,
    )
    db.add(t)
    db.flush()
    rule = ScoringRule(workspace_id=ws.id, preset="wins", game_formula="win", end_formula="games >= best_of")
    db.add(rule)
    db.flush()
    db.add(Stage(tournament_id=t.id, name="Groups", stage_type=enums.StageType.ROUND_ROBIN, scoring_rule_id=rule.id))
    db.add(RegistrationForm(tournament_id=t.id, workspace_id=ws.id))
    regs = [Registration(tournament_id=t.id, display_name=name) for name in "abcd"]
    node = models.FlowNode(tournament_id=t.id, kind="registration", name="Registration", status="open", config={})
    formation = models.FlowNode(
        tournament_id=t.id, kind="formation", name="Teams", status="draft", config={"mode": "balancer"}
    )
    db.add_all([*regs, node, formation])
    db.flush()
    db.add(models.FlowNodeSchedule(node_id=node.id, phase="open", starts_at=datetime.now(UTC)))
    db.add_all(
        models.RegistrationEntry(registration_node_id=node.id, registration_id=reg.id, **fields)
        for reg, fields in zip(
            regs,
            (
                {"status": "approved", "checked_in": True, "balancer_status": "ready"},
                {"status": "approved", "checked_in": True, "balancer_status": "incomplete"},
                {"status": "approved"},
                {"status": "pending"},
            ),
            strict=True,
        )
    )
    db.flush()
    # Saved rank data on two registrations (one approved, one pending); the
    # role without rank_value must NOT count as ranked.
    catalog_roles = {
        row.code: row
        for row in db.scalars(
            sa.select(CatalogRole)
            .join(RoleDimension, RoleDimension.id == CatalogRole.dimension_id)
            .where(
                RoleDimension.discipline == t.discipline,
                RoleDimension.rated.is_(True),
                CatalogRole.workspace_id.is_(None),
            )
        )
    }
    for registration, code, rank in ((regs[0], "tank", 2500), (regs[1], "damage", None), (regs[3], "support", 1800)):
        leaf = catalog_roles[code]
        db.add(
            RegistrationRole(
                registration_id=registration.id,
                catalog_role=leaf,
                dimension_id=leaf.dimension_id,
                is_primary=True,
                rank_value=rank,
            )
        )
    db.commit()
    try:
        yield ws.id, t.id
    finally:
        db.execute(sa.delete(Workspace).where(Workspace.id == ws.id))
        db.commit()


def _identity(ws_id: int, perms: list[dict[str, str]]) -> dict:
    return {
        "user_id": 424242,
        "is_superuser": False,
        "is_active": True,
        "roles": [],
        "permissions": [],
        "workspaces": [{"workspace_id": ws_id, "rbac_roles": [], "rbac_permissions": perms}],
    }


def test_readiness_counts(rpc, seeded):
    from src.core import db as async_db
    from src.services.dashboard.readiness import readiness

    _ws_id, tournament_id = seeded

    async def run():
        async with async_db.async_session_maker() as session:
            return await readiness.compute_readiness(session, tournament_id)

    r = asyncio.run(run())
    assert r.tournament_id == tournament_id
    assert r.status == "live"
    assert r.formation_modes == ["balancer"]
    # tournament.read group
    assert r.schedule_configured is True
    assert r.grid_selected is False
    assert r.stages_total == 1
    assert r.stage_slots_filled is False
    assert r.bracket_generated is False
    assert r.duel_encounters_total == 0
    assert r.duel_encounters_with_logs == 0
    assert r.logs_used is False
    assert r.standings_recalc_pending is False
    # team.read group
    assert r.registration_form_configured is True
    assert r.registrations_pending == 1
    assert r.registrations_approved == 3
    assert r.registrations_checked_in == 2
    assert r.registrations_ranked == 2
    assert r.pool_ready == 1
    assert r.pool_need_fix == 1
    assert r.balance_saved is False
    assert r.balance_exported_at is None
    assert r.draft_session_status is None
    # match.read group
    assert r.results_overdue == 0
    assert r.results_pending_confirmation == 0
    assert r.results_disputed == 0
    # achievement.read group: no enabled rule for the discipline
    assert r.achievements_status == "not_configured"


def test_readiness_masks_fields_without_team_read(rpc, seeded):
    ws_id, tournament_id = seeded
    resp = rpc.call_sync(
        TOPIC,
        {"id": tournament_id, "identity": _identity(ws_id, [{"resource": "tournament", "action": "read"}])},
    )
    assert resp["ok"] is True
    d = resp["data"]
    assert d["stages_total"] == 1
    assert d["schedule_configured"] is True
    # team.read-gated fields are masked, not zeroed
    assert d["registrations_approved"] is None
    assert d["registrations_ranked"] is None
    assert d["pool_ready"] is None
    assert d["balance_saved"] is None
    # match.read / achievement.read groups are masked too
    assert d["results_overdue"] is None
    assert d["results_pending_confirmation"] is None
    assert d["results_disputed"] is None
    assert d["achievements_status"] is None


def test_readiness_masks_fields_without_tournament_read(rpc, seeded):
    ws_id, tournament_id = seeded
    resp = rpc.call_sync(
        TOPIC,
        {"id": tournament_id, "identity": _identity(ws_id, [{"resource": "team", "action": "read"}])},
    )
    assert resp["ok"] is True
    d = resp["data"]
    # always-visible header
    assert d["tournament_id"] == tournament_id
    assert d["status"] == "live"
    assert d["formation_modes"] == ["balancer"]
    # tournament.read-gated fields are masked
    assert d["stages_total"] is None
    assert d["logs_used"] is None
    assert d["duel_encounters_total"] is None
    assert d["duel_encounters_with_logs"] is None
    assert d["standings_recalc_pending"] is None
    # team.read group visible
    assert d["registrations_approved"] == 3
    assert d["registrations_checked_in"] == 2


def test_readiness_match_and_achievement_read_unmask_their_groups(rpc, seeded):
    ws_id, tournament_id = seeded
    perms = [{"resource": resource, "action": "read"} for resource in ("team", "match", "achievement")]
    resp = rpc.call_sync(TOPIC, {"id": tournament_id, "identity": _identity(ws_id, perms)})
    assert resp["ok"] is True
    d = resp["data"]
    assert d["results_overdue"] == 0
    assert d["results_disputed"] == 0
    assert d["achievements_status"] == "not_configured"
    assert d["stages_total"] is None


def test_readiness_forbidden_without_any_permission(rpc, seeded):
    ws_id, tournament_id = seeded
    resp = rpc.call_sync(
        TOPIC,
        {"id": tournament_id, "identity": _identity(ws_id, [{"resource": "log", "action": "read"}])},
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "forbidden"


def test_readiness_not_found(rpc):
    resp = rpc.call_sync(TOPIC, {"id": 999999999, "identity": {"user_id": 1, "is_superuser": True, "is_active": True}})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "not_found"


def test_readiness_counts_duels_toward_logs_and_open_results_by_status(db_session):
    """Lobbies never count toward log coverage; open results split by status;
    a requested recalculation and an evaluation run surface as such."""
    from src.services.dashboard.readiness import readiness

    now = datetime.now(UTC)

    async def go():
        suffix = uuid.uuid4().hex[:12]
        ws = Workspace(slug=f"ready-{suffix}", name=f"Ready {suffix}")
        played_map = models.CatalogEntity(
            discipline="overwatch", kind="map", slug=f"ready-{suffix}", name=f"Ready {suffix}", image_path="x"
        )
        db_session.add_all([ws, played_map])
        await db_session.flush()
        ws_id, map_id = ws.id, played_map.id
        try:
            t = Tournament(
                workspace_id=ws_id, name=f"Live {suffix}", slug=f"live-{suffix}", status=enums.TournamentStatus.LIVE
            )
            db_session.add(t)
            await db_session.flush()
            rule_id = await seed_scoring_rule(db_session, ws_id)
            duel = [(None, 0), (None, 0)]

            async def encounter(name, seats=duel, *, logged=False, **columns):
                row = await seed_encounter(db_session, t, rule_id, seats, name=name, **columns)
                if logged:
                    db_session.add(
                        models.StatsMatch(
                            workspace_id=ws_id, discipline=t.discipline, encounter_id=row.id, map_entity_id=map_id
                        )
                    )
                return row

            await encounter("logged", logged=True)
            await encounter("plain")
            # A lobby with logs is still not a duel: neither total nor covered.
            await encounter("lobby", [*duel, (None, 0)], logged=True)
            await encounter("overdue", completed=False, scheduled_at=now - timedelta(hours=1))
            await encounter("upcoming", completed=False, scheduled_at=now + timedelta(days=1))
            for name, result_status in (
                ("pending", enums.EncounterResultStatus.PENDING_CONFIRMATION),
                ("disputed", enums.EncounterResultStatus.DISPUTED),
            ):
                (await encounter(name, completed=False)).result_status = result_status
            db_session.add_all(
                [
                    models.TournamentRecalculationState(
                        tournament_id=t.id, requested_generation=2, completed_generation=1
                    ),
                    models.AchievementRule(
                        workspace_id=ws_id,
                        slug=f"ready-{suffix}",
                        name="Rule",
                        description_ru="ru",
                        description_en="en",
                        discipline=t.discipline,
                        category="overall",
                        scope="global",
                        grain="user",
                        condition_tree={},
                        depends_on=[],
                        enabled=True,
                        rule_version=1,
                    ),
                    models.EvaluationRun(workspace_id=ws_id, trigger="manual", tournament_id=t.id, status="done"),
                ]
            )
            tournament_id = t.id
            await db_session.commit()
            db_session.expunge_all()
            return await readiness.compute_readiness(db_session, tournament_id)
        finally:
            await db_session.rollback()
            # Workspace first: its matches hold the map.
            await db_session.execute(sa.delete(Workspace).where(Workspace.id == ws_id))
            await db_session.execute(sa.delete(models.CatalogEntity).where(models.CatalogEntity.id == map_id))
            await db_session.commit()

    r = asyncio.run(go())
    # logged, plain, overdue, upcoming, pending, disputed; the logged lobby is in neither count.
    assert (r.duel_encounters_total, r.duel_encounters_with_logs, r.logs_used) == (6, 1, True)
    assert (r.results_overdue, r.results_pending_confirmation, r.results_disputed) == (1, 1, 1)
    assert r.standings_recalc_pending is True
    assert r.achievements_status == "done"
