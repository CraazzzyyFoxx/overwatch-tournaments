from __future__ import annotations

import importlib
import sys
from pathlib import Path
from time import perf_counter

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.core.enums import (  # noqa: E402
    HERO_TYPE_CLASSES,
    DraftPickStatus,
    DraftPlayerStatus,
    HeroClass,
)
from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftTeam  # noqa: E402
from src.domain.draft import rules  # noqa: E402
from tests.factories import roster  # noqa: E402


def _load_feature_modules():
    try:
        matching = importlib.import_module("src.domain.matching")
        feasibility = importlib.import_module("src.domain.draft.feasibility")
    except ModuleNotFoundError as exc:
        pytest.fail(f"draft feasibility feature is not implemented: {exc}")
    return matching, feasibility


def _player(feasibility, player_id: int, *roles: HeroClass):
    return feasibility.EligiblePlayer(player_id=player_id, playable_roles=frozenset(roles))


def _assignment(feasibility, player_id: int, team_id: int, slot_code: str):
    return feasibility.DraftAssignment(player_id=player_id, team_id=team_id, slot_code=slot_code)


def _shape(slots: dict[str, int]):
    return parse_roster_slots(slots)


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
        slot_targets={"tank": 1, "damage": 1, "support": 1},
        players=[
            _player(feasibility, 1, HeroClass.tank),
            _player(feasibility, 2, HeroClass.damage),
        ],
    )

    preflight_error = rules.role_shortage_error(report)
    pick_error = rules.unsafe_pick_error(report)

    assert _error_code(preflight_error) == "role_shortage"
    assert "support" in _error_message(preflight_error)
    assert _error_code(pick_error) == "pick_makes_draft_infeasible"
    assert "support" in _error_message(pick_error)


def test_insufficient_pool_reports_unmatched_slot() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, HeroClass.tank),
        _player(feasibility, 2, HeroClass.tank),
        _player(feasibility, 3, HeroClass.damage),
        _player(feasibility, 4, HeroClass.damage),
        _player(feasibility, 5, HeroClass.support),
    ]

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10, 20),
        slot_targets={"tank": 1, "damage": 1, "support": 1},
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
        _player(feasibility, 1, HeroClass.tank, HeroClass.damage),
        _player(feasibility, 2, HeroClass.tank, HeroClass.damage),
        _player(feasibility, 3, HeroClass.support),
        _player(feasibility, 4, HeroClass.support),
        _player(feasibility, 5, HeroClass.support),
        _player(feasibility, 6, HeroClass.support),
    ]

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10, 20),
        slot_targets={"tank": 1, "damage": 1, "support": 1},
        players=players,
    )

    assert report.is_feasible is False
    assert report.matched_slots == 4
    assert len(report.unmatched_slots) == 2
    assert {slot.slot_code for slot in report.unmatched_slots} <= {"tank", "damage"}
    assert report.blocking_player_ids == (1, 2)


def test_one_flex_player_cannot_cover_two_critical_roles() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, HeroClass.tank, HeroClass.damage, HeroClass.support),
        _player(feasibility, 2, HeroClass.damage),
        _player(feasibility, 3, HeroClass.damage),
    ]

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10,),
        slot_targets={"tank": 1, "damage": 1, "support": 1},
        players=players,
    )

    assert report.is_feasible is False
    assert report.matched_slots == 2
    assert report.blocking_player_ids == (1,)


def test_hypothetical_pick_can_be_locally_legal_but_globally_unsafe() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, HeroClass.support),
        _player(feasibility, 2, HeroClass.damage, HeroClass.support),
        _player(feasibility, 3, HeroClass.damage),
        _player(feasibility, 4, HeroClass.damage),
    ]
    assignments = (
        _assignment(feasibility, 101, 10, HeroClass.tank.slot_code),
        _assignment(feasibility, 102, 20, HeroClass.tank.slot_code),
    )
    common = {
        "team_ids": (10, 20),
        "slot_targets": {"tank": 1, "damage": 1, "support": 1},
        "players": players,
        "assignments": assignments,
    }

    safe = feasibility.analyze_draft_feasibility(
        **common,
        hypothetical=_assignment(feasibility, 1, 10, "support"),
    )
    unsafe = feasibility.analyze_draft_feasibility(
        **common,
        hypothetical=_assignment(feasibility, 2, 10, "damage"),
    )

    assert safe.is_feasible is True
    assert unsafe.is_feasible is False
    assert {slot.slot_code for slot in unsafe.unmatched_slots} == {"support"}


def test_pick_options_explain_safe_slot_filled_and_role_shortage_states() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, HeroClass.support),
        _player(feasibility, 2, HeroClass.damage, HeroClass.support),
        _player(feasibility, 3, HeroClass.damage),
        _player(feasibility, 4, HeroClass.damage),
    ]
    assignments = (
        _assignment(feasibility, 101, 10, HeroClass.tank.slot_code),
        _assignment(feasibility, 102, 20, HeroClass.tank.slot_code),
    )

    options = feasibility.evaluate_pick_options(
        team_id=10,
        team_ids=(10, 20),
        slot_targets={"tank": 1, "damage": 1, "support": 1},
        players=players,
        assignments=assignments,
    )
    by_key = {(option.player_id, option.role): option for option in options}

    assert by_key[(1, HeroClass.support)].is_safe is True
    assert by_key[(2, HeroClass.support)].is_safe is True
    assert by_key[(2, HeroClass.damage)].is_safe is False
    assert by_key[(2, HeroClass.damage)].reason_code == "role_shortage"
    assert by_key[(2, HeroClass.damage)].unmatched_slots


def test_full_coverage_with_extra_players_is_feasible() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, HeroClass.tank),
        _player(feasibility, 2, HeroClass.damage),
        _player(feasibility, 3, HeroClass.support),
        _player(feasibility, 4, HeroClass.tank, HeroClass.damage, HeroClass.support),
    ]

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10,),
        slot_targets={"tank": 1, "damage": 1, "support": 1},
        players=players,
    )

    assert report.is_feasible is True
    assert report.matched_slots == 3
    assert report.unmatched_slots == ()


def test_build_state_reads_roles_off_the_engine_rosters_and_the_pick_target_role() -> None:
    _, feasibility = _load_feature_modules()
    team = DraftTeam(id=10, session_id=1, name="Alpha", draft_position=1)
    captain = DraftPlayer(
        id=101,
        session_id=1,
        registration_id=201,
        status=DraftPlayerStatus.PICKED.value,
        is_captain=True,
        drafted_by_team_id=10,
    )
    picked = DraftPlayer(
        id=102,
        session_id=1,
        registration_id=202,
        status=DraftPlayerStatus.PICKED.value,
        drafted_by_team_id=10,
    )
    flex = DraftPlayer(
        id=103,
        session_id=1,
        registration_id=203,
        status=DraftPlayerStatus.AVAILABLE.value,
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
        target_role=HeroClass.support.slot_code,
    )

    state = feasibility.build_feasibility_state(
        shape=_shape({"tank": 1, "damage": 2, "support": 2}),
        teams=(team,),
        players=(captain, picked, flex),
        picks=(pick,),
        rosters={
            101: roster(201, ranks={"tank": 3100}),
            # Drafted onto SUPPORT even though DPS leads: the frozen target_role
            # names the slot they occupy.
            102: roster(202, ranks={"damage": 4000, "support": 2800}),
            103: roster(203, ranks={"damage": 3000, "tank": 3000, "support": 3000}, flex=True),
        },
    )

    assert state.team_ids == (10,)
    # The explicit 5v5 shape must reproduce exactly what the deleted
    # role_targets_for_team_size(5) used to derive from the scalar team size.
    assert state.slot_targets == {"tank": 1, "damage": 2, "support": 2}
    assert state.assignments == (
        feasibility.DraftAssignment(player_id=101, team_id=10, slot_code="tank"),
        feasibility.DraftAssignment(player_id=102, team_id=10, slot_code="support"),
    )
    assert state.players == (feasibility.EligiblePlayer(player_id=103, playable_roles=frozenset(HERO_TYPE_CLASSES)),)


def test_build_state_leaves_an_unranked_available_player_out_of_the_eligible_set() -> None:
    # A registration the balancer ranks on no role contributes NO eligibility:
    # that is what makes the draft report the shortage instead of quietly
    # picking them at rank 0. A seat the engine could not resolve at all (a
    # soft-deleted registration) counts the same way.
    _, feasibility = _load_feature_modules()
    team = DraftTeam(id=10, session_id=1, name="Alpha", draft_position=1)
    unranked = DraftPlayer(id=101, session_id=1, registration_id=201, status=DraftPlayerStatus.AVAILABLE.value)
    rosterless = DraftPlayer(id=102, session_id=1, registration_id=202, status=DraftPlayerStatus.AVAILABLE.value)
    ranked = DraftPlayer(id=103, session_id=1, registration_id=203, status=DraftPlayerStatus.AVAILABLE.value)

    state = feasibility.build_feasibility_state(
        shape=_shape({"tank": 1, "support": 1}),
        teams=(team,),
        players=(unranked, rosterless, ranked),
        picks=(),
        rosters={
            101: roster(201, ranks={"tank": None, "support": None}),
            103: roster(203, ranks={"tank": 3000}),
        },
    )
    report = feasibility.analyze_draft_feasibility(
        team_ids=state.team_ids,
        slot_targets=state.slot_targets,
        players=state.players,
        assignments=state.assignments,
    )

    assert [player.player_id for player in state.players] == [103]
    # Two role slots, one usable player: the shortage is REPORTED, not papered
    # over by two rank-less bodies.
    assert report.is_feasible is False
    assert [slot.slot_code for slot in report.unmatched_slots] == ["support"]
    assert [(d.slot_code, d.unmatched_slots, d.eligible_players) for d in report.slot_deficits] == [("support", 1, 0)]


def test_options_for_supported_scale_complete_under_latency_budget() -> None:
    _, feasibility = _load_feature_modules()
    team_ids = tuple(range(1, 13))
    assignments = tuple(_assignment(feasibility, 10_000 + team_id, team_id, "tank") for team_id in team_ids)
    players = [
        _player(
            feasibility,
            player_id,
            *(HeroClass.damage, HeroClass.support)
            if player_id % 5 == 0
            else ((HeroClass.damage,) if player_id % 2 == 0 else (HeroClass.support,)),
        )
        for player_id in range(1, 151)
    ]
    durations: list[float] = []

    for _ in range(5):
        started = perf_counter()
        options = feasibility.evaluate_pick_options(
            team_id=1,
            team_ids=team_ids,
            slot_targets={"tank": 1, "damage": 2, "support": 2},
            players=players,
            assignments=assignments,
        )
        durations.append(perf_counter() - started)

    assert options
    assert sorted(durations)[-2] < 0.300


def test_flex_slot_accepts_a_player_who_cannot_play_the_role_slot() -> None:
    _, feasibility = _load_feature_modules()

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10,),
        slot_targets={"tank": 1, "flex": 1},
        players=[
            _player(feasibility, 1, HeroClass.tank),
            _player(feasibility, 2, HeroClass.support),
        ],
    )

    assert report.is_feasible is True
    assert report.total_open_slots == 2
    assert report.matched_slots == 2
    assert report.unmatched_slots == ()


def test_an_all_flex_roster_is_feasible_for_any_declared_roles() -> None:
    _, feasibility = _load_feature_modules()
    players = [
        _player(feasibility, 1, HeroClass.support),
        _player(feasibility, 2, HeroClass.support),
        _player(feasibility, 3, HeroClass.support),
        _player(feasibility, 4, HeroClass.tank),
        _player(feasibility, 5, HeroClass.tank),
        _player(feasibility, 6, HeroClass.damage),
    ]

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10,),
        slot_targets={"flex": 6},
        players=players,
    )

    assert report.is_feasible is True
    assert report.matched_slots == 6
    assert report.unmatched_slots == ()


def test_flex_slot_never_absorbs_the_deficit_of_an_unfillable_role_slot() -> None:
    _, feasibility = _load_feature_modules()

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10,),
        slot_targets={"tank": 1, "flex": 1},
        players=[
            _player(feasibility, 1, HeroClass.support),
            _player(feasibility, 2, HeroClass.support),
        ],
    )

    assert report.is_feasible is False
    assert report.matched_slots == 1
    assert [slot.slot_code for slot in report.unmatched_slots] == ["tank"]
    assert [(d.slot_code, d.unmatched_slots, d.eligible_players) for d in report.slot_deficits] == [("tank", 1, 0)]


def test_player_level_flex_still_covers_a_role_slot() -> None:
    _, feasibility = _load_feature_modules()
    # A full-flex REGISTRATION ("plays anything") and a flex *slot* ("takes
    # anyone") are independent axes; a flex player must still fill role slots.
    flex_player = DraftPlayer(
        id=103,
        session_id=1,
        registration_id=203,
        status=DraftPlayerStatus.AVAILABLE.value,
    )

    state = feasibility.build_feasibility_state(
        shape=_shape({"tank": 1, "support": 1}),
        teams=(DraftTeam(id=10, session_id=1, name="Alpha", draft_position=1),),
        players=(flex_player,),
        picks=(),
        rosters={103: roster(203, ranks={"damage": 3000, "tank": 3000, "support": 3000}, flex=True)},
    )
    report = feasibility.analyze_draft_feasibility(
        team_ids=state.team_ids,
        slot_targets=state.slot_targets,
        players=state.players,
        assignments=state.assignments,
    )

    assert state.players[0].playable_roles == frozenset(HERO_TYPE_CLASSES)
    # Two role slots, one player: the tank slot is filled, support is left open.
    assert report.matched_slots == 1
    assert [slot.slot_code for slot in report.unmatched_slots] == ["support"]


def test_a_taken_flex_slot_consumes_flex_capacity_not_role_capacity() -> None:
    _, feasibility = _load_feature_modules()
    slot_targets = {"tank": 1, "flex": 1}
    players = [_player(feasibility, 1, HeroClass.support)]

    with_flex_taken = feasibility.analyze_draft_feasibility(
        team_ids=(10,),
        slot_targets=slot_targets,
        players=players,
        assignments=(_assignment(feasibility, 99, 10, "flex"),),
    )
    with_tank_taken = feasibility.analyze_draft_feasibility(
        team_ids=(10,),
        slot_targets=slot_targets,
        players=players,
        assignments=(_assignment(feasibility, 99, 10, "tank"),),
    )

    # Flex taken -> the tank slot is what remains, and a support cannot fill it.
    assert with_flex_taken.is_feasible is False
    assert [slot.slot_code for slot in with_flex_taken.unmatched_slots] == ["tank"]
    # Tank taken -> only the flex slot remains, which accepts the support.
    assert with_tank_taken.is_feasible is True
    assert with_tank_taken.matched_slots == 1


def test_a_picked_player_spills_into_flex_once_the_role_slot_is_full() -> None:
    _, feasibility = _load_feature_modules()
    shape = _shape({"tank": 1, "flex": 1})

    report = feasibility.analyze_draft_feasibility(
        team_ids=(10,),
        slot_targets=shape.slots,
        players=(),
        assignments=(
            _assignment(feasibility, 1, 10, "tank"),
            _assignment(feasibility, 2, 10, "tank"),
        ),
    )

    assert report.is_feasible is True
    assert report.total_open_slots == 0
    assert report.reason_code is None
