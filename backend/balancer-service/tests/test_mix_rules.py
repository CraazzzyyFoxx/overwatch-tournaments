"""The mix engine's soft rules end to end: host knobs + format -> engine -> lobby document -> swap."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.disciplines.deadlock import OPEN_4V4, OPEN_6V6  # noqa: E402
from shared.domain.team_format import TeamFormat  # noqa: E402
from src.domain.balancer.backends.base import BalanceMetrics  # noqa: E402
from src.domain.balancer.config.defaults import AlgorithmConfig, MixRules  # noqa: E402
from src.domain.balancer.entities import Player, Team  # noqa: E402
from src.domain.balancer.mix_rules import evaluate_variant_rules, lane_layout, resolve_mix_rules  # noqa: E402
from src.domain.balancer.result_serializer import _build_response_payload, lobby_document  # noqa: E402
from src.domain.balancer.runtime import balance_teams  # noqa: E402

needs_native = pytest.mark.skipif(
    importlib.util.find_spec("balancer_native") is None, reason="balancer_native not built"
)

SIX_V_SIX = TeamFormat.from_preset("deadlock", OPEN_6V6)


def _config(**overrides: object) -> AlgorithmConfig:
    return AlgorithmConfig(role_mask={"agent": 6}, lane_layout=(2, 2, 2), **overrides)


def test_lanes_come_from_the_formats_preset() -> None:
    assert lane_layout(SIX_V_SIX) == (2, 2, 2)
    assert lane_layout(TeamFormat.from_preset("deadlock", OPEN_4V4)) == ()
    assert lane_layout(TeamFormat(discipline="deadlock", name="custom", starter_min=6, starter_max=6)) == ()
    assert lane_layout(None) == ()


def test_an_enabled_lane_rule_that_fits_the_team_is_sent() -> None:
    assert resolve_mix_rules(_config()) == [
        {"kind": "lane_matchup", "layout": [2, 2, 2], "weight": 0.5, "cohesion_weight": 0.25}
    ]
    disabled = MixRules.model_validate({"lane_matchup": {"enabled": False}})
    assert resolve_mix_rules(_config(mix_rules=disabled)) == []
    assert resolve_mix_rules(AlgorithmConfig(role_mask={"agent": 5}, lane_layout=(2, 2, 2))) == []
    assert resolve_mix_rules(AlgorithmConfig(role_mask={"agent": 6})) == []


def test_rule_penalties_rescale_with_the_ratings() -> None:
    metrics = BalanceMetrics(mix_balancer_rules={"lane_matchup": 10.0})
    assert metrics.rescale_ratings(0.5).mix_balancer_rules == {"lane_matchup": 5.0}
    assert metrics.to_dict() == {"mix_balancer_rules": {"lane_matchup": 10.0}}


def test_rule_groups_follow_teams_into_the_strongest_first_order() -> None:
    """``teams_to_json`` puts the stronger team first; engine team 2 being the stronger one must take its lanes along."""
    mask = {"agent": 2}
    teams = []
    for team_id, ratings in ((1, (1000, 1100)), (2, (3000, 3100))):
        team = Team(team_id, mask)
        for index, rating in enumerate(ratings):
            uuid = f"t{team_id}-{index}"
            team.add_player(
                "agent", Player(name=uuid, uuid=uuid, ratings={"agent": rating}, preferences=["agent"], mask=mask)
            )
        teams.append(team)
    annotations = {
        "lane_matchup": {"rule": {"kind": "lane_matchup"}, "teams": {1: [["t1-1", "t1-0"]], 2: [["t2-1", "t2-0"]]}}
    }

    payload = _build_response_payload(teams, [], mask, AlgorithmConfig(), False, annotations=annotations)

    assert [team["id"] for team in payload["teams"]] == [2, 1]
    assert payload["annotations"]["lane_matchup"]["teams"] == [[["t2-1", "t2-0"]], [["t1-1", "t1-0"]]]


def _lobby() -> dict:
    """Twelve players rated 1000..2100 in steps of 100, balanced as a Deadlock 6v6 mix."""
    payload = {
        "players": {
            f"u-{index:02}": {
                "identity": {"name": f"Player {index}"},
                "stats": {"classes": {"agent": {"isActive": True, "rank": 1000 + index * 100, "priority": 1}}},
            }
            for index in range(12)
        }
    }
    return lobby_document(
        balance_teams(payload, None, None, role_mask={"agent": 6}, algorithm="mix_balancer", team_format=SIX_V_SIX)
    )


def _rank(uuid: str) -> int:
    return int(uuid.split("-")[1])


@needs_native
def test_a_deadlock_mix_stores_lanes_for_every_option() -> None:
    document = _lobby()
    for variant in document["variants"]:
        lanes = variant["annotations"]["lane_matchup"]
        assert lanes["rule"] == {"kind": "lane_matchup", "layout": [2, 2, 2], "weight": 0.5, "cohesion_weight": 0.25}
        for team, team_lanes in zip(variant["teams"], lanes["teams"], strict=True):
            assert sorted(uuid for lane in team_lanes for uuid in lane) == sorted(team["roster"]["agent"])
        assert variant["statistics"]["mix_balancer_rules"]["lane_matchup"] >= 0
    best = document["variants"][0]["annotations"]["lane_matchup"]["teams"]
    tiers = sorted(sorted(_rank(uuid) for team in best for uuid in team[lane]) for lane in range(3))
    assert tiers == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]]


@needs_native
def test_a_swap_reseats_the_lanes_by_the_frozen_rule() -> None:
    document = _lobby()
    variant = copy.deepcopy(document["variants"][0])
    first, second = variant["teams"][0]["roster"]["agent"], variant["teams"][1]["roster"]["agent"]
    first[0], second[0] = second[0], first[0]
    variant["annotations"]["lane_matchup"]["rule"]["cohesion_weight"] = 0.0

    evaluate_variant_rules(variant, document["players"])

    lanes = variant["annotations"]["lane_matchup"]
    for team, team_lanes in zip(variant["teams"], lanes["teams"], strict=True):
        assert sorted(uuid for lane in team_lanes for uuid in lane) == sorted(team["roster"]["agent"])
    assert lanes["rule"]["cohesion_weight"] == 0.0
    assert variant["statistics"]["mix_balancer_rules"]["lane_matchup"] >= 0


@needs_native
def test_a_variant_the_engine_cannot_read_loses_its_lanes() -> None:
    document = _lobby()
    variant = copy.deepcopy(document["variants"][0])
    variant["teams"][0]["roster"]["agent"][0] = "u-unknown"

    evaluate_variant_rules(variant, document["players"])

    assert "annotations" not in variant
    assert "mix_balancer_rules" not in variant["statistics"]
