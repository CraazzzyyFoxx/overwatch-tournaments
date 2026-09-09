from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from cashews import cache

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "app-service"))

os.environ["DEBUG"] = "true"

from shared.services.realtime import Scope, load_manifest  # noqa: E402

cache_resources = importlib.import_module("src.services.cache_resources")

# Mirrors the prefixes registered by ``src.core.caching.configure_cache()``.
# cashews has no default backend, so a delete_match pattern that starts with
# none of these is unroutable and raises NotConfiguredError at runtime.
_CONFIGURED_PREFIXES = ("fastapi:", "backend:")


def _manifest_tournament_resources() -> set[str]:
    return {
        name for name, spec in load_manifest()["resources"].items() if spec["scope"] == "tournament"
    }


class CacheResourceTableTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Reproduce production routing (prefixed backends only, no default),
        # but in-memory so the test never touches a real Redis.
        for prefix in _CONFIGURED_PREFIXES:
            cache.setup("mem://", prefix=prefix)

    def test_table_covers_exactly_the_tournament_resources(self) -> None:
        table = {str(key) for key in cache_resources.RESOURCE_CACHE_PATTERNS}
        self.assertEqual(_manifest_tournament_resources(), table)

    def test_every_pattern_is_routable(self) -> None:
        for resource, build in cache_resources.RESOURCE_CACHE_PATTERNS.items():
            for pattern in build(42):
                self.assertTrue(
                    pattern.startswith(_CONFIGURED_PREFIXES),
                    msg=f"{resource} pattern {pattern!r} has no configured cache backend prefix",
                )

    def test_standings_drops_the_cross_tournament_user_aggregates(self) -> None:
        # The whole point of the fan-out: a tournament write moves per-user
        # aggregates this service cannot attribute to a tournament.
        patterns = set(cache_resources.RESOURCE_CACHE_PATTERNS["tournament.standings"](42))
        self.assertIn("backend:user_compare:v2:*", patterns)
        self.assertIn("backend:user_hero_compare:v2:*", patterns)
        self.assertIn("backend:achievement_rarity_map:*", patterns)

    def test_a_score_report_drops_nothing_here(self) -> None:
        # Encounter writes are the highest-frequency event on the rail; paying
        # the user-cache fan-out per score report would be a SCAN storm.
        self.assertEqual((), tuple(cache_resources.RESOURCE_CACHE_PATTERNS["tournament.encounters"](42)))

    async def test_local_invalidation_clears_the_matching_keys(self) -> None:
        await cache.set("backend:user_compare:v2:9:x", 1)
        await cache.set("backend:untouched:9:x", 1)

        await cache_resources.invalidate_local(Scope.tournament(42), frozenset({"tournament.standings"}), {})

        self.assertIsNone(await cache.get("backend:user_compare:v2:9:x"))
        self.assertEqual(1, await cache.get("backend:untouched:9:x"))
