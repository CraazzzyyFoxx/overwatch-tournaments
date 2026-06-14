from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

recalculation = importlib.import_module("src.services.standings.recalculation")


class RecalculationDomainEventTests(IsolatedAsyncioTestCase):
    async def test_each_invalidation_publishes_domain_event_without_redis_lock(self) -> None:
        broker = SimpleNamespace()

        with patch.object(recalculation, "publish_message", AsyncMock()) as publish:
            first = await recalculation.enqueue_tournament_recalculation(42, broker=broker)
            second = await recalculation.enqueue_tournament_recalculation(42, broker=broker)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(2, publish.await_count)
        _, payload, queue, *_ = publish.await_args.args
        self.assertEqual("tournament_standings_invalidated", payload["event_type"])
        self.assertEqual(42, payload["tournament_id"])
        self.assertEqual("tournament_standings_invalidated", queue.name)
        self.assertEqual("tournament.standings.invalidated", publish.await_args.kwargs["routing_key"])

    async def test_close_redis_is_compatibility_noop(self) -> None:
        await recalculation.close_redis()
