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

cache_invalidation = importlib.import_module("src.services.tournament.cache_invalidation")

# Mirrors the prefixes registered by ``src.core.caching.configure_cache()`` in
# production. cashews routes ``delete_match`` to the backend whose registered
# prefix the key starts with, so any pattern that does not start with one of
# these is unroutable and raises ``NotConfiguredError`` at runtime.
_CONFIGURED_PREFIXES = ("fastapi:", "backend:")
_REASONS = (
    "bracket_changed",
    "results_changed",
    "structure_changed",
    "registration_changed",
    "registration_form_changed",
)


class TournamentCacheInvalidationTests(TestCase):
    def test_bracket_change_invalidates_encounters_only(self) -> None:
        patterns = cache_invalidation.tournament_cache_patterns(42, "bracket_changed")

        self.assertTrue(any("encounters" in pattern for pattern in patterns))
        self.assertFalse(any("encounters*:None:" in pattern for pattern in patterns))
        self.assertFalse(any("tournaments/42" in pattern for pattern in patterns))
        self.assertFalse(any("teams" in pattern for pattern in patterns))

    def test_form_change_invalidates_nothing(self) -> None:
        # The registration form has one reader and it is uncached on purpose
        # (registration/admission.py), so this reason must purge nothing at
        # all — and above all must not fall through to the broad fallback that
        # wipes tournaments/teams/encounters/standings.
        self.assertEqual(cache_invalidation.tournament_cache_patterns(42, "registration_form_changed"), ())

    def test_results_change_invalidates_all_tournament_reads(self) -> None:
        patterns = cache_invalidation.tournament_cache_patterns(42, "results_changed")

        self.assertTrue(any("encounters" in pattern for pattern in patterns))
        self.assertTrue(any("tournaments/42" in pattern for pattern in patterns))
        self.assertTrue(any("teams" in pattern for pattern in patterns))
        self.assertTrue(any("standings" in pattern for pattern in patterns))

    def test_registration_change_invalidates_only_the_tournament_detail_read(self) -> None:
        # The tournament-detail read embeds live participants_count/
        # registrations_count, and the public registration list is cashews-
        # cached as `registration_list:{id}:`. Teams/standings/encounters do
        # not change on a registration write, so a registration edit must
        # not blow those away too.
        patterns = cache_invalidation.tournament_cache_patterns(42, "registration_changed")

        self.assertTrue(any("tournaments/42" in pattern for pattern in patterns))
        self.assertTrue(any("registration_list:42:" in pattern for pattern in patterns))
        self.assertFalse(any("teams" in pattern for pattern in patterns))
        self.assertFalse(any("standings" in pattern for pattern in patterns))
        self.assertFalse(any("encounters" in pattern for pattern in patterns))

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
