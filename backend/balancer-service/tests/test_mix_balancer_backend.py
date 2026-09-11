"""Tests for the mix_balancer backend connector.

The uuid/priority/metrics helpers need no native extension and run anywhere.
``MixBalancerBackend.solve`` is covered too, against a stand-in for the
Linux-only compiled engine (``_fake_engine`` below): what is pinned is the
adapter's own behaviour -- the settings it builds, the retry it makes and the
mirrored duplicates it drops -- never the C++ search itself, which this dev box
cannot run.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
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
    _MAX_PRIORITY,
    _UNBOUNDED_BALANCE_LIMIT,
    MixBalancerBackend,
    build_metrics,
    member_uuid,
    priority_for_role,
    quality_coefficients,
    role_uuid,
    seating_key,
)
from src.domain.balancer.entities import Player  # noqa: E402
from src.services.balancer.config.defaults import AlgorithmConfig  # noqa: E402


def _player(**kwargs) -> Player:
    defaults = {
        "name": "p",
        "ratings": {"Tank": 2500, "Damage": 2000},
        "preferences": ["Tank", "Damage"],
        "uuid": "player-1",
        "mask": {"Tank": 1, "Damage": 2, "Support": 2},
    }
    defaults.update(kwargs)
    return Player(**defaults)


# One seat per team per role, so a "seating" in these tests is a list of two
# ``[(player uuid, role), ...]`` lists -- exactly what the engine returns and
# what ``seating_key`` identifies a result by.
_MASK = {"Tank": 1, "Damage": 1}
_SEATING_A = [[("p1", "Tank"), ("p2", "Damage")], [("p3", "Tank"), ("p4", "Damage")]]
_SEATING_B = [[("p1", "Tank"), ("p4", "Damage")], [("p3", "Tank"), ("p2", "Damage")]]


def seating_key_of(seating) -> frozenset:
    """What ``seating_key`` should return for a seating spec, built by hand."""
    return frozenset(frozenset(team) for team in seating)


def _response(seatings, *, ok: bool = True, status: str = "ok") -> SimpleNamespace:
    quality = SimpleNamespace(fairness=1.0, uniformity=1.0, role_fairness=1.0, role_points=1.0, total=4.0)
    balances = [
        SimpleNamespace(
            quality=quality,
            teams=[
                SimpleNamespace(
                    players=[
                        SimpleNamespace(member_id=member_uuid(who), game_role_id=role_uuid(role), rating=100)
                        for who, role in team
                    ]
                )
                for team in seating
            ],
        )
        for seating in seatings
    ]
    return SimpleNamespace(ok=ok, status=status, balances=balances)


def _fake_engine(responses: list[SimpleNamespace]) -> tuple[SimpleNamespace, list[SimpleNamespace]]:
    """Stand-in for the compiled extension, plus the call log it records.

    Only the surface the adapter touches: four input factories and a
    ``quick_find`` that replays ``responses`` in order.
    """
    calls: list[SimpleNamespace] = []

    class BalanceEngine:
        @staticmethod
        def quick_find(players, role_ids, constraints, team_size, balance_limit, quality, *, max_results):
            calls.append(
                SimpleNamespace(
                    players=players,
                    role_ids=role_ids,
                    constraints=constraints,
                    team_size=team_size,
                    balance_limit=balance_limit,
                    quality=quality,
                    max_results=max_results,
                )
            )
            return responses[len(calls) - 1]

    return (
        SimpleNamespace(
            RoleConstraint=lambda **kwargs: SimpleNamespace(**kwargs),
            PlayerRoleInfo=lambda **kwargs: SimpleNamespace(**kwargs),
            PlayerInfo=lambda **kwargs: SimpleNamespace(**kwargs),
            QualitySettings=lambda **kwargs: SimpleNamespace(**kwargs),
            BalanceEngine=BalanceEngine,
        ),
        calls,
    )


def _solve(responses: list[SimpleNamespace], **config_kwargs) -> tuple[list, list[SimpleNamespace]]:
    engine, calls = _fake_engine(responses)
    config = AlgorithmConfig(role_mask=_MASK, max_result_variants=2, **config_kwargs)
    players = [
        _player(name=who, uuid=who, mask=_MASK, ratings={"Tank": 2500, "Damage": 2000})
        for who in ("p1", "p2", "p3", "p4")
    ]
    with (
        patch("src.domain.balancer.backends.mix_balancer.platform.system", return_value="Linux"),
        patch("src.domain.balancer.backends.mix_balancer._load_library", return_value=engine),
    ):
        return MixBalancerBackend().solve(players, 2, config, None, 0, None), calls


class RoleAndMemberUuidTests(unittest.TestCase):
    def test_role_uuid_is_deterministic(self) -> None:
        self.assertEqual(role_uuid("Tank"), role_uuid("Tank"))

    def test_role_uuid_differs_per_role(self) -> None:
        self.assertNotEqual(role_uuid("Tank"), role_uuid("Damage"))

    def test_role_uuid_is_a_real_uuid(self) -> None:
        self.assertIsInstance(role_uuid("Tank"), uuid.UUID)

    def test_member_uuid_is_deterministic_and_distinct_from_role_uuid(self) -> None:
        self.assertEqual(member_uuid("player-1"), member_uuid("player-1"))
        # Distinct namespaces: a role code and a player uuid that happen to be
        # the same string must not collide.
        self.assertNotEqual(role_uuid("player-1"), member_uuid("player-1"))

    def test_member_uuid_differs_per_player(self) -> None:
        self.assertNotEqual(member_uuid("player-1"), member_uuid("player-2"))


class PriorityForRoleTests(unittest.TestCase):
    def test_most_preferred_role_gets_max_priority(self) -> None:
        player = _player(preferences=["Tank", "Damage"])
        self.assertEqual(priority_for_role(player, "Tank"), _MAX_PRIORITY)

    def test_later_preference_gets_lower_priority(self) -> None:
        player = _player(preferences=["Tank", "Damage"])
        self.assertEqual(priority_for_role(player, "Damage"), _MAX_PRIORITY - 1)

    def test_priority_floors_at_one_past_the_ceiling(self) -> None:
        player = _player(
            ratings={"Tank": 1, "Damage": 1, "Support": 1, "Flex": 1},
            preferences=["Tank", "Damage", "Support", "Flex"],
            mask={"Tank": 1, "Damage": 1, "Support": 1, "Flex": 1},
        )
        # 4th preference would be max_priority(3) - 3 = 0; floored at 1.
        self.assertEqual(priority_for_role(player, "Flex"), 1)

    def test_flex_player_gets_max_priority_for_every_playable_role(self) -> None:
        player = _player(is_flex=True, preferences=["Tank", "Damage"])
        self.assertEqual(priority_for_role(player, "Tank"), _MAX_PRIORITY)
        self.assertEqual(priority_for_role(player, "Damage"), _MAX_PRIORITY)

    def test_role_outside_preferences_defaults_to_lowest_priority(self) -> None:
        player = _player(ratings={"Tank": 2500}, preferences=["Tank"])
        self.assertEqual(priority_for_role(player, "Support"), 1)


class BuildMetricsTests(unittest.TestCase):
    def test_maps_and_prefixes_every_field(self) -> None:
        quality = SimpleNamespace(fairness=1.5, uniformity=2.5, role_fairness=3.5, role_points=4.5, total=12.0)
        metrics = build_metrics(quality)
        self.assertEqual(
            metrics.to_dict(),
            {
                "mix_balancer_fairness": 1.5,
                "mix_balancer_uniformity": 2.5,
                "mix_balancer_role_fairness": 3.5,
                "mix_balancer_role_points": 4.5,
                "mix_balancer_quality_total": 12.0,
            },
        )

    def test_coerces_to_float(self) -> None:
        quality = SimpleNamespace(fairness=1, uniformity=2, role_fairness=3, role_points=4, total=10)
        metrics = build_metrics(quality)
        self.assertTrue(all(isinstance(v, float) for v in metrics.to_dict().values()))

    def test_other_backend_fields_stay_unset(self) -> None:
        quality = SimpleNamespace(fairness=1.0, uniformity=1.0, role_fairness=1.0, role_points=1.0, total=4.0)
        metrics = build_metrics(quality)
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
    def test_drops_the_mirror_of_a_seating_it_already_returned(self) -> None:
        # The engine enumerates each team mask and its complement, and scores
        # both identically, so a raw result list repeats every seating with the
        # teams swapped. A host paging through options must not be shown the
        # same two teams twice.
        mirror = [_SEATING_A[1], _SEATING_A[0]]
        solutions, calls = _solve([_response([_SEATING_A, mirror, _SEATING_B])])

        self.assertEqual(
            [seating_key_of(_SEATING_A), seating_key_of(_SEATING_B)],
            [seating_key(solution.teams) for solution in solutions],
        )
        # Twice the wanted count is requested precisely because of that mirror.
        self.assertEqual(4, calls[0].max_results)

    def test_retries_unbounded_when_no_split_fits_the_balance_limit(self) -> None:
        # The limit prunes the search; it is not a requirement. A lobby nobody
        # can split well still has a best split, and the host gets it instead
        # of an error they cannot act on.
        refused = _response([], ok=False, status="Can't shuffle players within balance limit")
        solutions, calls = _solve([refused, _response([_SEATING_A])])

        self.assertEqual(1, len(solutions))
        self.assertEqual(1000.0, calls[0].balance_limit)
        self.assertEqual(_UNBOUNDED_BALANCE_LIMIT, calls[1].balance_limit)

    def test_reports_a_lobby_the_retry_cannot_fix(self) -> None:
        refused = _response([], ok=False, status="Not enough players for each role")
        with self.assertRaises(ValueError) as caught:
            _solve([refused])
        self.assertIn("Not enough players for each role", str(caught.exception))

    def test_hands_the_engine_the_host_s_tilt_and_role_weights(self) -> None:
        _, calls = _solve(
            [_response([_SEATING_A])],
            mix_comfort_tilt=0.75,
            mix_role_weights={"Tank": 2.0, "Support": 3.0},
        )
        quality = calls[0].quality

        self.assertEqual(0.5, quality.fairness_coef)
        self.assertEqual(0.5, quality.role_fairness_coef)
        self.assertEqual(1.5, quality.role_priority_coef)
        self.assertEqual(_MAX_PRIORITY, quality.max_priority)
        # Support is not fielded by this mix's mask, so weighting it would key a
        # role id the engine never sees.
        self.assertEqual({role_uuid("Tank"): 2.0}, quality.role_weights)

    def test_leaves_role_weights_unset_by_default(self) -> None:
        _, calls = _solve([_response([_SEATING_A])])
        self.assertIsNone(calls[0].quality.role_weights)


class MixBalanceFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_when_native_engine_is_missing(self) -> None:
        from src.services.balancer.solver import run_mix_balance

        with patch("src.services.balancer.solver.balance_teams") as balance:
            balance.side_effect = [
                RuntimeError("mix_balancer requires the 'mix-balancer' package"),
                [{"ok": True}],
            ]
            result = await run_mix_balance({}, None, None, None)
        self.assertEqual(result, {"variants": [{"ok": True}]})
        self.assertEqual("mix_balancer", balance.call_args_list[0].kwargs["algorithm"])
        self.assertEqual("tournament_balancer", balance.call_args_list[1].kwargs["algorithm"])


if __name__ == "__main__":
    unittest.main()
