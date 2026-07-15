from __future__ import annotations

import importlib
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

from shared.core.enums import DraftRole, DraftStatus  # noqa: E402
from shared.models.balancer.draft import DraftAuditEvent, DraftPlayer, DraftPlayerRole, DraftSession  # noqa: E402
from src.services.draft import feasibility  # noqa: E402


def _module():
    try:
        return importlib.import_module("src.services.draft.role_edit")
    except ModuleNotFoundError as exc:
        pytest.fail(f"draft role-edit service is not implemented: {exc}")


def _code(exc: Exception) -> str:
    return exc.detail[0]["code"]


def _draft(status: DraftStatus = DraftStatus.PAUSED) -> DraftSession:
    return DraftSession(id=1, tournament_id=1, workspace_id=1, status=status.value, team_size=3, rounds=2)


def _player() -> DraftPlayer:
    return DraftPlayer(
        id=20,
        session_id=1,
        primary_role=DraftRole.DPS.value,
        status="available",
        version=4,
        roles=[DraftPlayerRole(role=DraftRole.DPS.value, priority=0)],
    )


@pytest.mark.parametrize("status", [DraftStatus.LIVE, DraftStatus.COMPLETED, DraftStatus.CANCELLED])
def test_role_edit_requires_setup_ready_or_paused(status: DraftStatus) -> None:
    role_edit = _module()

    with pytest.raises(Exception) as exc_info:
        role_edit.validate_role_edit_request(
            _draft(status),
            _player(),
            role=DraftRole.SUPPORT,
            rank_value=2500,
            rank_absence_confirmed=False,
            reason="Player confirmed secondary role",
            expected_version=4,
        )

    assert _code(exc_info.value) == "role_edit_requires_pause"


def test_role_edit_rejects_duplicate_role() -> None:
    role_edit = _module()

    with pytest.raises(Exception) as exc_info:
        role_edit.validate_role_edit_request(
            _draft(),
            _player(),
            role=DraftRole.DPS,
            rank_value=3000,
            rank_absence_confirmed=False,
            reason="Duplicate",
            expected_version=4,
        )

    assert _code(exc_info.value) == "role_already_exists"


def test_role_edit_requires_reason_rank_confirmation_and_current_version() -> None:
    role_edit = _module()
    player = _player()

    with pytest.raises(Exception) as reason_error:
        role_edit.validate_role_edit_request(
            _draft(),
            player,
            role=DraftRole.SUPPORT,
            rank_value=2500,
            rank_absence_confirmed=False,
            reason="   ",
            expected_version=4,
        )
    assert _code(reason_error.value) == "role_edit_reason_required"

    with pytest.raises(Exception) as rank_error:
        role_edit.validate_role_edit_request(
            _draft(),
            player,
            role=DraftRole.SUPPORT,
            rank_value=None,
            rank_absence_confirmed=False,
            reason="Confirmed by player",
            expected_version=4,
        )
    assert _code(rank_error.value) == "role_rank_confirmation_required"

    with pytest.raises(Exception) as version_error:
        role_edit.validate_role_edit_request(
            _draft(),
            player,
            role=DraftRole.SUPPORT,
            rank_value=2500,
            rank_absence_confirmed=False,
            reason="Confirmed by player",
            expected_version=3,
        )
    assert _code(version_error.value) == "draft_player_stale"


def test_role_edit_preview_can_restore_global_feasibility_without_mutating_state() -> None:
    role_edit = _module()
    state = feasibility.DraftFeasibilityState(
        team_ids=(10, 20),
        role_targets={DraftRole.TANK: 1, DraftRole.DPS: 1, DraftRole.SUPPORT: 1},
        players=(
            feasibility.EligiblePlayer(1, frozenset({DraftRole.SUPPORT})),
            feasibility.EligiblePlayer(2, frozenset({DraftRole.DPS})),
            feasibility.EligiblePlayer(3, frozenset({DraftRole.DPS})),
            feasibility.EligiblePlayer(4, frozenset({DraftRole.DPS})),
        ),
        assignments=(
            feasibility.DraftAssignment(101, 10, DraftRole.TANK),
            feasibility.DraftAssignment(102, 20, DraftRole.TANK),
        ),
    )

    preview = role_edit.preview_role_addition(state, player_id=2, role=DraftRole.SUPPORT)

    assert preview.before.is_feasible is False
    assert preview.after.is_feasible is True
    assert state.players[1].playable_roles == frozenset({DraftRole.DPS})


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


def test_apply_role_edit_updates_snapshot_version_and_private_audit() -> None:
    role_edit = _module()
    player = _player()
    state = feasibility.DraftFeasibilityState(
        team_ids=(10,),
        role_targets={DraftRole.TANK: 1, DraftRole.DPS: 1, DraftRole.SUPPORT: 1},
        players=(feasibility.EligiblePlayer(20, frozenset({DraftRole.DPS})),),
        assignments=(),
    )
    preview = role_edit.preview_role_addition(state, player_id=20, role=DraftRole.SUPPORT)
    session = _FakeSession()

    audit = role_edit.apply_role_edit(
        session,
        _draft(),
        player,
        role=DraftRole.SUPPORT,
        rank_value=2750,
        reason="  Confirmed secondary role  ",
        actor_auth_user_id=99,
        preview=preview,
    )

    assert player.version == 5
    added_role = next(role for role in player.roles if role.role == DraftRole.SUPPORT.value)
    assert added_role.rank_value == 2750
    assert added_role.is_secondary is True
    assert audit in session.added
    assert isinstance(audit, DraftAuditEvent)
    assert audit.reason == "Confirmed secondary role"
    assert audit.before_json["feasibility"]["is_feasible"] is False
    assert audit.after_json["feasibility"]["is_feasible"] is False
    assert "reason" not in audit.after_json
