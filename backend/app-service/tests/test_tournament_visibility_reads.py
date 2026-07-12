"""DB-backed tests: app-service tournament-scoped reads honour hidden-tournament
visibility (issue #115).

Uses the shared ``rpc`` harness (dispatch a handler by topic with a request
envelope) and the sync ``db`` fixture to seed a throwaway hidden tournament.
Skips cleanly when the dev DB is unreachable (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from shared.core import enums
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament import Tournament


@pytest.fixture
def hidden_and_visible(db):
    """Seed a workspace with one hidden and one visible tournament; yield ids."""
    suffix = uuid.uuid4().hex[:12]
    ws = Workspace(slug=f"vis-app-{suffix}", name=f"Vis App {suffix}")
    db.add(ws)
    db.flush()
    hidden = Tournament(
        workspace_id=ws.id, name=f"Hidden {suffix}", status=enums.TournamentStatus.DRAFT, is_hidden=True
    )
    visible = Tournament(
        workspace_id=ws.id, name=f"Visible {suffix}", status=enums.TournamentStatus.DRAFT, is_hidden=False
    )
    db.add_all([hidden, visible])
    db.commit()
    ids = (ws.id, hidden.id, visible.id)
    try:
        yield ids
    finally:
        db.execute(sa.delete(Workspace).where(Workspace.id == ws.id))
        db.commit()


def _q(tid: int) -> dict:
    return {"query": {"tournament_id": [str(tid)]}}


def test_hidden_playtime_404_for_anon(rpc, hidden_and_visible):
    _ws, hidden_id, _visible = hidden_and_visible
    resp = rpc.call_sync("rpc.app.heroes.playtime", _q(hidden_id))  # no identity
    assert resp["ok"] is False
    assert resp["error"]["code"] == "not_found"


def test_hidden_playtime_allowed_for_superuser(rpc, hidden_and_visible):
    _ws, hidden_id, _visible = hidden_and_visible
    data = _q(hidden_id)
    data["identity"] = {"user_id": 1, "is_superuser": True, "is_active": True}
    resp = rpc.call_sync("rpc.app.heroes.playtime", data)
    assert resp["ok"] is True  # gate passed; playtime is simply empty for a fresh tournament


def test_visible_playtime_ok_for_anon(rpc, hidden_and_visible):
    _ws, _hidden, visible_id = hidden_and_visible
    resp = rpc.call_sync("rpc.app.heroes.playtime", _q(visible_id))  # no identity
    assert resp["ok"] is True


def test_hidden_user_tournament_404_for_anon(rpc, hidden_and_visible):
    _ws, hidden_id, _visible = hidden_and_visible
    # users.tournament takes tournament_id as a top-level path param.
    resp = rpc.call_sync("rpc.app.users.tournament", {"id": 1, "tournament_id": hidden_id})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "not_found"
