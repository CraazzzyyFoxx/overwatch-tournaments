from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase

from cashews import cache

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

cache_invalidation = importlib.import_module("src.services.tournament.cache_invalidation")

# Mirrors the prefixes registered by ``src.core.caching.configure_cache()`` in
# production. cashews routes ``delete_match`` to the backend whose registered
# prefix the key starts with, so any pattern that does not start with one of
# these is unroutable and raises ``NotConfiguredError`` at runtime.
_CONFIGURED_PREFIXES = ("fastapi:", "backend:")
_REASONS = ("bracket_changed", "results_changed", "structure_changed")


class TournamentCacheInvalidationTests(TestCase):
    def test_bracket_change_invalidates_encounters_only(self) -> None:
        patterns = cache_invalidation.tournament_cache_patterns(42, "bracket_changed")

        self.assertTrue(any("encounters" in pattern for pattern in patterns))
        self.assertTrue(any("encounters*:None:" in pattern for pattern in patterns))
        self.assertFalse(any("tournaments/42" in pattern for pattern in patterns))
        self.assertFalse(any("teams" in pattern for pattern in patterns))

    def test_results_change_invalidates_all_tournament_reads(self) -> None:
        patterns = cache_invalidation.tournament_cache_patterns(42, "results_changed")

        self.assertTrue(any("encounters" in pattern for pattern in patterns))
        self.assertTrue(any("tournaments/42" in pattern for pattern in patterns))
        self.assertTrue(any("teams" in pattern for pattern in patterns))

    def test_every_pattern_is_routable(self) -> None:
        # cashews has no default backend, so a pattern that matches no registered
        # prefix raises NotConfiguredError. Every emitted pattern must therefore
        # start with a configured prefix.
        for reason in _REASONS:
            for pattern in cache_invalidation.tournament_cache_patterns(42, reason):
                self.assertTrue(
                    pattern.startswith(_CONFIGURED_PREFIXES),
                    msg=f"pattern {pattern!r} ({reason}) has no configured cache backend prefix",
                )


class TournamentCacheInvalidationRuntimeTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Reproduce production routing: only prefixed backends, no default.
        for prefix in _CONFIGURED_PREFIXES:
            cache.setup("mem://", prefix=prefix)

    async def test_invalidate_does_not_raise_not_configured(self) -> None:
        for reason in _REASONS:
            await cache_invalidation.invalidate_tournament_cache(42, reason)
