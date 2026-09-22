from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from sqlalchemy.orm import configure_mappers  # noqa: E402

import src.models  # noqa: E402,F401  (import registers all models)
from shared.models.balancer import draft as draft_models  # noqa: E402
from shared.models.balancer.draft import (  # noqa: E402
    DraftPick,
    DraftPlayer,
    DraftSession,
    DraftTeam,
)
from shared.models.tenancy.workspace import WorkspaceMember  # noqa: E402
from src.domain.draft import rules  # noqa: E402


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


def test_pick_records_its_overtime_phase_on_the_row() -> None:
    # The phase has to survive a pause/resume, which only moves the deadline, so
    # it lives on the pick rather than being inferred from the clock fields.
    column = DraftPick.__table__.c.overtime_started_at
    assert column.nullable is True


def test_session_configures_overtime_and_defaults_to_none() -> None:
    column = DraftSession.__table__.c.overtime_seconds
    assert column.nullable is False
    assert str(column.server_default.arg) == "0"


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
# draftreg1: the seat IS a registration reference
#
# ``DraftPlayerRole``/``DraftPlayerRoleHero`` and the ``primary_role`` /
# ``sub_role`` / ``is_flex`` / ``division_number`` / ``rank_value`` /
# ``battle_tag`` / ``additional_info`` columns are gone: every one of them was a
# copy of the registration written once at seed time and never re-synced, while
# the balancer resolved the same rank through three layers. What is left on the
# row is draft state plus the FK, and these DB-free tests pin exactly that, so
# a re-added column cannot pass unnoticed.
# --------------------------------------------------------------------------- #
def test_seat_is_anchored_on_a_registration_and_carries_no_roles_or_ranks() -> None:
    columns = set(DraftPlayer.__table__.columns.keys())

    assert columns == {
        "id",
        "created_at",
        "updated_at",
        "session_id",
        "registration_id",
        "workspace_member_id",
        "status",
        "is_captain",
        "drafted_by_team_id",
        "version",
    }
    registration_id = DraftPlayer.__table__.c.registration_id
    assert registration_id.nullable is False
    # RESTRICT: a registration is soft-deleted, so a hard delete is somebody
    # erasing a row a draft depends on. Refusing beats dropping draft history.
    assert registration_id.foreign_keys.pop().ondelete == "RESTRICT"


def test_one_seat_per_registration_per_session() -> None:
    names = {c.name for c in DraftPlayer.__table__.constraints if c.name}
    assert "uq_draft_player_session_registration" in names


def test_draft_player_role_tables_are_gone() -> None:
    # The draft's roles snapshot is what went stale; nothing may reintroduce it.
    assert not hasattr(draft_models, "DraftPlayerRole")
    assert not hasattr(draft_models, "DraftPlayerRoleHero")
    assert "draft_player_role" not in {table.name for table in DraftPlayer.metadata.tables.values()}


def test_seat_resolves_its_domain_player_through_its_member() -> None:
    # The one derivation left on the row: the draft's own ACL and audit rows
    # join on the member, so ``user_id`` still has to answer.
    seated = DraftPlayer(session_id=1, registration_id=5, member=WorkspaceMember(player_id=7))
    assert seated.user_id == 7
    assert DraftPlayer(session_id=1, registration_id=6).user_id is None


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

    result = rules.mark_role_shortage_paused(draft, pick)

    assert draft.status == "paused"
    assert pick.status == "on_clock"
    assert pick.picked_player_id is None
    assert pick.clock_expires_at is None
    assert pick.clock_remaining_ms == 0
    assert result.pick is pick
    assert result.next_pick is None
    assert result.completed is False
    assert result.blocked_reason == "role_shortage"
