from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from cashews import cache

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "app-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

flows = importlib.import_module("src.services.user.flows")
schemas = importlib.import_module("src.schemas")
enums = importlib.import_module("src.core.enums")
division_grid = importlib.import_module("shared.division_grid")
user_merge = importlib.import_module("src.services.admin.user_merge")
caching = importlib.import_module("src.core.caching")


def _grid(version_id: int = 17):
    return division_grid.DivisionGrid(version_id=version_id, tiers=())


class UserCompareCacheTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        cache.setup("mem://", prefix="backend:")
        cache.setup("mem://", prefix="lock:")
        await cache.delete_match("backend:user_compare:v2:*")
        await cache.delete_match("backend:user_hero_compare:v2:*")

    async def test_overall_cache_ignores_runtime_session_and_uses_grid_version(self) -> None:
        response = {"result": "overall"}
        compute = AsyncMock(return_value=response)
        params = schemas.UserCompareParams(baseline="cohort", role=enums.HeroClass.support, div_min=4, div_max=9)

        with patch.object(flows, "get_compare", compute):
            first = await flows.get_compare_cached(object(), 101, params, grid=_grid(17))
            second = await flows.get_compare_cached(object(), 101, params, grid=_grid(17))
            third = await flows.get_compare_cached(object(), 101, params, grid=_grid(18))

        self.assertEqual(first, response)
        self.assertEqual(second, response)
        self.assertEqual(third, response)
        self.assertEqual(2, compute.await_count)

    async def test_user_merge_invalidates_both_compare_namespaces(self) -> None:
        preview = SimpleNamespace(
            source=SimpleNamespace(social_accounts=[]),
            target=SimpleNamespace(social_accounts=[]),
        )
        delete_match = AsyncMock()

        with patch.object(user_merge.cache, "delete_match", delete_match):
            await user_merge._invalidate_merge_caches(  # noqa: SLF001 - invalidation contract
                source_user_id=7,
                target_user_id=9,
                preview=preview,
            )

        patterns = {call.args[0] for call in delete_match.await_args_list}
        self.assertIn("backend:user_compare:v2:*", patterns)
        self.assertIn("backend:user_hero_compare:v2:*", patterns)

    def test_cache_configuration_registers_the_lock_namespace(self) -> None:
        with patch.object(caching.cache, "setup") as setup:
            caching.configure_cache()

        self.assertTrue(
            any(call.kwargs.get("prefix") == "lock:" for call in setup.call_args_list),
            msg="cashews lock=True needs a routable lock: backend",
        )

    async def test_hero_cache_normalizes_stat_order_and_deduplicates(self) -> None:
        response = object()
        compute = AsyncMock(return_value=response)
        first_params = schemas.UserHeroCompareParams(
            baseline="global",
            left_hero_id=1,
            right_hero_id=2,
            stats=[enums.LogStatsName.Deaths, enums.LogStatsName.Eliminations],
        )
        second_params = schemas.UserHeroCompareParams(
            baseline="global",
            left_hero_id=1,
            right_hero_id=2,
            stats=[
                enums.LogStatsName.Eliminations,
                enums.LogStatsName.Deaths,
                enums.LogStatsName.Eliminations,
            ],
        )

        with patch.object(flows, "get_hero_compare", compute):
            await flows.get_hero_compare_cached(object(), 202, first_params, grid=_grid())
            await flows.get_hero_compare_cached(object(), 202, second_params, grid=_grid())

        compute.assert_awaited_once()

    async def test_stampede_lock_computes_identical_request_once(self) -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def compute(*args, **kwargs):
            entered.set()
            await release.wait()
            return {"ok": True}

        params = schemas.UserCompareParams(baseline="global")
        with patch.object(flows, "get_compare", AsyncMock(side_effect=compute)) as mocked:
            first = asyncio.create_task(flows.get_compare_cached(object(), 303, params, grid=_grid()))
            await entered.wait()
            second = asyncio.create_task(flows.get_compare_cached(object(), 303, params, grid=_grid()))
            await asyncio.sleep(0)
            release.set()
            self.assertEqual(await first, {"ok": True})
            self.assertEqual(await second, {"ok": True})

        mocked.assert_awaited_once()

    async def test_exceptions_are_not_cached(self) -> None:
        params = schemas.UserCompareParams(baseline="global")
        compute = AsyncMock(side_effect=RuntimeError("boom"))

        with patch.object(flows, "get_compare", compute):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await flows.get_compare_cached(object(), 404, params, grid=_grid())
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await flows.get_compare_cached(object(), 404, params, grid=_grid())

        self.assertEqual(2, compute.await_count)
