"""Admin-only emergency role additions.

After ``draftreg1`` the write lands on the REGISTRATION
(``balancer.registration_role``), not on a draft-local roles snapshot: the
balancer is the only writer of roles and ranks, so the board, the pool verdict
and the balance job all see the edit at once. What the draft still owns is the
guard, the before/after feasibility preview and the private audit row.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.core.enums import DraftStatus, HeroClass  # noqa: E402
from shared.models.balancer.draft import DraftAuditEvent, DraftPlayer, DraftSession  # noqa: E402
from shared.models.registration.registration import BalancerRegistrationRole  # noqa: E402
from src.domain.draft import entities as feasibility  # noqa: E402
from src.domain.draft import rules  # noqa: E402
from tests.factories import roster  # noqa: E402


def _module():
    try:
        return importlib.import_module("src.services.draft.role_edit")
    except ModuleNotFoundError as exc:
        pytest.fail(f"draft role-edit service is not implemented: {exc}")


def _code(exc: Exception) -> str:
    return exc.detail[0]["code"]


def _draft(status: DraftStatus = DraftStatus.PAUSED) -> DraftSession:
    # `rounds` is all a session stores about its size now; the roster shape is
    # resolved per tournament, and role_edit reads it through feasibility.
    return DraftSession(id=1, tournament_id=1, workspace_id=1, status=status.value, rounds=2)


def _player() -> DraftPlayer:
    return DraftPlayer(id=20, session_id=1, registration_id=120, status="available", version=4)


def _roster():
    return roster(120, ranks={"damage": 4000})


@pytest.mark.parametrize("status", [DraftStatus.LIVE, DraftStatus.COMPLETED, DraftStatus.CANCELLED])
def test_role_edit_requires_setup_ready_or_paused(status: DraftStatus) -> None:
    with pytest.raises(Exception) as exc_info:
        rules.validate_role_edit_request(
            _draft(status),
            _player(),
            _roster(),
            role=HeroClass.support,
            rank_value=2500,
            reason="Player confirmed secondary role",
            expected_version=4,
        )

    assert _code(exc_info.value) == "role_edit_requires_pause"


def test_role_edit_rejects_a_role_the_player_already_plays() -> None:
    with pytest.raises(Exception) as exc_info:
        rules.validate_role_edit_request(
            _draft(),
            _player(),
            _roster(),
            role=HeroClass.damage,
            rank_value=3000,
            reason="Duplicate",
            expected_version=4,
        )

    assert _code(exc_info.value) == "role_already_exists"


def test_a_role_declared_but_unranked_is_not_a_duplicate() -> None:
    # The exact case an emergency edit exists for: the sheet import created the
    # row and its rank did not parse, so the role is declared, inactive and
    # unplayable. Refusing it as "already exists" left the organizer no way in.
    normalized = rules.validate_role_edit_request(
        _draft(),
        _player(),
        roster(120, ranks={"damage": 4000, "support": None}),
        role=HeroClass.support,
        rank_value=2500,
        reason="  Rank confirmed in VOD  ",
        expected_version=4,
    )

    assert normalized == "Rank confirmed in VOD"


def test_role_edit_requires_a_reason_a_positive_rank_and_the_current_version() -> None:
    player = _player()

    with pytest.raises(Exception) as reason_error:
        rules.validate_role_edit_request(
            _draft(),
            player,
            _roster(),
            role=HeroClass.support,
            rank_value=2500,
            reason="   ",
            expected_version=4,
        )
    assert _code(reason_error.value) == "role_edit_reason_required"

    # There is no "confirm the rank is missing" escape hatch any more: a role
    # without a rank is not playable, so adding one would change nothing.
    with pytest.raises(Exception) as rank_error:
        rules.validate_role_edit_request(
            _draft(),
            player,
            _roster(),
            role=HeroClass.support,
            rank_value=0,
            reason="Confirmed by player",
            expected_version=4,
        )
    assert _code(rank_error.value) == "role_rank_required"

    with pytest.raises(Exception) as version_error:
        rules.validate_role_edit_request(
            _draft(),
            player,
            _roster(),
            role=HeroClass.support,
            rank_value=2500,
            reason="Confirmed by player",
            expected_version=3,
        )
    assert _code(version_error.value) == "draft_player_stale"


def test_role_edit_accepts_a_seat_the_engine_resolved_no_roster_for() -> None:
    # An organizer who cleared every rank leaves the seat with nothing playable.
    # That is precisely who needs the edit, so a missing roster must not read as
    # "already plays it" nor crash the guard.
    assert (
        rules.validate_role_edit_request(
            _draft(),
            _player(),
            None,
            role=HeroClass.support,
            rank_value=2500,
            reason="Rank recovered",
            expected_version=4,
        )
        == "Rank recovered"
    )


def test_role_edit_preview_can_restore_global_feasibility_without_mutating_state() -> None:
    state = feasibility.DraftFeasibilityState(
        team_ids=(10, 20),
        slot_targets={"tank": 1, "damage": 1, "support": 1},
        players=(
            feasibility.EligiblePlayer(1, frozenset({HeroClass.support})),
            feasibility.EligiblePlayer(2, frozenset({HeroClass.damage})),
            feasibility.EligiblePlayer(3, frozenset({HeroClass.damage})),
            feasibility.EligiblePlayer(4, frozenset({HeroClass.damage})),
        ),
        assignments=(
            feasibility.DraftAssignment(101, 10, "tank"),
            feasibility.DraftAssignment(102, 20, "tank"),
        ),
    )

    preview = rules.preview_role_addition(state, player_id=2, role=HeroClass.support)

    assert preview.before.is_feasible is False
    assert preview.after.is_feasible is True
    assert state.players[1].playable_roles == frozenset({HeroClass.damage})


class _FakeSession:
    """Answers the two reads ``_write_registration_role`` makes, in order.

    ``scalar``: the existing ``registration_role`` row (or ``None``), then
    ``max(priority)`` for the next one.
    """

    def __init__(self, existing: BalancerRegistrationRole | None = None, max_priority: int = 2) -> None:
        self._scalars: list = [existing] if existing is not None else [None, max_priority]
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def scalar(self, _statement):
        return self._scalars.pop(0)

    async def flush(self) -> None:
        return None


class _FakeRosters:
    """Stands in for ``DraftRosterService``; ``apply_role_edit`` re-reads through it."""

    def __init__(self, after) -> None:
        self._after = after
        self.calls = 0

    async def load(self, _session, _draft_session, players) -> dict:
        self.calls += 1
        return {player.id: self._after for player in players}


class _FakeAuditRepo:
    def __init__(self) -> None:
        self.created: list[DraftAuditEvent] = []

    async def create(self, _session, audit: DraftAuditEvent) -> DraftAuditEvent:
        self.created.append(audit)
        return audit


def _service(*, rosters, audit_repo):
    role_edit = _module()
    return role_edit.DraftRoleEditService(rosters=rosters, audit_repo=audit_repo)


def _preview(player_id: int = 20):
    state = feasibility.DraftFeasibilityState(
        team_ids=(10,),
        slot_targets={"tank": 1, "damage": 1, "support": 1},
        players=(feasibility.EligiblePlayer(player_id, frozenset({HeroClass.damage})),),
        assignments=(),
    )
    return rules.preview_role_addition(state, player_id=player_id, role=HeroClass.support)


def test_apply_role_edit_writes_the_registration_bumps_the_seat_and_audits() -> None:
    player = _player()
    before = _roster()
    after = roster(120, ranks={"damage": 4000, "support": 2750})
    session = _FakeSession(max_priority=2)
    rosters = _FakeRosters(after)
    audit_repo = _FakeAuditRepo()

    audit = asyncio.run(
        _service(rosters=rosters, audit_repo=audit_repo).apply_role_edit(
            session,  # type: ignore[arg-type]
            _draft(),
            player,
            before,
            role=HeroClass.support,
            rank_value=2750,
            reason="  Confirmed secondary role  ",
            actor_auth_user_id=99,
            preview=_preview(),
        )
    )

    # The role landed on balancer.registration_role -- NOT on a draft snapshot.
    added = [row for row in session.added if isinstance(row, BalancerRegistrationRole)]
    assert len(added) == 1
    assert (added[0].registration_id, added[0].role, added[0].rank_value) == (120, "support", 2750)
    assert added[0].is_active is True
    assert added[0].is_primary is False
    assert added[0].priority == 3  # max(priority) + 1
    # The seat keeps only the optimistic token the preview was taken against.
    assert player.version == 5

    assert audit in audit_repo.created
    assert isinstance(audit, DraftAuditEvent)
    assert audit.reason == "Confirmed secondary role"
    assert audit.before_json["registration_id"] == 120
    assert [entry["role"] for entry in audit.before_json["roles"]] == ["damage"]
    # The after-roles are RE-RESOLVED through the engine, not assembled by hand.
    assert rosters.calls == 1
    assert [entry["role"] for entry in audit.after_json["roles"]] == ["damage", "support"]
    assert audit.after_json["roles"][1]["rank_value"] == 2750
    assert audit.before_json["feasibility"]["is_feasible"] is False
    assert audit.after_json["feasibility"]["is_feasible"] is False
    assert "reason" not in audit.after_json


def test_apply_role_edit_reactivates_an_existing_inactive_registration_role() -> None:
    # The common case: a sheet import created the row and its rank did not
    # parse, so it sits there inactive. Inserting a second row would violate
    # uq_balancer_registration_role, and leaving is_active=False would keep the
    # role unplayable -- the edit has to flip both fields on the row that exists.
    existing = BalancerRegistrationRole(
        registration_id=120,
        role="support",
        is_primary=False,
        priority=1,
        rank_value=None,
        is_active=False,
    )
    session = _FakeSession(existing=existing)

    asyncio.run(
        _service(
            rosters=_FakeRosters(roster(120, ranks={"damage": 4000, "support": 2750})), audit_repo=_FakeAuditRepo()
        ).apply_role_edit(
            session,  # type: ignore[arg-type]
            _draft(),
            _player(),
            roster(120, ranks={"damage": 4000, "support": None}),
            role=HeroClass.support,
            rank_value=2750,
            reason="Rank confirmed in VOD",
            actor_auth_user_id=99,
            preview=_preview(),
        )
    )

    assert existing.rank_value == 2750
    assert existing.is_active is True
    # No second row for the same (registration, role).
    assert [row for row in session.added if isinstance(row, BalancerRegistrationRole)] == []
