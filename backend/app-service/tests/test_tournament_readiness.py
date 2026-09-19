"""DB-backed tests for the tournament readiness aggregate (Phase 1, D13/§7.1).

Seeds a throwaway workspace/tournament with the sync ``db`` fixture (mirrors
``test_tournament_visibility_reads.py``) and exercises both the pure
``compute_readiness`` aggregate and the ``rpc.app.statistics.tournament_readiness``
subscriber, including permission masking (ANY(tournament.read, team.read) gate,
missing group -> None fields).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from shared.core import enums
from shared.models.registration.registration import (
    BalancerRegistration,
    BalancerRegistrationForm,
    BalancerRegistrationRole,
)
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament import Stage, Tournament, TournamentPhaseSchedule

TOPIC = "rpc.app.statistics.tournament_readiness"


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
        status=enums.TournamentStatus.REGISTRATION,
    )
    db.add(t)
    db.flush()
    db.add(
        TournamentPhaseSchedule(
            tournament_id=t.id,
            status=enums.TournamentStatus.REGISTRATION,
            starts_at=datetime.now(UTC),
        )
    )
    db.add(Stage(tournament_id=t.id, name="Groups", stage_type=enums.StageType.ROUND_ROBIN))
    db.add(BalancerRegistrationForm(tournament_id=t.id, workspace_id=ws.id, is_open=True))
    regs = [
        BalancerRegistration(
            tournament_id=t.id, display_name="a", status="approved", checked_in=True, balancer_status="ready"
        ),
        BalancerRegistration(
            tournament_id=t.id, display_name="b", status="approved", checked_in=True, balancer_status="incomplete"
        ),
        BalancerRegistration(tournament_id=t.id, display_name="c", status="approved"),
        BalancerRegistration(tournament_id=t.id, display_name="d", status="pending"),
    ]
    db.add_all(regs)
    db.flush()
    # Saved rank data on two registrations (one approved, one pending); the
    # role without rank_value must NOT count as ranked.
    db.add(BalancerRegistrationRole(registration_id=regs[0].id, role="tank", is_primary=True, rank_value=2500))
    db.add(BalancerRegistrationRole(registration_id=regs[1].id, role="damage", is_primary=True, rank_value=None))
    db.add(BalancerRegistrationRole(registration_id=regs[3].id, role="support", is_primary=True, rank_value=1800))
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
    assert r.status == "registration"
    assert r.team_formation == "balancer"
    # tournament.read group
    assert r.schedule_configured is True
    assert r.grid_selected is False
    assert r.stages_total == 1
    assert r.stage_slots_filled is False
    assert r.bracket_generated is False
    assert r.encounters_total == 0
    assert r.encounters_with_logs == 0
    assert r.logs_used is False
    # team.read group
    assert r.registration_form_configured is True
    assert r.registration_open is True
    assert r.registrations_pending == 1
    assert r.registrations_approved == 3
    assert r.registrations_checked_in == 2
    assert r.registrations_ranked == 2
    assert r.pool_ready == 1
    assert r.pool_need_fix == 1
    assert r.balance_saved is False
    assert r.balance_exported_at is None
    assert r.draft_session_status is None


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
    assert d["registration_open"] is None
    assert d["balance_saved"] is None


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
    assert d["status"] == "registration"
    assert d["team_formation"] == "balancer"
    # tournament.read-gated fields are masked
    assert d["stages_total"] is None
    assert d["logs_used"] is None
    # team.read group visible
    assert d["registrations_approved"] == 3
    assert d["registrations_checked_in"] == 2


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
