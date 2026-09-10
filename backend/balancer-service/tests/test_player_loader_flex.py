"""Flex slots at the balancer input boundary.

A roster shape may contain ``flex`` slots, up to and including the role-less
``{"flex": N}`` roster. The mask handed to the algorithm is that shape, so
``parse_player_node`` has to answer a question it never had to answer before:
what rating does a player bring to a slot that has no role?

Answer: the best rating he actually has. It is the same "ready to play
anything" policy the roster engine applies for every-role tournaments
(``PlayerRoster.best_rank``, pinned by ``test_forced_flex_parity.py`` against
``docs/superpowers/fixtures/forced-flex-eff-rank.json``), so both halves of the
product agree on what a flex player is worth.

Without the synthesis every player is dropped (no role line resolves into a
flex-only mask, ``ratings`` stays empty, ``parse_player_node`` returns
``None``) and the Rust solver rejects the request with "player count must equal
total roster slots" — see ``native/tournament_balancer/src/context.rs`` line 41.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from shared.domain.roster_shape import DEFAULT_ROSTER_SLOTS, FLEX_SLOT_CODE, parse_roster_slots  # noqa: E402
from src.domain.balancer.entities import Team  # noqa: E402
from src.domain.balancer.moo_backend import _serialize_native_request  # noqa: E402
from src.domain.balancer.player_loader import (  # noqa: E402
    load_players_from_dict,
    parse_player_node,
)
from src.domain.balancer.result_serializer import teams_to_json  # noqa: E402
from src.domain.balancer.runtime import _prepare_balance_context, balance_teams  # noqa: E402
from src.services.balancer.config.defaults import AlgorithmConfig  # noqa: E402
from src.services.balancer.config.presets import ConfigPresets  # noqa: E402
from src.services.balancer.config.provider import EDITABLE_CONFIG_FIELD_KEYS  # noqa: E402
from src.services.balancer.config.public_contract import PUBLIC_CONFIG_KEYS  # noqa: E402

FLEX_ONLY_MASK = {FLEX_SLOT_CODE: 6}
ROLE_MASK = {"tank": 1, "dps": 2, "support": 2}
LEGACY_ROLE_MASK = {"Tank": 1, "Damage": 2, "Support": 2}


def _class(rank: int, priority: int, *, is_active: bool = True, subtype: str = "") -> dict[str, Any]:
    node: dict[str, Any] = {"isActive": is_active, "rank": rank, "priority": priority}
    if subtype:
        node["subtype"] = subtype
    return node


def _node(name: str, classes: dict[str, Any], *, is_full_flex: bool = False, must_play: bool = False) -> dict[str, Any]:
    return {
        "identity": {"name": name, "isFullFlex": is_full_flex, "mustPlay": must_play},
        "stats": {"classes": classes},
    }


# ---------------------------------------------------------------------------
# 1-3. The flex-only mask: nobody is dropped, flex carries the best rating
# ---------------------------------------------------------------------------


def _tank_and_support_player():
    # Support is the stronger role but the lower priority, so a "max, not
    # primary" policy is observable: 3100 rather than 2600.
    player = parse_player_node(
        "u-1",
        _node("Tank And Support", {"Tank": _class(2600, 0), "Support": _class(3100, 1)}),
        FLEX_ONLY_MASK,
    )
    assert player is not None, "a flex slot accepts anyone — the player must survive parsing"
    return player


def test_flex_only_mask_keeps_the_player_and_synthesizes_the_best_rank() -> None:
    player = _tank_and_support_player()

    assert player.ratings[FLEX_SLOT_CODE] == 3100
    # A flex slot is not a preference: nothing the player did not declare
    # appears in their role order, so ``primary_role`` stays honest.
    assert FLEX_SLOT_CODE not in player.preferences
    assert player.primary_role is None


def test_flex_slot_costs_no_discomfort() -> None:
    # entities.py prices a playable flex slot at 0 explicitly -- it is a slot
    # with no role, so nobody is out of place on it.
    assert _tank_and_support_player().discomfort_map[FLEX_SLOT_CODE] == 0


def test_role_ratings_survive_a_mask_without_role_slots() -> None:
    # ``all_ratings`` in the saved balance is the admin panel's view of what a
    # player can do; collapsing him to a single flex number would erase it.
    ratings = _tank_and_support_player().ratings

    assert ratings == {"tank": 2600, "support": 3100, FLEX_SLOT_CODE: 3100}


# ---------------------------------------------------------------------------
# 4. Hybrid roster: some role slots, some flex slots
# ---------------------------------------------------------------------------


def test_hybrid_mask_carries_both_the_role_rating_and_the_flex_rating() -> None:
    player = parse_player_node(
        "u-2",
        _node("Hybrid", {"Tank": _class(2600, 1), "Support": _class(3100, 0)}),
        {"tank": 1, FLEX_SLOT_CODE: 5},
    )

    assert player is not None
    assert player.ratings["tank"] == 2600
    assert player.ratings[FLEX_SLOT_CODE] == 3100
    # A flex slot is never a compromise, and the player's own role order is
    # untouched by the roster fielding one.
    assert player.discomfort_map[FLEX_SLOT_CODE] == 0
    assert player.preferences == ["tank"]
    assert player.primary_role == "tank"


# ---------------------------------------------------------------------------
# 5. Nothing to synthesize from
# ---------------------------------------------------------------------------


def test_player_without_a_single_ranked_active_role_is_still_dropped() -> None:
    node = _node(
        "Empty",
        {
            "Tank": _class(2600, 0, is_active=False),
            "Support": _class(0, 1),
        },
    )

    assert parse_player_node("u-3", node, FLEX_ONLY_MASK) is None


# ---------------------------------------------------------------------------
# 6. A mask without flex behaves exactly as before
# ---------------------------------------------------------------------------


def test_mask_without_flex_is_unchanged() -> None:
    player = parse_player_node(
        "u-4",
        _node(
            "Classic",
            {
                "Tank": _class(2600, 1),
                "Damage": _class(2900, 0, subtype="hitscan"),
                "Support": _class(3100, 2),
            },
        ),
        ROLE_MASK,
    )

    assert player is not None
    assert FLEX_SLOT_CODE not in player.ratings
    assert FLEX_SLOT_CODE not in player.discomfort_map
    assert player.ratings == {"tank": 2600, "dps": 2900, "support": 3100}
    assert player.preferences == ["dps", "tank", "support"]
    assert player.subclasses == {"dps": "hitscan"}
    assert player.discomfort_map == {"dps": 0, "tank": 100, "support": 200}


# ---------------------------------------------------------------------------
# 7. A flex assignment is not an off-role assignment
# ---------------------------------------------------------------------------


def test_flex_assignment_is_not_counted_as_off_role() -> None:
    mask = {FLEX_SLOT_CODE: 2}
    teams = []
    for team_index, ranks in enumerate(((3100, 2600), (3000, 2700)), start=1):
        team = Team(team_index, mask)
        for player_index, rank in enumerate(ranks):
            player = parse_player_node(
                f"u-{team_index}-{player_index}",
                _node(f"P{team_index}{player_index}", {"Tank": _class(rank, 0)}),
                mask,
            )
            assert player is not None
            team.add_player(FLEX_SLOT_CODE, player)
        teams.append(team)

    result = teams_to_json(teams, mask)

    assert result["statistics"]["off_role_count"] == 0
    assert result["statistics"]["off_role_rate"] == 0.0


# ---------------------------------------------------------------------------
# 8. The invariant the Rust solver depends on
# ---------------------------------------------------------------------------


def test_flex_only_mask_loses_no_player() -> None:
    roles = ("Tank", "Damage", "Support", "Tank", "Damage", "Support")
    payload = {
        "players": {
            f"u-{index}": _node(f"Player {index}", {role: _class(2500 + index * 10, 0)})
            for index, role in enumerate(roles)
        }
    }

    players = load_players_from_dict(payload, FLEX_ONLY_MASK)

    assert len(players) == len(roles) == sum(FLEX_ONLY_MASK.values())
    assert all(FLEX_SLOT_CODE in player.ratings for player in players)


# ---------------------------------------------------------------------------
# 9. What actually reaches Rust
# ---------------------------------------------------------------------------


def test_native_request_carries_the_flex_mask_and_flex_ratings() -> None:
    # The native module builds only on Linux, so the contract under test is the
    # serialized request, not the solver run.
    payload = {
        "players": {f"u-{index}": _node(f"Player {index}", {"Damage": _class(2500 + index, 0)}) for index in range(6)}
    }
    players = load_players_from_dict(payload, FLEX_ONLY_MASK)
    config = AlgorithmConfig(role_mask=dict(FLEX_ONLY_MASK))

    request = json.loads(
        _serialize_native_request(
            players=players,
            num_teams=1,
            config=config,
            role_assignment={player.uuid: FLEX_SLOT_CODE for player in players},
            seed=7,
        )
    )

    assert request["mask"] == FLEX_ONLY_MASK
    assert len(request["players"]) == 6
    for entry in request["players"]:
        # The Rust core prices a playable flex slot itself (context.rs); the
        # rating is what makes it playable, and preferences stay real roles.
        assert FLEX_SLOT_CODE in entry["ratings"]
        assert FLEX_SLOT_CODE not in entry["preferences"]
        assert entry["seed_role"] == FLEX_SLOT_CODE


# ---------------------------------------------------------------------------
# 10-11. The mask is no longer a balancer setting
# ---------------------------------------------------------------------------


def test_role_mask_is_not_an_editable_or_public_config_field() -> None:
    # It is a projection of the tournament roster shape, resolved per run; an
    # editable copy would be a second source of truth that silently wins.
    assert "role_mask" not in EDITABLE_CONFIG_FIELD_KEYS
    assert "role_mask" not in PUBLIC_CONFIG_KEYS


def test_default_role_mask_is_the_canonical_roster_shape() -> None:
    assert AlgorithmConfig().role_mask == DEFAULT_ROSTER_SLOTS
    assert ConfigPresets.DEFAULT["role_mask"] == DEFAULT_ROSTER_SLOTS


# ---------------------------------------------------------------------------
# 12. Saved legacy configs keep resolving
# ---------------------------------------------------------------------------


def test_legacy_capitalized_mask_still_resolves_player_roles() -> None:
    # ``balance.config_json`` rows saved before the roster shape existed carry
    # {"Tank": 1, "Damage": 2, "Support": 2}. ``resolve_input_role_name`` is the
    # bridge that keeps them loadable; deleting it would break every old row.
    player = parse_player_node(
        "u-5",
        _node("Legacy", {"Tank": _class(2600, 1), "Damage": _class(2900, 0), "Support": _class(3100, 2)}),
        LEGACY_ROLE_MASK,
    )

    assert player is not None
    assert player.ratings == {"Tank": 2600, "Damage": 2900, "Support": 3100}
    assert player.preferences == ["Damage", "Tank", "Support"]
    assert FLEX_SLOT_CODE not in player.ratings


# ---------------------------------------------------------------------------
# 13. parse_roster_slots validates and canonicalizes through the roster canon
# ---------------------------------------------------------------------------


def test_parse_roster_slots_normalizes_the_mask_through_the_roster_canon() -> None:
    slots = parse_roster_slots({FLEX_SLOT_CODE: 5, "tank": 1}).slots

    # Canonical order comes from ROSTER_SLOT_CODES, not from the caller.
    assert list(slots.items()) == [("tank", 1), (FLEX_SLOT_CODE, 5)]


@pytest.mark.parametrize(
    "garbage",
    [
        {},
        {"tank": 0},
        {"Tank": 1, "Damage": 2, "Support": 2},
        {"tank": "1"},
        {"tank": 1, "healer": 2},
        {"tank": 99},
        [("tank", 1)],
    ],
)
def test_parse_roster_slots_rejects_a_mask_the_canon_rejects(garbage: Any) -> None:
    with pytest.raises(ValueError):
        parse_roster_slots(garbage)


# ---------------------------------------------------------------------------
# 14. The run takes the mask from the resolver
# ---------------------------------------------------------------------------


def test_balance_run_takes_the_mask_from_the_resolved_roster_shape() -> None:
    payload = {
        "players": {
            f"u-{index}": _node(
                f"Player {index}",
                {("Tank", "Damage", "Support")[index % 3]: _class(2500 + index, 0)},
            )
            for index in range(12)
        }
    }

    # Captains stay on: role assignment and captain pinning must also survive a
    # roster with no role slots, since that is what the whole run depends on.
    context = _prepare_balance_context(
        payload,
        # A stale saved config must not win over the tournament's shape.
        {"role_mask": ROLE_MASK},
        None,
        role_mask=dict(FLEX_ONLY_MASK),
    )

    assert context.config.role_mask == FLEX_ONLY_MASK
    assert context.num_teams == 2
    assert len(context.players) == 12
    assert set(context.role_assignment.values()) == {FLEX_SLOT_CODE}
    assert sum(1 for player in context.players if player.is_captain) == context.num_teams


# ---------------------------------------------------------------------------
# 'must play' -- guaranteed a seat when the lineup doesn't divide evenly
# ---------------------------------------------------------------------------


def test_must_play_players_are_never_trimmed_ahead_of_optional_ones() -> None:
    # 5 players, team size 2 -> 1 sits out. Without a flag it would be
    # whichever sorts last (u-5, see test_public_balancer_architecture.py's
    # equivalent unflagged case); flagging it 'must play' instead benches an
    # earlier, optional player.
    payload = {
        "players": {
            f"u-{index}": _node(f"Player {index}", {"Tank": _class(2500, 0)}, must_play=(index == 5))
            for index in range(1, 6)
        }
    }

    context = _prepare_balance_context(payload, None, None, role_mask={"tank": 2})

    assert context.num_teams == 2
    assert {player.uuid for player in context.players} == {"u-1", "u-2", "u-3", "u-5"}
    assert [player.uuid for player in context.overflow_benched] == ["u-4"]


def test_too_many_must_play_players_raises_a_clear_error() -> None:
    # 5 players, team size 2 -> only 4 slots exist; flagging all 5 as
    # 'must play' cannot be honoured.
    payload = {
        "players": {
            f"u-{index}": _node(f"Player {index}", {"Tank": _class(2500, 0)}, must_play=True) for index in range(1, 6)
        }
    }

    with pytest.raises(ValueError, match="must play"):
        _prepare_balance_context(payload, None, None, role_mask={"tank": 2})


# ---------------------------------------------------------------------------
# 'max_teams' -- backends pinned to a team-count ceiling (mix_balancer) cap
# the natural team count and bench the surplus, same as an uneven remainder
# ---------------------------------------------------------------------------


def test_max_teams_cap_benches_the_surplus_even_when_pool_divides_evenly() -> None:
    # 6 players, team size 2 -> divides evenly into 3 teams; max_teams=2 caps
    # it to 2, benching the extra pair exactly like an uneven remainder would.
    payload = {"players": {f"u-{index}": _node(f"Player {index}", {"Tank": _class(2500, 0)}) for index in range(1, 7)}}

    context = _prepare_balance_context(payload, None, None, role_mask={"tank": 2}, max_teams=2)

    assert context.num_teams == 2
    assert len(context.players) == 4
    assert len(context.overflow_benched) == 2


def test_max_teams_cap_still_protects_must_play_players() -> None:
    # 6 players, team size 2, capped to 2 teams -> 2 must sit out. A
    # 'must play' player is never among them unless every seat is already
    # claimed by other must-play players.
    payload = {
        "players": {
            f"u-{index}": _node(f"Player {index}", {"Tank": _class(2500, 0)}, must_play=(index in (5, 6)))
            for index in range(1, 7)
        }
    }

    context = _prepare_balance_context(payload, None, None, role_mask={"tank": 2}, max_teams=2)

    assert context.num_teams == 2
    benched_uuids = {player.uuid for player in context.overflow_benched}
    assert benched_uuids.isdisjoint({"u-5", "u-6"})


def test_balance_teams_rejects_too_few_players_for_a_capped_algorithm() -> None:
    # 2 players, team size 2 -> only 1 team's worth; mix_balancer needs
    # exactly 2. Raises before ever touching the (Linux-only) native engine.
    payload = {"players": {f"u-{index}": _node(f"Player {index}", {"Tank": _class(2500, 0)}) for index in range(1, 3)}}

    with pytest.raises(ValueError, match="needs exactly 2 team"):
        balance_teams(payload, None, None, role_mask={"tank": 2}, algorithm="mix_balancer")
