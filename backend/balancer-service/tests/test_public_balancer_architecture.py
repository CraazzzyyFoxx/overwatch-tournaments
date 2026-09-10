from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from src.core.job_store import BalancerJobStore  # noqa: E402
from src.domain.balancer.captain_assignment_service import assign_captains  # noqa: E402
from src.domain.balancer.entities import Player  # noqa: E402
from src.domain.balancer.moo_backend import _serialize_native_request, run_moo_optimizer  # noqa: E402
from src.domain.balancer.player_loader import load_players_from_dict  # noqa: E402
from src.domain.balancer.role_assignment_service import find_feasible_role_assignment  # noqa: E402
from src.domain.balancer.runtime import balance_teams_tournament  # noqa: E402
from src.services.balancer.config.defaults import AlgorithmConfig  # noqa: E402
from src.services.balancer.request_parser import BalancerRequestParser  # noqa: E402


class MooBackendContractTests(TestCase):
    def test_serializes_current_rust_config_contract(self) -> None:
        config = AlgorithmConfig()
        config.intra_team_std_weight = 1.25
        config.internal_role_spread_weight = 0.75
        config.tank_impact_weight = 1.7
        config.mutation_rate_min = 0.2
        config.island_count = 6
        config.crossover_rate = 0.9
        config.low_rank_threshold = 900
        config.low_rank_collision_weight = 300.0

        player = Player(
            name="Player One",
            ratings={"Tank": 2500},
            preferences=["Tank"],
            uuid="player-1",
            mask=config.role_mask,
        )

        payload = json.loads(
            _serialize_native_request(
                players=[player],
                num_teams=1,
                config=config,
                role_assignment={"player-1": "Tank"},
                seed=123,
            )
        )

        config_payload = payload["config"]
        self.assertEqual(config_payload["intra_team_std_weight"], 1.25)
        self.assertEqual(config_payload["internal_role_spread_weight"], 0.75)
        self.assertEqual(config_payload["tank_impact_weight"], 1.7)
        self.assertEqual(config_payload["mutation_rate_min"], 0.2)
        self.assertEqual(config_payload["island_count"], 6)
        self.assertEqual(config_payload["crossover_rate"], 0.9)
        self.assertEqual(config_payload["low_rank_threshold"], 900)
        self.assertEqual(config_payload["low_rank_collision_weight"], 300.0)
        self.assertNotIn("elitism_rate", config_payload)
        self.assertNotIn("stagnation_threshold", config_payload)
        self.assertNotIn("default_convergence_patience", config_payload)


class MooBackendRuntimeTests(TestCase):
    def setUp(self) -> None:
        self.config = AlgorithmConfig(
            role_mask={"Tank": 1},
            population_size=10,
            generation_count=10,
            mutation_strength=1,
            max_result_variants=1,
            use_captains=False,
        )
        self.player = Player(
            name="Player One",
            ratings={"Tank": 2500},
            preferences=["Tank"],
            uuid="player-1",
            mask=self.config.role_mask,
        )
        self.role_assignment = {"player-1": "Tank"}

    def test_requires_native_module_even_when_legacy_python_backend_is_requested(self) -> None:
        with patch.dict(os.environ, {"BALANCER_MOO_BACKEND": "python"}, clear=False):
            with patch("src.domain.balancer.moo_backend.platform.system", return_value="Linux"):
                with patch("src.domain.balancer.moo_backend._load_native_module", return_value=None):
                    with self.assertRaisesRegex(RuntimeError, "tournament_balancer"):
                        run_moo_optimizer(
                            [self.player],
                            1,
                            self.config,
                            None,
                            role_assignment=self.role_assignment,
                            seed=123,
                        )

    def test_propagates_rust_backend_failures_without_python_fallback(self) -> None:
        broken_native = SimpleNamespace(
            run_moo_optimizer=lambda _: (_ for _ in ()).throw(ValueError("native exploded"))
        )

        with patch("src.domain.balancer.moo_backend.platform.system", return_value="Linux"):
            with patch("src.domain.balancer.moo_backend._load_native_module", return_value=broken_native):
                with self.assertRaisesRegex(ValueError, "native exploded"):
                    run_moo_optimizer(
                        [self.player],
                        1,
                        self.config,
                        None,
                        role_assignment=self.role_assignment,
                        seed=123,
                    )

    def test_forwards_progress_callback_to_native_backend_when_present(self) -> None:
        observed_events: list[dict[str, object]] = []

        def progress_callback(payload: dict[str, object]) -> None:
            observed_events.append(payload)

        def fake_run_moo_optimizer(request_payload: str, native_progress_callback=None) -> str:
            self.assertIsNotNone(native_progress_callback)
            native_progress_callback(
                {
                    "status": "running",
                    "stage": "optimizing",
                    "message": "Rust MOO initialized 1 search islands",
                    "progress": {"current": 0, "total": 10, "percent": 0.0},
                }
            )
            payload = json.loads(request_payload)
            return json.dumps(
                {
                    "variants": [
                        {
                            "teams": [
                                {
                                    "id": 1,
                                    "roster": {payload["players"][0]["seed_role"]: [payload["players"][0]["uuid"]]},
                                }
                            ]
                        }
                    ]
                }
            )

        native_module = SimpleNamespace(run_moo_optimizer=fake_run_moo_optimizer)

        with patch("src.domain.balancer.moo_backend.platform.system", return_value="Linux"):
            with patch("src.domain.balancer.moo_backend._load_native_module", return_value=native_module):
                result = run_moo_optimizer(
                    [self.player],
                    1,
                    self.config,
                    progress_callback,
                    role_assignment=self.role_assignment,
                    seed=123,
                )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            observed_events,
            [
                {
                    "status": "running",
                    "stage": "optimizing",
                    "message": "Rust MOO initialized 1 search islands",
                    "progress": {"current": 0, "total": 10, "percent": 0.0},
                }
            ],
        )


class BalancerRequestParserTests(TestCase):
    def test_rejects_nested_legacy_config_wrapper(self) -> None:
        parser = BalancerRequestParser()

        with self.assertRaises(ValueError):
            parser.parse_config_overrides('{"config_overrides": {"algorithm": "moo"}}')

    def test_ignores_legacy_input_role_mapping_override(self) -> None:
        parser = BalancerRequestParser()

        payload = parser.parse_config_overrides('{"population_size": 50, "input_role_mapping": {"tank": "Tank"}}')

        self.assertEqual(payload, {"population_size": 50})


class PlayerLoaderTests(TestCase):
    def test_accepts_standard_role_aliases_without_explicit_mapping(self) -> None:
        players = load_players_from_dict(
            {
                "players": {
                    "player-1": {
                        "identity": {
                            "name": "Player One",
                            "isFullFlex": False,
                        },
                        "stats": {
                            "classes": {
                                "tank": {"isActive": True, "rank": 2500, "priority": 0},
                                "damage": {"isActive": True, "rank": 2400, "priority": 1},
                                "support": {"isActive": True, "rank": 2300, "priority": 2},
                            }
                        },
                    }
                }
            },
            {"Tank": 1, "Damage": 2, "Support": 2},
        )

        self.assertEqual(len(players), 1)
        self.assertEqual(players[0].ratings, {"Tank": 2500, "Damage": 2400, "Support": 2300})
        self.assertEqual(players[0].preferences, ["Tank", "Damage", "Support"])

    def test_builds_stable_preferences_when_role_priorities_tie(self) -> None:
        players = load_players_from_dict(
            {
                "players": {
                    "player-1": {
                        "identity": {
                            "name": "Player One",
                            "isFullFlex": False,
                        },
                        "stats": {
                            "classes": {
                                "support": {"isActive": True, "rank": 2300, "priority": 0},
                                "tank": {"isActive": True, "rank": 2500, "priority": 0},
                                "damage": {"isActive": True, "rank": 2400, "priority": 0},
                            }
                        },
                    }
                }
            },
            {"Tank": 1, "Damage": 2, "Support": 2},
        )

        self.assertEqual(len(players), 1)
        self.assertEqual(players[0].preferences, ["Damage", "Support", "Tank"])


class BalancerJobStoreTests(IsolatedAsyncioTestCase):
    class FakePipeline:
        def __init__(self, redis_client) -> None:
            self._redis = redis_client
            self._operations: list[tuple[str, tuple[object, ...]]] = []

        def set(self, key, value, ex=None):
            self._operations.append(("set", (key, value, ex)))
            return self

        def expire(self, key, ttl):
            self._operations.append(("expire", (key, ttl)))
            return self

        def rpush(self, key, value):
            self._operations.append(("rpush", (key, value)))
            return self

        async def execute(self):
            for operation, args in self._operations:
                if operation == "set":
                    await self._redis.set(*args)
                elif operation == "expire":
                    await self._redis.expire(*args)
                elif operation == "rpush":
                    await self._redis.rpush(*args)
            self._operations.clear()

    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, object] = {}
            self.get_calls = 0
            self.llen_calls = 0

        def pipeline(self):
            return BalancerJobStoreTests.FakePipeline(self)

        async def set(self, key, value, ex=None):
            self.values[key] = value

        async def get(self, key):
            self.get_calls += 1
            return self.values.get(key)

        async def incr(self, key):
            next_value = int(self.values.get(key, 0)) + 1
            self.values[key] = next_value
            return next_value

        async def rpush(self, key, value):
            self.values.setdefault(key, [])
            self.values[key].append(value)

        async def llen(self, key):
            self.llen_calls += 1
            return len(self.values.get(key, []))

        async def lrange(self, key, start, end):
            values = list(self.values.get(key, []))
            if end == -1:
                return values[start:]
            return values[start : end + 1]

        async def expire(self, key, ttl):
            return True

        async def sadd(self, key, *members):
            existing = self.values.setdefault(key, set())
            before = len(existing)
            existing.update(members)
            return len(existing) - before

        async def srem(self, key, *members):
            existing = self.values.get(key)
            if not isinstance(existing, set):
                return 0
            removed = 0
            for member in members:
                if member in existing:
                    existing.discard(member)
                    removed += 1
            return removed

        async def scard(self, key):
            existing = self.values.get(key)
            return len(existing) if isinstance(existing, set) else 0

        async def smembers(self, key):
            existing = self.values.get(key)
            return set(existing) if isinstance(existing, set) else set()

    async def test_persists_canonical_payload_keys_only(self) -> None:
        store = BalancerJobStore.__new__(BalancerJobStore)
        store._redis = self.FakeRedis()
        store._ttl_seconds = 3600

        job_id = await store.create_job(
            {"players": {}},
            {"algorithm": "moo"},
            workspace_id=10,
            created_by=20,
            role_mask={"tank": 1, "flex": 4},
        )

        payload = await store.get_job_payload(job_id)

        self.assertEqual(
            payload,
            {
                "player_data": {"players": {}},
                "config_overrides": {"algorithm": "moo"},
                "role_mask": {"tank": 1, "flex": 4},
            },
        )

    async def test_get_job_meta_uses_persisted_events_count_without_llen(self) -> None:
        store = BalancerJobStore.__new__(BalancerJobStore)
        store._redis = self.FakeRedis()
        store._ttl_seconds = 3600
        job_id = "job-meta"
        meta = {
            "job_id": job_id,
            "status": "running",
            "stage": "optimizing",
            "created_at": 1.0,
            "started_at": 2.0,
            "finished_at": None,
            "progress": {"percent": 10.0},
            "error": None,
            "workspace_id": 7,
            "created_by": 9,
            "events_count": 4,
        }
        store._redis.values[store._meta_key(job_id)] = json.dumps(meta)

        loaded = await store.get_job_meta(job_id)

        self.assertEqual(loaded["events_count"], 4)
        self.assertEqual(store._redis.llen_calls, 0)

    async def test_append_event_updates_meta_without_reread_when_meta_passed(self) -> None:
        store = BalancerJobStore.__new__(BalancerJobStore)
        store._redis = self.FakeRedis()
        store._ttl_seconds = 3600
        job_id = "job-progress"
        meta = {
            "job_id": job_id,
            "status": "running",
            "stage": "solving",
            "created_at": 1.0,
            "started_at": 2.0,
            "finished_at": None,
            "progress": None,
            "error": None,
            "workspace_id": 7,
            "created_by": 9,
            "events_count": 1,
        }
        store._redis.values[store._event_sequence_key(job_id)] = 1

        await store.append_event(
            job_id,
            status="running",
            stage="optimizing",
            message="Progress update",
            progress={"percent": 25.0},
            update_meta=True,
            meta=meta,
        )

        self.assertEqual(store._redis.get_calls, 0)
        self.assertEqual(meta["events_count"], 2)
        self.assertEqual(meta["stage"], "optimizing")
        self.assertEqual(meta["progress"], {"percent": 25.0})

    async def test_mark_succeeded_persists_result_and_final_event_count(self) -> None:
        store = BalancerJobStore.__new__(BalancerJobStore)
        store._redis = self.FakeRedis()
        store._ttl_seconds = 3600
        job_id = "job-success"
        meta = {
            "job_id": job_id,
            "status": "running",
            "stage": "optimizing",
            "created_at": 1.0,
            "started_at": 2.0,
            "finished_at": None,
            "progress": {"percent": 100.0},
            "error": None,
            "workspace_id": 7,
            "created_by": 9,
            "events_count": 2,
        }
        result = {"variants": [{"teams": [], "statistics": {}, "benched_players": []}]}
        store._redis.values[store._event_sequence_key(job_id)] = 2

        updated_meta = await store.mark_succeeded(job_id, result, meta=meta)
        stored_result = await store.get_job_result(job_id)

        self.assertEqual(updated_meta["status"], "succeeded")
        self.assertEqual(updated_meta["events_count"], 3)
        self.assertEqual(stored_result, result)


class SolverDomainServiceTests(TestCase):
    def setUp(self) -> None:
        self.mask = {"tank": 1, "dps": 1}
        self.players = [
            Player(
                name="Tank Main",
                ratings={"tank": 2800},
                preferences=["tank"],
                uuid="tank-main",
                mask=self.mask,
            ),
            Player(
                name="Flex Carry",
                ratings={"tank": 2500, "dps": 2700},
                preferences=["dps", "tank"],
                uuid="flex-carry",
                mask=self.mask,
                is_flex=True,
            ),
        ]

    def test_assign_captains_marks_requested_count(self) -> None:
        assign_captains(self.players, count=1, mask=self.mask)

        self.assertEqual(sum(1 for player in self.players if player.is_captain), 1)

    def test_find_feasible_role_assignment_matches_existing_feasibility_rules(self) -> None:
        role_assignment = find_feasible_role_assignment(self.players, num_teams=1, mask=self.mask)

        self.assertEqual(role_assignment, {"tank-main": "tank", "flex-carry": "dps"})


class MooDeterminismTests(TestCase):
    def test_balance_teams_moo_returns_same_best_variant_for_same_input(self) -> None:
        input_data = {
            "players": {
                f"player-{index}": {
                    "identity": {
                        "name": f"Player {index}",
                        "isFullFlex": False,
                    },
                    "stats": {
                        "classes": {
                            "tank": {
                                "isActive": True,
                                "rank": 2500,
                                "priority": 0,
                            }
                        }
                    },
                }
                for index in range(1, 7)
            }
        }
        # The mask is no longer a config override: it is the tournament's
        # resolved roster shape, handed to the run directly.
        role_mask = {"tank": 1}
        config_overrides = {
            "algorithm": "moo",
            "population_size": 10,
            "generation_count": 10,
            "mutation_strength": 1,
            "max_result_variants": 1,
            "use_captains": False,
        }

        observed_seeds: list[int] = []

        def fake_run_moo_optimizer(request_payload: str) -> str:
            payload = json.loads(request_payload)
            observed_seeds.append(payload["seed"])
            role_names = sorted(payload["mask"].keys())
            players = sorted(payload["players"], key=lambda entry: entry["uuid"])
            teams = []
            for index, player in enumerate(players, start=1):
                role = player["seed_role"] or role_names[0]
                teams.append(
                    {
                        "id": index,
                        "roster": {role: [player["uuid"]]},
                    }
                )
            return json.dumps({"variants": [{"teams": teams}]})

        native_module = SimpleNamespace(run_moo_optimizer=fake_run_moo_optimizer)

        with patch("src.domain.balancer.moo_backend.platform.system", return_value="Linux"):
            with patch("src.domain.balancer.moo_backend._load_native_module", return_value=native_module):
                runs = [
                    balance_teams_tournament(input_data, config_overrides, None, role_mask)[0]["teams"]
                    for _ in range(3)
                ]

        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[1], runs[2])
        self.assertEqual(observed_seeds[0], observed_seeds[1])
        self.assertEqual(observed_seeds[1], observed_seeds[2])

    def test_balance_teams_moo_ignores_input_player_order(self) -> None:
        def make_input(order: list[int]) -> dict[str, dict[str, dict[str, object]]]:
            return {
                "players": {
                    f"player-{index}": {
                        "identity": {
                            "name": f"Player {index}",
                            "isFullFlex": False,
                        },
                        "stats": {
                            "classes": {
                                "tank": {
                                    "isActive": True,
                                    "rank": 2500 + index,
                                    "priority": 0,
                                }
                            }
                        },
                    }
                    for index in order
                }
            }

        role_mask = {"tank": 1}
        config_overrides = {
            "algorithm": "moo",
            "population_size": 10,
            "generation_count": 10,
            "mutation_strength": 1,
            "max_result_variants": 1,
            "use_captains": False,
        }

        observed_player_orders: list[list[str]] = []

        def fake_run_moo_optimizer(request_payload: str) -> str:
            payload = json.loads(request_payload)
            observed_player_orders.append([player["uuid"] for player in payload["players"]])
            role_name = sorted(payload["mask"].keys())[0]
            teams = [
                {
                    "id": index,
                    "roster": {role_name: [player["uuid"]]},
                }
                for index, player in enumerate(payload["players"], start=1)
            ]
            return json.dumps({"variants": [{"teams": teams}]})

        native_module = SimpleNamespace(run_moo_optimizer=fake_run_moo_optimizer)

        with patch("src.domain.balancer.moo_backend.platform.system", return_value="Linux"):
            with patch("src.domain.balancer.moo_backend._load_native_module", return_value=native_module):
                ordered_run = balance_teams_tournament(
                    make_input([1, 2, 3, 4, 5, 6]), config_overrides, None, role_mask
                )[0]["teams"]
                reversed_run = balance_teams_tournament(
                    make_input([6, 5, 4, 3, 2, 1]), config_overrides, None, role_mask
                )[0]["teams"]

        self.assertEqual(ordered_run, reversed_run)
        self.assertEqual(observed_player_orders[0], observed_player_orders[1])
        self.assertEqual(
            observed_player_orders[0],
            [f"player-{index}" for index in range(1, 7)],
        )

    def test_balance_teams_moo_benches_players_left_over_after_full_teams(self) -> None:
        """A player count that isn't an exact multiple of the team size no
        longer blocks the run: the leftover players are benched automatically
        instead of the solver raising a "must be divisible" error."""
        input_data = {
            "players": {
                f"player-{index}": {
                    "identity": {
                        "name": f"Player {index}",
                        "isFullFlex": False,
                    },
                    "stats": {
                        "classes": {
                            "tank": {
                                "isActive": True,
                                "rank": 2500,
                                "priority": 0,
                            }
                        }
                    },
                }
                for index in range(1, 6)  # 5 players, team size 2 -> 1 sits out
            }
        }
        role_mask = {"tank": 2}
        config_overrides = {
            "algorithm": "moo",
            "population_size": 10,
            "generation_count": 10,
            "mutation_strength": 1,
            "max_result_variants": 1,
            "use_captains": False,
        }

        def fake_run_moo_optimizer(request_payload: str) -> str:
            payload = json.loads(request_payload)
            players = sorted(payload["players"], key=lambda entry: entry["uuid"])
            team_size = sum(payload["mask"].values())
            # The native backend must only ever see a player count that
            # divides evenly into full teams -- the leftover was trimmed
            # before this request was built.
            self.assertEqual(len(players) % team_size, 0)
            teams = [
                {
                    "id": team_index + 1,
                    "roster": {
                        "tank": [
                            player["uuid"] for player in players[team_index * team_size : (team_index + 1) * team_size]
                        ]
                    },
                }
                for team_index in range(len(players) // team_size)
            ]
            return json.dumps({"variants": [{"teams": teams}]})

        native_module = SimpleNamespace(run_moo_optimizer=fake_run_moo_optimizer)

        with patch("src.domain.balancer.moo_backend.platform.system", return_value="Linux"):
            with patch("src.domain.balancer.moo_backend._load_native_module", return_value=native_module):
                result = balance_teams_tournament(input_data, config_overrides, None, role_mask)[0]

        self.assertEqual(len(result["teams"]), 2)
        self.assertEqual(sum(len(team["roster"].get("tank", [])) for team in result["teams"]), 4)
        benched = result["benched_players"]
        self.assertEqual(len(benched), 1)
        self.assertEqual(benched[0]["uuid"], "player-5")
