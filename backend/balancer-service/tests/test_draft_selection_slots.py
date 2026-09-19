"""Slot-vocabulary rules for pick selection.

The draft no longer derives per-role targets from a scalar team size: it fills the
tournament's ``RosterShape``, where a ``flex`` slot accepts anybody. These tests
pin the decision layer (``resolve_pick_slot``, ``team_slot_counts``,
``role_openings``) plus the option-level ``slot_filled`` reason, all of which are
pure and therefore run without Postgres or Redis.

Which roles a seat can fill is no longer stored on the seat: it is the engine's
``PlayerRoster``, handed in as ``rosters`` keyed by ``DraftPlayer.id``. A seat
whose roster the balancer ranks on no role is not pickable at all, which is the
last case below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.core.enums import HERO_TYPE_CLASSES, DraftPickStatus, DraftPlayerStatus, HeroClass  # noqa: E402
from shared.domain.roster import PlayerRoster  # noqa: E402
from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from shared.models.balancer.draft import DraftPick, DraftPlayer  # noqa: E402
from src.domain.draft import (
    feasibility,  # noqa: E402
    rules,  # noqa: E402
)
from tests.factories import roster  # noqa: E402


def _shape(slots: dict[str, int]):
    return parse_roster_slots(slots)


def _code(exc: Exception) -> str:
    return exc.detail[0]["code"]


def _player(
    player_id: int,
    primary: HeroClass,
    *secondary: HeroClass,
    flex: bool = False,
    status: DraftPlayerStatus = DraftPlayerStatus.AVAILABLE,
    team_id: int | None = None,
) -> DraftPlayer:
    """A seat plus the roster the engine would resolve for it.

    The roster rides along on ``player_roster`` (see :func:`_rosters`) because
    the row itself holds no roles: only ``session_id``, ``registration_id`` and
    draft state.
    """
    seat = DraftPlayer(
        id=player_id,
        session_id=1,
        registration_id=player_id,
        status=status.value,
        drafted_by_team_id=team_id,
    )
    seat.player_roster = roster(
        player_id,
        ranks={primary.slot_code: 3000, **{role.slot_code: 2800 for role in secondary}},
        primary=primary.slot_code,
        flex=flex,
    )
    return seat


def _rosters(*players: DraftPlayer) -> dict[int, PlayerRoster]:
    return {player.id: player.player_roster for player in players}


def _roster_of(player: DraftPlayer) -> PlayerRoster:
    return player.player_roster


def _pick(pick_id: int, *, player_id: int, team_id: int, target_role: HeroClass | None) -> DraftPick:
    return DraftPick(
        id=pick_id,
        session_id=1,
        overall_no=pick_id,
        round_no=1,
        pick_in_round=pick_id,
        draft_team_id=team_id,
        status=DraftPickStatus.COMPLETED.value,
        picked_player_id=player_id,
        target_role=target_role.slot_code if target_role else None,
    )


def _eligible(player_id: int, *roles: HeroClass):
    return feasibility.EligiblePlayer(player_id=player_id, playable_roles=frozenset(roles))


def test_a_second_tank_is_legal_while_a_flex_slot_is_open() -> None:
    shape = _shape({"tank": 1, "flex": 5})
    picked_tank = _player(
        1,
        HeroClass.tank,
        status=DraftPlayerStatus.PICKED,
        team_id=10,
    )
    counts = rules.team_slot_counts(
        (picked_tank,),
        (_pick(1, player_id=1, team_id=10, target_role=HeroClass.tank),),
        10,
        shape,
        _rosters(picked_tank),
    )

    assert counts["tank"] == 1
    # The role slot is full, but five flex slots still accept a tank.
    assert rules.role_openings(shape, counts)[HeroClass.tank] == 5

    candidate = _player(2, HeroClass.tank)
    decision = rules.resolve_pick_slot(shape, counts, _roster_of(candidate), HeroClass.tank)

    assert decision.role is HeroClass.tank
    assert decision.recorded_role == "tank"


def test_slot_filled_needs_both_the_role_and_the_flex_capacity_gone() -> None:
    shape = _shape({"tank": 1, "damage": 2, "flex": 1})
    picked = (
        _player(1, HeroClass.tank, status=DraftPlayerStatus.PICKED, team_id=10),
        _player(2, HeroClass.damage, status=DraftPlayerStatus.PICKED, team_id=10),
        _player(3, HeroClass.damage, status=DraftPlayerStatus.PICKED, team_id=10),
    )
    picks = tuple(
        _pick(
            index + 1,
            player_id=player.id,
            team_id=10,
            target_role=_roster_of(player).primary.role,
        )
        for index, player in enumerate(picked)
    )
    counts = rules.team_slot_counts(picked, picks, 10, shape, _rosters(*picked))

    # Tank and DPS role slots are exhausted, the single flex slot is not.
    assert counts == {"tank": 1, "damage": 2, "flex": 0}
    assert rules.role_openings(shape, counts)[HeroClass.tank] == 1
    fourth = _player(4, HeroClass.tank)
    decision = rules.resolve_pick_slot(shape, counts, _roster_of(fourth), HeroClass.tank)
    assert decision.role is HeroClass.tank

    # Spend the flex slot too: now nothing is left for a fourth tank.
    counts_with_flex_used = dict(counts, flex=1)
    assert rules.role_openings(shape, counts_with_flex_used)[HeroClass.tank] == 0
    fifth = _player(5, HeroClass.tank)
    with pytest.raises(Exception) as exc_info:
        rules.resolve_pick_slot(shape, counts_with_flex_used, _roster_of(fifth), HeroClass.tank)

    assert _code(exc_info.value) == "slot_filled"


def test_pick_options_report_slot_filled_only_without_any_remaining_capacity() -> None:
    with_flex = feasibility.evaluate_pick_options(
        team_id=10,
        team_ids=(10,),
        slot_targets={"tank": 1, "flex": 1},
        players=(_eligible(1, HeroClass.tank),),
        assignments=(feasibility.DraftAssignment(player_id=99, team_id=10, slot_code="tank"),),
    )
    without_flex = feasibility.evaluate_pick_options(
        team_id=10,
        team_ids=(10,),
        slot_targets={"tank": 1, "damage": 1},
        players=(_eligible(1, HeroClass.tank),),
        assignments=(feasibility.DraftAssignment(player_id=99, team_id=10, slot_code="tank"),),
    )

    flex_option = next(option for option in with_flex if option.role is HeroClass.tank)
    assert flex_option.reason_code != "slot_filled"
    assert flex_option.is_safe is True

    blocked = next(option for option in without_flex if option.role is HeroClass.tank)
    assert blocked.is_safe is False
    assert blocked.reason_code == "slot_filled"


def test_a_role_less_roster_ignores_the_requested_target_role() -> None:
    shape = _shape({"flex": 6})
    counts = rules.team_slot_counts((), (), 10, shape, {})

    # The player cannot play tank at all, yet the request must not be rejected:
    # a flex-only roster has no role to validate against.
    candidate = _player(1, HeroClass.damage)
    decision = rules.resolve_pick_slot(shape, counts, _roster_of(candidate), HeroClass.tank)

    assert shape.has_role_slots is False
    assert decision.role is HeroClass.damage
    assert decision.recorded_role is None


def test_a_role_slot_roster_keeps_the_existing_target_role_rules() -> None:
    shape = _shape({"tank": 1, "damage": 2, "support": 2})
    counts = rules.team_slot_counts((), (), 10, shape, {})

    flexible = _player(1, HeroClass.damage, HeroClass.tank)
    decision = rules.resolve_pick_slot(shape, counts, _roster_of(flexible), HeroClass.tank)
    assert decision.role is HeroClass.tank
    assert decision.recorded_role == "tank"

    damage_only = _player(2, HeroClass.damage)
    with pytest.raises(Exception) as illegal:
        rules.resolve_pick_slot(shape, counts, _roster_of(damage_only), HeroClass.tank)
    assert _code(illegal.value) == "illegal_role"

    tank = _player(3, HeroClass.tank)
    with pytest.raises(Exception) as filled:
        rules.resolve_pick_slot(shape, dict(counts, tank=1), _roster_of(tank), HeroClass.tank)
    assert _code(filled.value) == "slot_filled"


def test_a_player_the_balancer_ranks_on_no_role_cannot_be_picked() -> None:
    # There is no honest slot for them: the old seeder labelled such a player
    # ``damage`` at rank 0 and autopick took them last. Both the "declared but
    # unranked" roster and a seat with no roster at all must be refused, and the
    # refusal must precede the role/slot checks so the message names the cause.
    shape = _shape({"tank": 1, "damage": 2, "support": 2})
    counts = rules.team_slot_counts((), (), 10, shape, {})
    unranked = roster(7, ranks={"damage": None, "tank": None})

    assert unranked.is_draftable is False
    for candidate in (unranked, None):
        with pytest.raises(Exception) as exc_info:
            rules.resolve_pick_slot(shape, counts, candidate, HeroClass.damage)
        assert _code(exc_info.value) == "player_unranked"

    # ... and a role-less shape, where every role check is skipped, is no escape.
    with pytest.raises(Exception) as flex_error:
        rules.resolve_pick_slot(_shape({"flex": 6}), {"flex": 0}, unranked, None)
    assert _code(flex_error.value) == "player_unranked"


def test_team_slot_counts_fill_role_slots_first_and_flex_with_the_remainder() -> None:
    shape = _shape({"tank": 1, "damage": 1, "flex": 2})
    captain = _player(1, HeroClass.support, status=DraftPlayerStatus.PICKED, team_id=10)
    off_role = _player(2, HeroClass.support, HeroClass.damage, status=DraftPlayerStatus.PICKED, team_id=10)
    tank = _player(3, HeroClass.tank, status=DraftPlayerStatus.PICKED, team_id=10)
    other_team = _player(4, HeroClass.tank, status=DraftPlayerStatus.PICKED, team_id=20)
    available = _player(5, HeroClass.tank)
    picks = (
        # The frozen target_role wins over the roster's lead role.
        _pick(2, player_id=2, team_id=10, target_role=HeroClass.damage),
        _pick(3, player_id=3, team_id=10, target_role=None),
        _pick(4, player_id=4, team_id=20, target_role=HeroClass.tank),
    )
    players = (captain, off_role, tank, other_team, available)

    counts = rules.team_slot_counts(players, picks, 10, shape, _rosters(*players))

    # Three picked players on team 10: tank and damage role slots take one each, and
    # the support captain has no role slot to land in, so flex absorbs them.
    assert counts == {"tank": 1, "damage": 1, "flex": 1}
    assert rules.role_openings(shape, counts) == {
        HeroClass.tank: 1,
        HeroClass.damage: 1,
        HeroClass.support: 1,
    }


def test_a_picked_seat_without_a_roster_still_occupies_a_flex_slot() -> None:
    # A registration soft-deleted mid-draft resolves to no roster at all. The
    # player is already on the team, so their slot must keep counting; dropping
    # them would hand the captain a phantom extra pick.
    shape = _shape({"tank": 1, "flex": 1})
    picked = _player(1, HeroClass.tank, status=DraftPlayerStatus.PICKED, team_id=10)

    counts = rules.team_slot_counts(
        (picked,),
        (_pick(1, player_id=1, team_id=10, target_role=None),),
        10,
        shape,
        {},
    )

    assert counts == {"tank": 0, "flex": 1}


def test_an_overfilled_role_spills_into_flex_instead_of_inflating_the_role_count() -> None:
    shape = _shape({"tank": 1, "flex": 2})
    picked = tuple(_player(index, HeroClass.tank, status=DraftPlayerStatus.PICKED, team_id=10) for index in (1, 2, 3))
    picks = tuple(_pick(player.id, player_id=player.id, team_id=10, target_role=HeroClass.tank) for player in picked)

    counts = rules.team_slot_counts(picked, picks, 10, shape, _rosters(*picked))

    assert counts == {"tank": 1, "flex": 2}
    assert rules.role_openings(shape, counts) == dict.fromkeys(HERO_TYPE_CLASSES, 0)
