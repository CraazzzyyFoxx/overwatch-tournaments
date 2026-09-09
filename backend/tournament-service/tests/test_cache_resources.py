"""Parity between this service's cache table and the shared resource manifest.

The manifest (``shared/realtime/resources.json``) is the vocabulary; this table
is one consumer's answer to "what do I drop for it". A publisher must not be
able to name a resource this service silently ignores, and this service must not
keep a rule for a resource nobody publishes — so the two sets are compared
exactly, and "we cache nothing of that" has to be said out loud as an empty
tuple rather than omitted.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

cache_resources = importlib.import_module("src.services.tournament.cache_resources")

from shared.services.realtime import Resource, load_manifest  # noqa: E402

_CONFIGURED_PREFIXES = ("fastapi:", "backend:")


def _manifest_tournament_resources() -> set[str]:
    return {name for name, spec in load_manifest()["resources"].items() if spec["scope"] == "tournament"}


class CacheResourceParityTests(TestCase):
    def test_table_covers_exactly_the_tournament_resources(self) -> None:
        table = {str(resource) for resource in cache_resources.RESOURCE_CACHE_PATTERNS}

        self.assertEqual(table, _manifest_tournament_resources())

    def test_every_pattern_is_routable(self) -> None:
        # cashews has no default backend: a pattern matching no registered prefix
        # raises NotConfiguredError and aborts the rest of the invalidation loop,
        # so one unroutable pattern silently strands every resource after it.
        for resource, build in cache_resources.RESOURCE_CACHE_PATTERNS.items():
            for pattern in build(42):
                self.assertTrue(
                    pattern.startswith(_CONFIGURED_PREFIXES),
                    msg=f"pattern {pattern!r} ({resource}) has no configured cache backend prefix",
                )

    def test_id_patterns_cannot_match_a_longer_id(self) -> None:
        # `*tournaments/7*` also matches 70, 72 and 700, so the lowest-id (busiest)
        # tournaments would evict everyone else's reads on every write. Every
        # pattern that names the id must terminate it.
        for resource, build in cache_resources.RESOURCE_CACHE_PATTERNS.items():
            for pattern in build(7):
                self.assertNotIn("7*", pattern, msg=f"pattern {pattern!r} ({resource}) matches longer ids")

    def test_registration_form_is_deliberately_uncached(self) -> None:
        # One reader, and a stale form is either a false refusal or a false
        # admission (services/registration/admission.py). An empty tuple is the
        # assertion that this stays uncached, not an oversight.
        self.assertEqual(tuple(cache_resources.patterns_for(Resource.TOURNAMENT_REGISTRATION_FORM, 42)), ())

    def test_unknown_resource_maps_to_nothing(self) -> None:
        # A workspace-scoped resource reaches this service's invalidator (the
        # shared one hands over every scope the process emits); it must fall
        # through, not raise.
        self.assertEqual(tuple(cache_resources.patterns_for(Resource.WORKSPACE_LOGS, 42)), ())
