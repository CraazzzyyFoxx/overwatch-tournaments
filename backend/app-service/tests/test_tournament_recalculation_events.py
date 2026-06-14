from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
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

events = importlib.import_module("src.services.tournament_events")

# Mirrors the prefixes registered by ``src.core.caching.configure_cache()``.
# cashews has no default backend, so a delete_match pattern that starts with
# none of these is unroutable and raises NotConfiguredError at runtime.
_CONFIGURED_PREFIXES = ("fastapi:", "backend:")


class TournamentStandingsCacheInvalidationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Reproduce production routing (prefixed backends only, no default),
        # but in-memory so the test never touches a real Redis.
        for prefix in _CONFIGURED_PREFIXES:
            cache.setup("mem://", prefix=prefix)

    def test_every_pattern_is_routable(self) -> None:
        for pattern in events.tournament_standings_cache_patterns(42):
            self.assertTrue(
                pattern.startswith(_CONFIGURED_PREFIXES),
                msg=f"pattern {pattern!r} has no configured cache backend prefix",
            )

    async def test_invalidate_does_not_raise_not_configured(self) -> None:
        await events.invalidate_tournament_standings_cache(42)


class TournamentRecalculationEventsTests(IsolatedAsyncioTestCase):
    async def test_changed_event_invalidates_cache(self) -> None:
        invalidate = AsyncMock()

        with patch.object(events, "invalidate_tournament_standings_cache", invalidate):
            await events.handle_tournament_changed_event(
                {"tournament_id": 42, "reason": "results_changed"}
            )

        invalidate.assert_awaited_once_with(42)

    async def test_bracket_changed_does_not_invalidate_app_service_caches(self) -> None:
        invalidate = AsyncMock()

        with patch.object(events, "invalidate_tournament_standings_cache", invalidate):
            await events.handle_tournament_changed_event(
                {"tournament_id": 42, "reason": "bracket_changed"}
            )

        invalidate.assert_not_awaited()
