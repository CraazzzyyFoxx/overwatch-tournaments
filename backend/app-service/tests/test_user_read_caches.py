"""Cache behaviour + invalidation coverage for the /users/* read surface.

Guards two things that are easy to break silently:

* the per-flow ``@cache`` keys actually memoize (and normalize their inputs), and
* every user read-cache prefix is dropped by *both* invalidation shapes
  (tournament change → broad; profile/identity edit → precise), so a longer TTL
  never serves stale data.
"""

from __future__ import annotations

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

flows = importlib.import_module("src.services.user.service")
enums = importlib.import_module("src.core.enums")
pagination = importlib.import_module("shared.core.pagination")
user_cache = importlib.import_module("src.services.user_cache")
cache_resources = importlib.import_module("src.services.cache_resources")

_ALL_PREFIXES = (*user_cache.USER_CACHE_KEY_PREFIXES, *user_cache.USER_COMPARE_KEY_PREFIXES)


class _CacheTestBase(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        cache.setup("mem://", prefix="backend:")
        cache.setup("mem://", prefix="lock:")
        for prefix in _ALL_PREFIXES:
            await cache.delete_match(f"backend:{prefix}:*")


class UserCacheInvalidationTests(_CacheTestBase):
    async def test_tournament_patterns_clear_every_user_read_cache(self) -> None:
        for prefix in _ALL_PREFIXES:
            await cache.set(f"backend:{prefix}:5:x", 1)

        for pattern in user_cache.tournament_user_cache_patterns():
            await cache.delete_match(pattern)

        for prefix in _ALL_PREFIXES:
            self.assertIsNone(
                await cache.get(f"backend:{prefix}:5:x"),
                msg=f"{prefix} survived a tournament-change invalidation",
            )

    async def test_user_patterns_are_precise_to_the_subject(self) -> None:
        # Per-user (non-compare) caches must drop only the subject's entries.
        for prefix in user_cache.USER_CACHE_KEY_PREFIXES:
            await cache.set(f"backend:{prefix}:5:x", 1)
            await cache.set(f"backend:{prefix}:6:x", 1)

        for pattern in user_cache.user_cache_patterns(5):
            await cache.delete_match(pattern)

        for prefix in user_cache.USER_CACHE_KEY_PREFIXES:
            self.assertIsNone(await cache.get(f"backend:{prefix}:5:x"))
            self.assertEqual(1, await cache.get(f"backend:{prefix}:6:x"))

    async def test_invalidate_user_caches_routes_every_pattern(self) -> None:
        await cache.set("backend:user_heroes:9:x", 1)
        await cache.set("backend:user_matches_summary:9:x", 1)
        await cache.set("backend:user_compare:v2:9:x", 1)

        # Must not raise NotConfiguredError and must clear the subject's keys.
        await user_cache.invalidate_user_caches(9)

        self.assertIsNone(await cache.get("backend:user_heroes:9:x"))
        self.assertIsNone(await cache.get("backend:user_matches_summary:9:x"))
        self.assertIsNone(await cache.get("backend:user_compare:v2:9:x"))

    def test_tournament_invalidation_patterns_include_new_read_caches(self) -> None:
        patterns = set(cache_resources.RESOURCE_CACHE_PATTERNS["tournament.standings"](42))
        for prefix in user_cache.USER_CACHE_KEY_PREFIXES:
            self.assertIn(
                f"backend:{prefix}:*",
                patterns,
                msg=f"tournament change does not drop {prefix}",
            )
        # Regression: compare namespaces stay covered (was asserted before refactor).
        self.assertIn("backend:user_compare:v2:*", patterns)
        self.assertIn("backend:user_hero_compare:v2:*", patterns)


class HeroesCacheTests(_CacheTestBase):
    def _patch_deps(self):
        user = SimpleNamespace(id=101, name="Player")
        get_user = patch.object(flows.users, "get", AsyncMock(return_value=user))
        compute = AsyncMock(return_value=[])
        svc = patch.multiple(
            flows.users.profile,
            get_statistics_by_heroes=compute,
            get_statistics_by_heroes_all_values=AsyncMock(return_value=[]),
        )
        return get_user, svc, compute

    async def test_repeat_request_is_served_from_cache(self) -> None:
        get_user, svc, compute = self._patch_deps()
        params = pagination.PaginationParams(page=1, per_page=10)
        stats = [enums.LogStatsName.Deaths, enums.LogStatsName.Eliminations]
        with get_user, svc:
            await flows.users.get_heroes(object(), 101, params, stats, workspace_id=1)
            await flows.users.get_heroes(object(), 101, params, stats, workspace_id=1)
        compute.assert_awaited_once()

    async def test_stats_order_and_duplicates_share_one_key(self) -> None:
        get_user, svc, compute = self._patch_deps()
        params = pagination.PaginationParams(page=1, per_page=10)
        with get_user, svc:
            await flows.users.get_heroes(
                object(),
                101,
                params,
                [enums.LogStatsName.Deaths, enums.LogStatsName.Eliminations],
                workspace_id=1,
            )
            await flows.users.get_heroes(
                object(),
                101,
                params,
                [enums.LogStatsName.Eliminations, enums.LogStatsName.Deaths, enums.LogStatsName.Eliminations],
                workspace_id=1,
            )
        compute.assert_awaited_once()

    async def test_pagination_is_part_of_the_key(self) -> None:
        get_user, svc, compute = self._patch_deps()
        stats = [enums.LogStatsName.Deaths]
        with get_user, svc:
            await flows.users.get_heroes(
                object(), 101, pagination.PaginationParams(page=1, per_page=10), stats, workspace_id=1
            )
            await flows.users.get_heroes(
                object(), 101, pagination.PaginationParams(page=2, per_page=10), stats, workspace_id=1
            )
        self.assertEqual(2, compute.await_count)


class MatchesSummaryCacheTests(_CacheTestBase):
    async def test_repeat_request_is_served_from_cache(self) -> None:
        user = SimpleNamespace(id=202, name="Player")
        opponents = AsyncMock(return_value=[])
        with (
            patch.object(flows.users, "get", AsyncMock(return_value=user)),
            patch.object(flows.users.encounters, "get_user_opponents", opponents),
            patch.object(flows.users.encounters, "get_user_stage_breakdown", AsyncMock(return_value=[])),
        ):
            await flows.users.get_matches_summary(object(), 202, workspace_id=1)
            await flows.users.get_matches_summary(object(), 202, workspace_id=1)
            await flows.users.get_matches_summary(object(), 202, workspace_id=2)  # different scope
        self.assertEqual(2, opponents.await_count)


class CacheKeyRoutabilityTests(_CacheTestBase):
    """The keys the decorators really write must be reachable by the patterns in
    ``user_cache``.

    Regression: every ``@cache`` in this domain used to pass
    ``prefix="backend:"`` next to a bare ``key="user_…"`` template, and cashews
    renders that as ``backend:`` + ``:`` + template. So the stored key was
    ``backend::user_profile:7:2`` while every invalidation pattern was
    ``backend:user_profile:7:*`` — off by one colon, matching nothing. Profile
    edits, merges and tournament changes silently invalidated *nothing* for
    ~300 s. The other tests in this file seed their own keys in the pattern's
    shape, so none of them could see it. This one asserts against the key the
    decorator itself produced.
    """

    async def test_a_cached_read_is_dropped_by_its_own_invalidation_pattern(self) -> None:
        user = SimpleNamespace(id=303, name="Player")
        opponents = AsyncMock(return_value=[])
        with (
            patch.object(flows.users, "get", AsyncMock(return_value=user)),
            patch.object(flows.users.encounters, "get_user_opponents", opponents),
            patch.object(flows.users.encounters, "get_user_stage_breakdown", AsyncMock(return_value=[])),
        ):
            await flows.users.get_matches_summary(object(), 303, workspace_id=1)
            stored = [key async for key in cache.scan("backend:*")]

            await user_cache.invalidate_user_caches(303)
            self.assertEqual([], [key async for key in cache.scan("backend:*")])

            await flows.users.get_matches_summary(object(), 303, workspace_id=1)

        self.assertTrue(stored, "the decorated read stored nothing")
        for key in stored:
            self.assertTrue(
                key.startswith("backend:user_matches_summary:303:"),
                f"key {key!r} is not in the shape user_cache_patterns() globs for",
            )
        self.assertEqual(2, opponents.await_count, "invalidation did not force a recompute")

    def test_no_cache_decorator_reintroduces_the_prefix_kwarg(self) -> None:
        """``prefix=`` is what produced the double colon. The prefix belongs in
        the key template, which is also where ``user_cache`` looks for it."""
        domain = Path(__file__).resolve().parents[1] / "src" / "services"
        offenders = [
            path.relative_to(domain).as_posix()
            for path in domain.rglob("*.py")
            if 'prefix="backend:"' in path.read_text(encoding="utf-8")
        ]
        self.assertEqual([], offenders)
