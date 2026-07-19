from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

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
from shared.core.enums import DraftRole  # noqa: E402
from shared.models.balancer import draft as draft_models  # noqa: E402
from shared.models.balancer.draft import (  # noqa: E402
    DraftPick,
    DraftPlayer,
    DraftPlayerRole,
    DraftSession,
    DraftTeam,
)
from shared.models.tenancy.workspace import WorkspaceMember  # noqa: E402
from src.services.draft import selection  # noqa: E402
from src.services.draft.selection import _role_is_legal  # noqa: E402


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


def test_player_has_version_for_role_edit_concurrency() -> None:
    version = DraftPlayer.__table__.c.version
    assert version.nullable is False
    assert str(version.server_default.arg) == "0"


def test_session_has_version_for_reseed_concurrency() -> None:
    version = DraftSession.__table__.c.version
    assert version.nullable is False
    assert str(version.server_default.arg) == "0"


def test_session_persists_structured_pause_reason() -> None:
    column = DraftSession.__table__.c.blocked_reason

    assert column.nullable is True


def test_draft_audit_event_keeps_private_before_after_reason() -> None:
    DraftAuditEvent = getattr(draft_models, "DraftAuditEvent", None)
    if DraftAuditEvent is None:
        pytest.fail("DraftAuditEvent model is not implemented")
    table = DraftAuditEvent.__table__
    assert table.schema == "balancer"
    assert {
        "session_id",
        "actor_auth_user_id",
        "action",
        "entity_type",
        "entity_id",
        "reason",
        "before_json",
        "after_json",
    } <= set(table.columns.keys())
    index_names = {index.name for index in table.indexes}
    assert "ix_draft_audit_session_created" in index_names
    assert table.c.session_id.foreign_keys.pop().ondelete == "CASCADE"
    assert table.c.actor_auth_user_id.foreign_keys.pop().ondelete == "SET NULL"


def test_session_pick_circular_relationship_resolves() -> None:
    # picks via DraftPick.session_id; current_pick via current_pick_id
    assert DraftSession.picks.property.mapper.class_ is DraftPick
    assert DraftSession.current_pick.property.mapper.class_ is DraftPick


def test_unique_constraints_present() -> None:
    pick_uqs = {c.name for c in DraftPick.__table__.constraints if c.name}
    assert "uq_draft_pick_session_overall" in pick_uqs
    team_uqs = {c.name for c in DraftTeam.__table__.constraints if c.name}
    assert "uq_draft_team_session_position" in team_uqs


# --------------------------------------------------------------------------- #
# dbarch03 compatibility read shims
#
# The autopick/select/board/export paths read these properties off eager-loaded
# rows (member + roles child rows) instead of the dropped user_id/role_ranks/
# secondary_roles_json/captain_user_id/picked_by_user_id columns. These pure,
# DB-free tests assert the shims reconstruct the pre-dbarch03 read shape — the
# invariant the eager-load option sets exist to protect. (The DB-backed autopick
# path is covered by the integration suite, which skips without Postgres.)
# --------------------------------------------------------------------------- #
def test_player_compat_properties_reconstruct_old_shape() -> None:
    player = DraftPlayer(
        session_id=1,
        primary_role="dps",
        rank_value=4000,
        member=WorkspaceMember(player_id=7),
        roles=[
            DraftPlayerRole(role="dps", rank_value=4000, is_secondary=False, priority=0),
            DraftPlayerRole(role="support", rank_value=2800, is_secondary=True, priority=1),
        ],
    )
    assert player.user_id == 7
    assert player.secondary_roles_json == ["support"]
    assert player.role_ranks == {"dps": 4000, "support": 2800}


def test_player_compat_properties_empty_without_member_or_roles() -> None:
    player = DraftPlayer(session_id=1, primary_role="dps", rank_value=3000)
    assert player.user_id is None
    assert player.secondary_roles_json is None  # empty -> None, matching old writer
    assert player.role_ranks == {}


def test_role_is_legal_reads_off_role_from_child_rows() -> None:
    # The autopick/select legality gate reads secondary_roles_json (roles rows).
    player = DraftPlayer(
        session_id=1,
        primary_role="dps",
        rank_value=4000,
        roles=[
            DraftPlayerRole(role="dps", is_secondary=False, priority=0),
            DraftPlayerRole(role="support", rank_value=2800, is_secondary=True, priority=1),
        ],
    )
    assert _role_is_legal(player, DraftRole.SUPPORT) is True  # declared off-role
    assert _role_is_legal(player, DraftRole.TANK) is False  # not playable
    assert _role_is_legal(player, None) is True  # no requested role


def test_team_and_pick_compat_properties() -> None:
    team = DraftTeam(session_id=1, name="T", draft_position=1, captain_member=WorkspaceMember(player_id=9))
    assert team.captain_user_id == 9
    assert DraftTeam(session_id=1, name="T2", draft_position=2).captain_user_id is None

    pick = DraftPick(
        session_id=1,
        overall_no=1,
        round_no=1,
        pick_in_round=1,
        draft_team_id=1,
        picked_by_member=WorkspaceMember(player_id=5),
    )
    assert pick.picked_by_user_id == 5
    pick_none = DraftPick(session_id=1, overall_no=2, round_no=1, pick_in_round=2, draft_team_id=1)
    assert pick_none.picked_by_user_id is None


def test_role_shortage_pauses_without_resolving_the_current_pick() -> None:
    draft = DraftSession(id=1, tournament_id=1, workspace_id=1, status="live", current_pick_id=9)
    pick = DraftPick(
        id=9,
        session_id=1,
        overall_no=1,
        round_no=1,
        pick_in_round=1,
        draft_team_id=10,
        status="on_clock",
        clock_remaining_ms=None,
    )

    result = selection.mark_role_shortage_paused(draft, pick)

    assert draft.status == "paused"
    assert pick.status == "on_clock"
    assert pick.picked_player_id is None
    assert pick.clock_expires_at is None
    assert pick.clock_remaining_ms == 0
    assert result.pick is pick
    assert result.next_pick is None
    assert result.completed is False
    assert result.blocked_reason == "role_shortage"
