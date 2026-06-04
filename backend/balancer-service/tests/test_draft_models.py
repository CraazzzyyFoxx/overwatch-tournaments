from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from sqlalchemy.orm import configure_mappers  # noqa: E402

import src.models  # noqa: E402,F401  (import registers all models)
from shared.models.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam  # noqa: E402


def test_mappers_configure_cleanly() -> None:
    # Raises if any relationship/foreign_keys is ambiguous or unresolved.
    configure_mappers()


def test_tables_live_in_balancer_schema() -> None:
    for model in (DraftSession, DraftTeam, DraftPlayer, DraftPick):
        assert model.__table__.schema == "balancer"


def test_session_has_partial_unique_active_index() -> None:
    idx = {i.name for i in DraftSession.__table__.indexes}
    assert "uq_draft_session_active_tournament" in idx


def test_pick_has_version_and_clock_columns() -> None:
    cols = set(DraftPick.__table__.columns.keys())
    assert {"version", "clock_started_at", "clock_expires_at", "clock_remaining_ms"} <= cols


def test_session_pick_circular_relationship_resolves() -> None:
    # picks via DraftPick.session_id; current_pick via current_pick_id
    assert DraftSession.picks.property.mapper.class_ is DraftPick
    assert DraftSession.current_pick.property.mapper.class_ is DraftPick


def test_unique_constraints_present() -> None:
    pick_uqs = {c.name for c in DraftPick.__table__.constraints if c.name}
    assert "uq_draft_pick_session_overall" in pick_uqs
    team_uqs = {c.name for c in DraftTeam.__table__.constraints if c.name}
    assert "uq_draft_team_session_position" in team_uqs
