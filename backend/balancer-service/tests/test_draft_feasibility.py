from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from time import perf_counter

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

from shared.core.enums import (  # noqa: E402
    DraftPickStatus,
    DraftPlayerStatus,
    DraftRole,  # noqa: E402
)
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftPlayerRole, DraftTeam  # noqa: E402
from src.services.draft import lifecycle, selection  # noqa: E402


def _load_feature_modules():
    try:
        matching = importlib.import_module("src.services.role_matching")
        feasibility = importlib.import_module("src.services.draft.feasibility")
    except ModuleNotFoundError as exc:
        pytest.fail(f"draft feasibility feature is not implemented: {exc}")
    return matching, feasibility


def _player(feasibility, player_id: int, *roles: DraftRole):
    return feasibility.EligiblePlayer(player_id=player_id, playable_roles=frozenset(roles))


def _assignment(feasibility, player_id: int, team_id: int, role: DraftRole):
    return feasibility.DraftAssignment(player_id=player_id, team_id=team_id, role=role)


def _error_code(exc: Exception) -> str:
    return exc.detail[0]["code"]


def _error_message(exc: Exception) -> str:
    return exc.detail[0]["msg"]


def test_generic_matcher_reassigns_an_existing_owner_to_complete_the_matching() -> None:
    matching, _ = _load_feature_modules()

    result = matching.maximum_bipartite_matching(
        candidates=("flex", "tank"),
        slots=("tank-slot", "support-slot"),
        eligible_slots={
            "flex": ("tank-slot", "support-slot"),
            "tank": ("tank-slot",),
        },
    )

    assert result.matched_count == 2
    assert result.unmatched_slots == ()
    assert result.slot_to_candidate == {
        "tank-slot": "tank",
        "support-slot": "flex",
    }


def test_service_errors_expose_contract_codes_and_role_deficit_details() -> None:
    _, feasibility = _load_feature_modules()
    report = feasibility.analyze_draft_feasibility(
        team_ids=[10],
        role_targets={DraftRole.TANK: 1, DraftRole.DPS: 1, DraftRole.SUPPORT: 1},
        players=[
            _player(feasibility, 1, DraftRole.TANK),
            _player(feasibility, 2, DraftRole.DPS),
        ],
    )

    preflight_error = lifecycle._role_shortage_error(report)
    pick_error = selection._unsafe_pick_error(report)

    assert _error_code(preflight_error) == "role_shortage"
    assert "support" in _error_message(preflight_error)
    assert _error_code(pick_error) == "pick_makes_draft_infeasible"
    assert "support" in _error_message(pick_error)


def test_insufficient_pool_reports_unmatched_slot() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, DraftRole.TANK),
        _player(feasibility, 2, DraftRole.TANK),
        _player(feasibility, 3, DraftRole.DPS),
        _player(feasibility, 4, DraftRole.DPS),
        _player(feasibility, 5, DraftRole.SUPPORT),
    ]

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10, 20),
        role_targets={DraftRole.TANK: 1, DraftRole.DPS: 1, DraftRole.SUPPORT: 1},
        players=players,
    )

    assert report.is_feasible is False
    assert report.total_open_slots == 6
    assert report.matched_slots == 5
    assert len(report.unmatched_slots) == 1


def test_hall_deficit_is_detected_when_each_role_counter_looks_sufficient() -> None:
    _, feasibility = _load_feature_modules()
    # Tank and DPS each show supply=2, but it is the same two flex players. Four
    # distinct Tank/DPS slots therefore cannot be filled simultaneously.
    players = [
        _player(feasibility, 1, DraftRole.TANK, DraftRole.DPS),
        _player(feasibility, 2, DraftRole.TANK, DraftRole.DPS),
        _player(feasibility, 3, DraftRole.SUPPORT),
        _player(feasibility, 4, DraftRole.SUPPORT),
        _player(feasibility, 5, DraftRole.SUPPORT),
        _player(feasibility, 6, DraftRole.SUPPORT),
    ]

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10, 20),
        role_targets={DraftRole.TANK: 1, DraftRole.DPS: 1, DraftRole.SUPPORT: 1},
        players=players,
    )

    assert report.is_feasible is False
    assert report.matched_slots == 4
    assert len(report.unmatched_slots) == 2
    assert {slot.role for slot in report.unmatched_slots} <= {DraftRole.TANK, DraftRole.DPS}
    assert report.blocking_player_ids == (1, 2)


def test_one_flex_player_cannot_cover_two_critical_roles() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, DraftRole.TANK, DraftRole.DPS, DraftRole.SUPPORT),
        _player(feasibility, 2, DraftRole.DPS),
        _player(feasibility, 3, DraftRole.DPS),
    ]

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10,),
        role_targets={DraftRole.TANK: 1, DraftRole.DPS: 1, DraftRole.SUPPORT: 1},
        players=players,
    )

    assert report.is_feasible is False
    assert report.matched_slots == 2
    assert report.blocking_player_ids == (1,)


def test_hypothetical_pick_can_be_locally_legal_but_globally_unsafe() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, DraftRole.SUPPORT),
        _player(feasibility, 2, DraftRole.DPS, DraftRole.SUPPORT),
        _player(feasibility, 3, DraftRole.DPS),
        _player(feasibility, 4, DraftRole.DPS),
    ]
    assignments = (
        _assignment(feasibility, 101, 10, DraftRole.TANK),
        _assignment(feasibility, 102, 20, DraftRole.TANK),
    )
    common = {
        "team_ids": (10, 20),
        "role_targets": {DraftRole.TANK: 1, DraftRole.DPS: 1, DraftRole.SUPPORT: 1},
        "players": players,
        "assignments": assignments,
    }

    safe = feasibility.analyze_draft_feasibility(
        **common,
        hypothetical=_assignment(feasibility, 1, 10, DraftRole.SUPPORT),
    )
    unsafe = feasibility.analyze_draft_feasibility(
        **common,
        hypothetical=_assignment(feasibility, 2, 10, DraftRole.DPS),
    )

    assert safe.is_feasible is True
    assert unsafe.is_feasible is False
    assert {slot.role for slot in unsafe.unmatched_slots} == {DraftRole.SUPPORT}


def test_pick_options_explain_safe_role_filled_and_role_shortage_states() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, DraftRole.SUPPORT),
        _player(feasibility, 2, DraftRole.DPS, DraftRole.SUPPORT),
        _player(feasibility, 3, DraftRole.DPS),
        _player(feasibility, 4, DraftRole.DPS),
    ]
    assignments = (
        _assignment(feasibility, 101, 10, DraftRole.TANK),
        _assignment(feasibility, 102, 20, DraftRole.TANK),
    )

    options = feasibility.evaluate_pick_options(
        team_id=10,
        team_ids=(10, 20),
        role_targets={DraftRole.TANK: 1, DraftRole.DPS: 1, DraftRole.SUPPORT: 1},
        players=players,
        assignments=assignments,
    )
    by_key = {(option.player_id, option.role): option for option in options}

    assert by_key[(1, DraftRole.SUPPORT)].is_safe is True
    assert by_key[(2, DraftRole.SUPPORT)].is_safe is True
    assert by_key[(2, DraftRole.DPS)].is_safe is False
    assert by_key[(2, DraftRole.DPS)].reason_code == "role_shortage"
    assert by_key[(2, DraftRole.DPS)].unmatched_slots


def test_full_coverage_with_extra_players_is_feasible() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, DraftRole.TANK),
        _player(feasibility, 2, DraftRole.DPS),
        _player(feasibility, 3, DraftRole.SUPPORT),
        _player(feasibility, 4, DraftRole.TANK, DraftRole.DPS, DraftRole.SUPPORT),
    ]

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10,),
        role_targets={DraftRole.TANK: 1, DraftRole.DPS: 1, DraftRole.SUPPORT: 1},
        players=players,
    )

    assert report.is_feasible is True
    assert report.matched_slots == 3
    assert report.unmatched_slots == ()


def test_build_state_uses_captain_primary_role_pick_target_role_and_flex_semantics() -> None:
    _, feasibility = _load_feature_modules()
    team = DraftTeam(id=10, session_id=1, name="Alpha", draft_position=1)
    captain = DraftPlayer(
        id=101,
        session_id=1,
        primary_role=DraftRole.TANK.value,
        status=DraftPlayerStatus.PICKED.value,
        is_captain=True,
        drafted_by_team_id=10,
        roles=[DraftPlayerRole(role=DraftRole.TANK.value, priority=0)],
    )
    picked = DraftPlayer(
        id=102,
        session_id=1,
        primary_role=DraftRole.DPS.value,
        status=DraftPlayerStatus.PICKED.value,
        drafted_by_team_id=10,
        roles=[
            DraftPlayerRole(role=DraftRole.DPS.value, priority=0),
            DraftPlayerRole(role=DraftRole.SUPPORT.value, is_secondary=True, priority=1),
        ],
    )
    flex = DraftPlayer(
        id=103,
        session_id=1,
        primary_role=DraftRole.DPS.value,
        status=DraftPlayerStatus.AVAILABLE.value,
        is_flex=True,
        roles=[DraftPlayerRole(role=DraftRole.DPS.value, priority=0)],
    )
    pick = DraftPick(
        id=1001,
        session_id=1,
        overall_no=1,
        round_no=1,
        pick_in_round=1,
        draft_team_id=10,
        status=DraftPickStatus.COMPLETED.value,
        picked_player_id=102,
        target_role=DraftRole.SUPPORT.value,
    )

    state = feasibility.build_feasibility_state(
        team_size=5,
        teams=(team,),
        players=(captain, picked, flex),
        picks=(pick,),
    )

    assert state.team_ids == (10,)
    assert state.assignments == (
        feasibility.DraftAssignment(player_id=101, team_id=10, role=DraftRole.TANK),
        feasibility.DraftAssignment(player_id=102, team_id=10, role=DraftRole.SUPPORT),
    )
    assert state.players == (
        feasibility.EligiblePlayer(player_id=103, playable_roles=frozenset(DraftRole)),
    )


def test_options_for_supported_scale_complete_under_latency_budget() -> None:
    _, feasibility = _load_feature_modules()
    team_ids = tuple(range(1, 13))
    assignments = tuple(
        _assignment(feasibility, 10_000 + team_id, team_id, DraftRole.TANK)
        for team_id in team_ids
    )
    players = [
        _player(
            feasibility,
            player_id,
            *(DraftRole.DPS, DraftRole.SUPPORT)
            if player_id % 5 == 0
            else ((DraftRole.DPS,) if player_id % 2 == 0 else (DraftRole.SUPPORT,)),
        )
        for player_id in range(1, 151)
    ]
    durations: list[float] = []

    for _ in range(5):
        started = perf_counter()
        options = feasibility.evaluate_pick_options(
            team_id=1,
            team_ids=team_ids,
            role_targets={DraftRole.TANK: 1, DraftRole.DPS: 2, DraftRole.SUPPORT: 2},
            players=players,
            assignments=assignments,
        )
        durations.append(perf_counter() - started)

    assert options
    assert sorted(durations)[-2] < 0.300
