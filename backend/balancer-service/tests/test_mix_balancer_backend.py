"""Tests for the mix_balancer backend connector.

What the adapter owns is pinned against a stand-in native module: the config
it sends and how it reads the engine's answer back. The search itself is
covered by the Rust crate's parity tests against the C++ engine it replaced;
the last class here runs the real extension when it is installed.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from src.domain.balancer.backends.mix_balancer import (  # noqa: E402
    MixBalancerBackend,
    build_metrics,
    quality_coefficients,
)
from src.domain.balancer.entities import Player  # noqa: E402
from src.services.balancer.config.defaults import DEFAULT_ROLE_SETTINGS, AlgorithmConfig  # noqa: E402

_MASK = {"Tank": 1, "Damage": 1}
_METRICS = {"fairness": 1.5, "uniformity": 2.5, "role_fairness": 3.5, "role_points": 4.5, "total": 12.0}


def _players() -> list[Player]:
    return [
        Player(
            name=who,
            uuid=who,
            ratings={"Tank": 2500 - index * 100, "Damage": 2000},
            preferences=["Tank", "Damage"],
            mask=_MASK,
        )
        for index, who in enumerate(("p1", "p2", "p3", "p4"))
    ]


def _solve(response: dict, progress_callback=None, **config_kwargs):
    requests: list[dict] = []

    def run_mix_balancer(request_json: str, *callback) -> str:
        requests.append(json.loads(request_json))
        if callback:
            callback[0]({"status": "running", "stage": "optimizing", "message": "m"})
        return json.dumps(response)

    config = AlgorithmConfig(role_mask=_MASK, max_result_variants=2, **config_kwargs)
    with patch(
        "src.domain.balancer.native.load_native_module",
        return_value=SimpleNamespace(run_mix_balancer=run_mix_balancer),
    ):
        solutions = MixBalancerBackend().solve(_players(), 2, config, None, 7, progress_callback)
    return solutions, requests[0]


_ONE_VARIANT = {
    "variants": [
        {
            "teams": [
                {"id": 1, "roster": {"Tank": ["p1"], "Damage": ["p2"]}},
                {"id": 2, "roster": {"Tank": ["p3"], "Damage": ["p4"]}},
            ],
            "metrics": _METRICS,
        }
    ]
}


class BuildMetricsTests(unittest.TestCase):
    def test_maps_and_prefixes_every_field(self) -> None:
        self.assertEqual(
            build_metrics(_METRICS).to_dict(),
            {
                "mix_balancer_fairness": 1.5,
                "mix_balancer_uniformity": 2.5,
                "mix_balancer_role_fairness": 3.5,
                "mix_balancer_role_points": 4.5,
                "mix_balancer_quality_total": 12.0,
            },
        )

    def test_other_backend_fields_stay_unset(self) -> None:
        metrics = build_metrics(_METRICS)
        self.assertIsNone(metrics.balance_objective)
        self.assertIsNone(metrics.composite_score)


class QualityCoefficientTests(unittest.TestCase):
    def test_centre_reproduces_the_engine_defaults(self) -> None:
        # A mix that never touches the knob must balance exactly as it did
        # before the knob existed: every coefficient back at the engine's 1.0.
        self.assertEqual((1.0, 1.0, 1.0), quality_coefficients(0.5))

    def test_ends_hand_the_whole_weight_to_one_side(self) -> None:
        # At either end the other side stops counting entirely -- pure rank
        # balance ignores who got their role, pure comfort ignores the ranks
        # (bar uniformity, which the engine never weights at all).
        self.assertEqual((2.0, 2.0, 0.0), quality_coefficients(0.0))
        self.assertEqual((0.0, 0.0, 2.0), quality_coefficients(1.0))


class SolveTests(unittest.TestCase):
    def test_sends_the_shared_envelope_with_the_host_s_tilt_and_role_weights(self) -> None:
        weights = dict(DEFAULT_ROLE_SETTINGS)
        weights["tank"] = weights["tank"].model_copy(update={"mix_weight": 2.0})
        _, request = _solve(_ONE_VARIANT, mix_comfort_tilt=0.75, role_settings=weights)

        self.assertEqual(["p1", "p2", "p3", "p4"], [p["uuid"] for p in request["players"]])
        self.assertEqual(["Tank", "Damage"], request["players"][0]["preferences"])
        self.assertEqual((2, 7), (request["num_teams"], request["seed"]))
        # Mask order, the mask's own spelling, and the host's weight per role --
        # the engine knows no role names of its own.
        self.assertEqual(
            [
                {"name": "Tank", "slots": 1, "flex": False, "weight": 2.0},
                {"name": "Damage", "slots": 1, "flex": False, "weight": 1.0},
            ],
            request["roles"],
        )
        self.assertEqual(
            {
                "max_result_variants": 2,
                "fairness_weight": 0.5,
                "role_fairness_weight": 0.5,
                "role_priority_weight": 1.5,
            },
            request["config"],
        )

    def test_reads_teams_and_metrics_back(self) -> None:
        solutions, _ = _solve(_ONE_VARIANT)

        self.assertEqual(1, len(solutions))
        teams = solutions[0].teams
        self.assertEqual([["p1"], ["p3"]], [[p.uuid for p in team.roster["Tank"]] for team in teams])
        self.assertEqual(12.0, solutions[0].metrics.mix_balancer_quality_total)

    def test_forwards_the_progress_callback(self) -> None:
        events: list[dict] = []
        _solve(_ONE_VARIANT, progress_callback=events.append)
        self.assertEqual("optimizing", events[0]["stage"])


@unittest.skipUnless(importlib.util.find_spec("balancer_native"), "balancer_native is not installed")
class NativeEngineTests(unittest.TestCase):
    def test_returns_distinct_two_team_seatings_best_first(self) -> None:
        config = AlgorithmConfig(role_mask=_MASK, max_result_variants=10)
        solutions = MixBalancerBackend().solve(_players(), 2, config, None, 0, None)

        seatings = [
            frozenset(
                frozenset((p.uuid, role) for role, players in team.roster.items() for p in players)
                for team in solution.teams
            )
            for solution in solutions
        ]
        self.assertEqual(len(seatings), len(set(seatings)), "a mirrored seating came back twice")
        totals = [solution.metrics.mix_balancer_quality_total for solution in solutions]
        self.assertEqual(sorted(totals), totals)
        self.assertTrue(all(len(solution.teams) == 2 for solution in solutions))

    def test_unseatable_lobby_is_a_value_error(self) -> None:
        players = _players()
        for player in players[1:]:
            player.ratings.pop("Tank")
        config = AlgorithmConfig(role_mask=_MASK, max_result_variants=3)
        with self.assertRaisesRegex(ValueError, "Not enough players for each role"):
            MixBalancerBackend().solve(players, 2, config, None, 0, None)


if __name__ == "__main__":
    unittest.main()
