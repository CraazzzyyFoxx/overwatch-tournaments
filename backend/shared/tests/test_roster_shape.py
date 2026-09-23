import copy
import dataclasses
import json
import pickle
import typing

import pytest

from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
from shared.domain.roster_shape import (
    DEFAULT_ROSTER_SHAPE,
    DEFAULT_ROSTER_SLOTS,
    FLEX_SLOT_CODE,
    MAX_TEAM_SIZE,
    MIN_TEAM_SIZE,
    ROSTER_SLOT_CODES,
    RegistrationRoleCode,
    RosterShape,
    RosterShapeError,
    RosterSlotCode,
    parse_roster_slots,
    resolve_roster_shape,
)


def test_slot_codes_are_derived_from_registration_roles() -> None:
    # Asserting the relationship, not the literal: replacing the unpacking with a
    # hardcoded tuple would add a fifth copy of the role vocabulary to the repo,
    # which is exactly the duplication this feature removes.
    assert ROSTER_SLOT_CODES == (*REGISTRATION_ROLE_CODES, FLEX_SLOT_CODE)
    assert FLEX_SLOT_CODE not in REGISTRATION_ROLE_CODES


def test_slot_code_literal_cannot_drift_from_the_tuple() -> None:
    # ``RosterSlotCode`` has to spell the codes out (a Literal cannot be built
    # from a tuple), so this is the guard that keeps the static type and the
    # runtime vocabulary the same thing. The Pydantic export contracts in
    # balancer/parser/tournament-service all type their ``role`` field with it.
    assert typing.get_args(RosterSlotCode) == ROSTER_SLOT_CODES


def test_registration_role_literal_cannot_drift_from_the_tuple() -> None:
    # Same guard as ``RosterSlotCode`` above, for the flex-less variant used by
    # a player's fixed registration/draft role (``HeroClass.slot_code``).
    assert typing.get_args(RegistrationRoleCode) == REGISTRATION_ROLE_CODES


def test_slot_codes_and_defaults_have_the_expected_membership() -> None:
    assert ROSTER_SLOT_CODES == ("tank", "damage", "support", "flex")
    assert FLEX_SLOT_CODE == "flex"
    assert DEFAULT_ROSTER_SLOTS == {"tank": 1, "damage": 2, "support": 2}


def test_team_size_bounds_are_pinned() -> None:
    assert MIN_TEAM_SIZE == 1
    assert MAX_TEAM_SIZE == 12


def test_default_roster_slots_cannot_be_mutated() -> None:
    with pytest.raises(TypeError):
        DEFAULT_ROSTER_SLOTS["flex"] = 99  # type: ignore[index]


def test_default_shape_is_the_parsed_default_slots() -> None:
    assert DEFAULT_ROSTER_SHAPE == parse_roster_slots(DEFAULT_ROSTER_SLOTS)
    assert DEFAULT_ROSTER_SHAPE.slots == {"tank": 1, "damage": 2, "support": 2}
    assert DEFAULT_ROSTER_SHAPE.team_size == 5


def test_parses_overwatch_five_v_five() -> None:
    shape = parse_roster_slots({"tank": 1, "damage": 2, "support": 2})

    assert shape.slots == {"tank": 1, "damage": 2, "support": 2}
    assert shape.team_size == 5
    assert shape.flex_slots == 0
    assert shape.role_slots == {"tank": 1, "damage": 2, "support": 2}
    assert shape.has_role_slots is True
    assert shape.draft_rounds == 4


def test_parses_role_less_roster() -> None:
    shape = parse_roster_slots({"flex": 6})

    assert shape.team_size == 6
    assert shape.flex_slots == 6
    assert shape.role_slots == {}
    assert shape.has_role_slots is False
    assert shape.draft_rounds == 5


def test_parses_hybrid_roster() -> None:
    shape = parse_roster_slots({"tank": 1, "flex": 5})

    assert shape.team_size == 6
    assert shape.flex_slots == 5
    assert shape.role_slots == {"tank": 1}
    assert shape.has_role_slots is True


def test_drops_zero_counts_so_has_role_slots_is_unambiguous() -> None:
    shape = parse_roster_slots({"tank": 0, "damage": 0, "support": 0, "flex": 6})

    assert shape.slots == {"flex": 6}
    assert shape.has_role_slots is False


def test_normalizes_key_order_to_canonical() -> None:
    shape = parse_roster_slots({"flex": 1, "support": 2, "tank": 1})

    assert list(shape.slots) == ["tank", "support", "flex"]
    assert shape.entries == (("tank", 1), ("support", 2), ("flex", 1))


def test_accepts_the_largest_allowed_roster() -> None:
    shape = parse_roster_slots({"flex": MAX_TEAM_SIZE})

    assert shape.team_size == MAX_TEAM_SIZE
    assert shape.draft_rounds == MAX_TEAM_SIZE - 1


def test_accepts_a_single_slot_roster_as_a_one_player_team_format() -> None:
    # A 1v1 tournament is a team format like any other; that it has nothing to
    # draft is the draft's concern, not the shape's.
    shape = parse_roster_slots({"flex": 1})

    assert shape.team_size == MIN_TEAM_SIZE
    assert shape.draft_rounds == 0


def test_slots_returns_a_detached_mutable_copy() -> None:
    shape = parse_roster_slots({"flex": 6})
    dumped = shape.slots
    dumped["tank"] = 1

    assert shape.slots == {"flex": 6}
    assert shape.has_role_slots is False


def test_role_slots_returns_a_detached_mutable_copy() -> None:
    shape = parse_roster_slots({"tank": 1, "flex": 5})
    dumped = shape.role_slots
    dumped["damage"] = 4

    assert shape.role_slots == {"tank": 1}


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (None, "roster_slots_not_a_map"),
        ([("tank", 1)], "roster_slots_not_a_map"),
        ({"healer": 2}, "roster_slots_unknown_code"),
        ({"Tank": 1}, "roster_slots_unknown_code"),
        ({"tank": -1}, "roster_slots_invalid_count"),
        ({"tank": 1.5}, "roster_slots_invalid_count"),
        ({"tank": True}, "roster_slots_invalid_count"),
        ({"tank": "1"}, "roster_slots_invalid_count"),
        ({}, "roster_slots_empty"),
        ({"tank": 0}, "roster_slots_empty"),
        ({"flex": MAX_TEAM_SIZE + 1}, "roster_slots_out_of_range"),
        # Over the limit by sum rather than by any single slot.
        ({"tank": 1, "damage": MAX_TEAM_SIZE}, "roster_slots_out_of_range"),
    ],
)
def test_rejects_invalid_maps_with_machine_readable_codes(raw: object, code: str) -> None:
    with pytest.raises(RosterShapeError) as exc_info:
        parse_roster_slots(raw)

    assert exc_info.value.code == code


@pytest.mark.parametrize(
    ("entries", "code"),
    [
        ((), "roster_slots_empty"),
        ((("healer", 2), ("flex", 2)), "roster_slots_unknown_code"),
        ((("tank", 0), ("flex", 5)), "roster_slots_invalid_count"),
        ((("tank", True), ("flex", 5)), "roster_slots_invalid_count"),
        ((("tank", "1"), ("flex", 5)), "roster_slots_invalid_count"),
        ((("flex", 1), ("tank", 1)), "roster_slots_not_canonical"),
        ((("tank", 1), ("tank", 1)), "roster_slots_not_canonical"),
        ([("tank", 1), ("flex", 1)], "roster_slots_not_canonical"),
        ((("flex", MAX_TEAM_SIZE + 1),), "roster_slots_out_of_range"),
    ],
)
def test_direct_construction_enforces_the_same_invariants(entries: object, code: str) -> None:
    with pytest.raises(RosterShapeError) as exc_info:
        RosterShape(entries=entries)  # type: ignore[arg-type]

    assert exc_info.value.code == code


def test_error_is_a_value_error_so_pydantic_validators_can_catch_it() -> None:
    assert issubclass(RosterShapeError, ValueError)


def test_shape_is_frozen_and_hashable() -> None:
    shape = parse_roster_slots({"flex": 6})

    with pytest.raises(dataclasses.FrozenInstanceError):
        shape.entries = (("tank", 1),)  # type: ignore[misc]
    assert hash(shape) == hash(parse_roster_slots({"flex": 6}))
    assert shape == parse_roster_slots({"flex": 6})


def test_shape_survives_the_serialization_paths_it_travels_through() -> None:
    # A MappingProxyType field passed pyright but blew up at runtime on every one
    # of these; the shape goes through Pydantic into a JSONB column.
    shape = parse_roster_slots({"tank": 1, "flex": 5})

    assert json.loads(json.dumps(shape.slots)) == {"tank": 1, "flex": 5}
    assert json.loads(json.dumps(shape.role_slots)) == {"tank": 1}
    assert copy.deepcopy(shape) == shape
    assert pickle.loads(pickle.dumps(shape)) == shape
    assert dataclasses.asdict(shape) == {"entries": (("tank", 1), ("flex", 5))}
    assert hash(shape) == hash(parse_roster_slots({"tank": 1, "flex": 5}))


def test_tournament_override_wins() -> None:
    shape = resolve_roster_shape({"flex": 6}, {"tank": 1, "damage": 2, "support": 2})

    assert shape.slots == {"flex": 6}


def test_falls_back_to_workspace_default() -> None:
    shape = resolve_roster_shape(None, {"tank": 1, "flex": 5})

    assert shape.slots == {"tank": 1, "flex": 5}


def test_falls_back_to_builtin_default_when_nothing_is_set() -> None:
    shape = resolve_roster_shape(None, None)

    assert shape.slots == {"tank": 1, "damage": 2, "support": 2}


def test_builtin_fallback_returns_the_prebuilt_default_shape() -> None:
    # Identity, not equality: the default is parsed once at import time, so the
    # fallback must hand back that object instead of re-parsing on every call.
    assert resolve_roster_shape(None, None) is DEFAULT_ROSTER_SHAPE


def test_empty_map_at_a_level_means_no_value_not_an_error() -> None:
    # A cleared override must inherit, not blow up the tournament read.
    assert resolve_roster_shape({}, {"flex": 6}).slots == {"flex": 6}
    assert resolve_roster_shape({}, {}) is DEFAULT_ROSTER_SHAPE


def test_invalid_value_at_a_level_still_raises() -> None:
    # Corrupt stored config must surface, not silently degrade to the default.
    with pytest.raises(RosterShapeError) as exc_info:
        resolve_roster_shape({"healer": 6}, None)

    assert exc_info.value.code == "roster_slots_unknown_code"


def test_invalid_workspace_default_raises_even_when_tournament_is_unset() -> None:
    with pytest.raises(RosterShapeError) as exc_info:
        resolve_roster_shape(None, {"flex": MAX_TEAM_SIZE + 1})

    assert exc_info.value.code == "roster_slots_out_of_range"


def test_accepts_an_already_parsed_shape_at_either_level() -> None:
    # Callers holding a RosterShape should not have to unwrap it back into a map.
    shape = parse_roster_slots({"flex": 6})

    assert resolve_roster_shape(shape, None) is shape
    assert resolve_roster_shape(None, shape) is shape


def test_a_falsy_non_mapping_is_rejected_rather_than_skipped() -> None:
    # Only None and an empty mapping mean "no value"; 0, "" and [] are corruption.
    for corrupt in (0, "", [], ()):
        with pytest.raises(RosterShapeError) as exc_info:
            resolve_roster_shape(corrupt, None)
        assert exc_info.value.code == "roster_slots_not_a_map"


def test_the_package_reexports_the_roster_shape_api() -> None:
    # Consumers import from shared.domain, not the module path.
    from shared.domain import DEFAULT_ROSTER_SHAPE as reexported_default
    from shared.domain import resolve_roster_shape as reexported_resolve

    assert reexported_resolve is resolve_roster_shape
    assert reexported_default is DEFAULT_ROSTER_SHAPE
