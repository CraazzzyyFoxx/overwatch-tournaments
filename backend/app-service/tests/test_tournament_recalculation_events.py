from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

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

events = importlib.import_module("src.services.tournament.recalculation_events")


class TournamentRecalculationEventsTests(IsolatedAsyncioTestCase):
    async def test_changed_event_invalidates_cache(self) -> None:
        invalidate = AsyncMock()

        with patch.object(events, "invalidate_tournament_standings_cache", invalidate):
            await events.handle_tournament_changed_event(
                {"tournament_id": 42, "reason": "results_changed"}
            )

        invalidate.assert_awaited_once_with(42)
