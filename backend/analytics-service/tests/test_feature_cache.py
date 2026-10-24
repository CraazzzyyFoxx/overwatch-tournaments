from __future__ import annotations

import importlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import pandas as pd

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))


feature_cache = importlib.import_module("src.services.ml.features.cache")
job_runner = importlib.import_module("src.worker.job_runner")


def _cache_on(cache_dir: str):
    return patch.multiple(
        feature_cache.settings,
        analytics_feature_cache_enabled=True,
        analytics_feature_cache_dir=cache_dir,
        analytics_feature_cache_namespace="test",
        analytics_feature_cache_ttl_seconds=3600,
    )


def _build(value: str):
    async def build() -> pd.DataFrame:
        return pd.DataFrame({"data": [value]})

    return build


async def _never() -> pd.DataFrame:
    raise AssertionError("the cached entry was not used")


class FeatureCacheTests(IsolatedAsyncioTestCase):
    async def test_dataframe_cache_survives_memory_clear(self) -> None:
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            calls = 0

            async def build() -> pd.DataFrame:
                nonlocal calls
                calls += 1
                return pd.DataFrame({"player_id": [1], "value": [42.0]})

            async def fail_build() -> pd.DataFrame:
                raise AssertionError("disk cache was not used")

            with (
                patch.object(feature_cache.settings, "analytics_feature_cache_enabled", True),
                patch.object(feature_cache.settings, "analytics_feature_cache_dir", str(cache_dir)),
                patch.object(feature_cache.settings, "analytics_feature_cache_namespace", "test"),
                patch.object(feature_cache.settings, "analytics_feature_cache_ttl_seconds", 3600),
            ):
                feature_cache.clear_memory_cache()
                first = await feature_cache.get_or_build_dataframe(
                    "demo",
                    {"tournament_ids": (1, 2)},
                    build,
                    discipline="overwatch",
                )
                first.loc[0, "value"] = 999.0

                feature_cache.clear_memory_cache()
                second = await feature_cache.get_or_build_dataframe(
                    "demo",
                    {"tournament_ids": (1, 2)},
                    fail_build,
                    discipline="overwatch",
                )

            feature_cache.clear_memory_cache()

        self.assertEqual(1, calls)
        self.assertEqual(42.0, float(second.loc[0, "value"]))

    async def test_same_name_and_scope_under_two_disciplines_do_not_collide(self) -> None:
        """The discipline is part of the key: another game's frame is never served for the same ids, memory or disk."""
        with TemporaryDirectory() as tmp:
            built: list[str] = []

            def builder(code: str):
                async def build() -> pd.DataFrame:
                    built.append(code)
                    return pd.DataFrame({"player_id": [1], "game": [code]})

                return build

            with (
                patch.object(feature_cache.settings, "analytics_feature_cache_enabled", True),
                patch.object(feature_cache.settings, "analytics_feature_cache_dir", tmp),
                patch.object(feature_cache.settings, "analytics_feature_cache_namespace", "test"),
                patch.object(feature_cache.settings, "analytics_feature_cache_ttl_seconds", 3600),
            ):
                feature_cache.clear_memory_cache()
                params = {"tournament_id": 7, "workspace_id": 3, "workspace_ids": ()}
                ow = await feature_cache.get_or_build_dataframe(
                    "demo", params, builder("overwatch"), discipline="overwatch"
                )
                lol = await feature_cache.get_or_build_dataframe("demo", params, builder("lol"), discipline="lol")
                # A repeat read of each is a hit: in memory, then (after a memory clear) from its own disk file.
                ow_again = await feature_cache.get_or_build_dataframe(
                    "demo", params, builder("never"), discipline="overwatch"
                )
                feature_cache.clear_memory_cache()
                lol_again = await feature_cache.get_or_build_dataframe(
                    "demo", params, builder("never"), discipline="lol"
                )
                # Mutating a returned frame cannot reach the next cached read.
                ow.loc[0, "game"] = "mutated"
                ow_third = await feature_cache.get_or_build_dataframe(
                    "demo", params, builder("never"), discipline="overwatch"
                )
                feature_cache.clear_memory_cache()

        self.assertEqual(["overwatch", "lol"], built)
        self.assertEqual("overwatch", ow_again.loc[0, "game"])
        self.assertEqual("lol", lol.loc[0, "game"])
        self.assertEqual("lol", lol_again.loc[0, "game"])
        self.assertEqual("overwatch", ow_third.loc[0, "game"])

    def test_a_new_discipline_field_namespaces_every_old_key_out(self) -> None:
        """Keys built before the discipline existed hash differently, so they are never reachable."""
        legacy = feature_cache.hashlib.sha256(
            feature_cache.json.dumps(
                {
                    "feature_version": feature_cache.FEATURE_VERSION,
                    "namespace": feature_cache.settings.analytics_feature_cache_namespace,
                    "name": "demo",
                    "params": {"tournament_id": 7},
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        self.assertNotEqual(legacy, feature_cache._cache_key("demo", {"tournament_id": 7}, "overwatch"))

    async def test_a_refresh_rebuilds_a_cached_frame_once_and_writes_it_back(self) -> None:
        params = {"tournament_id": 7}
        with TemporaryDirectory() as tmp, _cache_on(tmp):
            feature_cache.clear_memory_cache()
            await feature_cache.get_or_build_dataframe("demo", params, _build("stale"), discipline="overwatch")
            with feature_cache.refreshing_feature_cache():
                fresh = await feature_cache.get_or_build_dataframe(
                    "demo", params, _build("fresh"), discipline="overwatch"
                )
                # One rebuild per block: a repeat read inside it gets the fresh entry.
                again = await feature_cache.get_or_build_dataframe("demo", params, _never, discipline="overwatch")
            feature_cache.clear_memory_cache()
            # The rebuild was written to disk for later, unrefreshed reads.
            after = await feature_cache.get_or_build_dataframe("demo", params, _never, discipline="overwatch")
            feature_cache.clear_memory_cache()

        self.assertEqual(["fresh", "fresh", "fresh"], [frame.loc[0, "data"] for frame in (fresh, again, after)])

    async def test_the_compute_job_rebuilds_frames_an_earlier_job_cached(self) -> None:
        """A recompute within the TTL must not read a frame built before the tournament's new or corrected results."""
        params = {"tournament_id": 7}
        job = SimpleNamespace(id=10, workspace_id=1, tournament_id=7, algorithms=None)

        async def infer(*_args, **_kwargs) -> dict:
            frame = await feature_cache.get_or_build_dataframe("demo", params, _build("fresh"), discipline="overwatch")
            return {"data": frame.loc[0, "data"]}

        with TemporaryDirectory() as tmp, _cache_on(tmp):
            feature_cache.clear_memory_cache()
            await feature_cache.get_or_build_dataframe("demo", params, _build("stale"), discipline="overwatch")
            with (
                patch.object(job_runner, "update_progress", AsyncMock()),
                patch.object(job_runner.flows_service, "recalculate_analytics", AsyncMock(return_value=[])),
                patch.object(job_runner, "run_for_tournament", AsyncMock(side_effect=infer)),
            ):
                summary = await job_runner.runner_service._run_compute(SimpleNamespace(), job)
            feature_cache.clear_memory_cache()

        self.assertEqual({"ml": {"data": "fresh"}}, summary)
