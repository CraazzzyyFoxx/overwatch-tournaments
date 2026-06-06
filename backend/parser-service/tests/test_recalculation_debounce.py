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

recalculation = importlib.import_module("src.services.standings.recalculation")


class FakeRedis:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        del value, ex
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def delete(self, key: str) -> int:
        existed = key in self.keys
        self.keys.discard(key)
        return int(existed)


class RecalculationDebounceTests(IsolatedAsyncioTestCase):
    async def test_enqueue_publishes_only_first_message_while_tournament_is_pending(self) -> None:
        redis = FakeRedis()
        broker = SimpleNamespace()
        publish_mock = AsyncMock()

        with patch.object(recalculation, "publish_message", publish_mock):
            first = await recalculation.enqueue_tournament_recalculation(42, broker=broker, redis=redis)
            second = await recalculation.enqueue_tournament_recalculation(42, broker=broker, redis=redis)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(1, publish_mock.await_count)

        _, message, _, *_ = publish_mock.await_args.args
        self.assertEqual(42, message["tournament_id"])
        self.assertEqual("tournament_recalc", publish_mock.await_args.args[2].name)
        self.assertEqual("tournament.recalc.42", publish_mock.await_args.kwargs["routing_key"])
        self.assertEqual(
            "tournament-recalc:42",
            publish_mock.await_args.kwargs["headers"]["x-deduplication-header"],
        )

    async def test_enqueue_clears_pending_marker_when_publish_fails(self) -> None:
        redis = FakeRedis()
        broker = SimpleNamespace()

        with patch.object(recalculation, "publish_message", AsyncMock(side_effect=RuntimeError("broker down"))):
            with self.assertRaises(RuntimeError):
                await recalculation.enqueue_tournament_recalculation(42, broker=broker, redis=redis)

        self.assertNotIn("tournament_recalc:pending:42", redis.keys)

    async def test_process_event_publishes_tournament_changed_results_event(self) -> None:
        redis = FakeRedis()
        broker = SimpleNamespace()
        publish_mock = AsyncMock()
        recalculate = AsyncMock()

        class _SessionFactory:
            def __call__(self):
                return self

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with (
            patch.object(recalculation, "publish_message", publish_mock),
            patch.object(recalculation.swiss_auto_round, "enqueue_swiss_next_rounds", AsyncMock()),
        ):
            processed = await recalculation.process_tournament_recalculation_event(
                {"tournament_id": 42},
                broker=broker,
                redis=redis,
                session_factory=_SessionFactory(),
                recalculate=recalculate,
            )

        self.assertTrue(processed)
        self.assertEqual(1, publish_mock.await_count)
        _, message, queue, *_ = publish_mock.await_args.args
        self.assertEqual("tournament_changed", message["event_type"])
        self.assertEqual(42, message["tournament_id"])
        self.assertEqual("results_changed", message["reason"])
        self.assertEqual("tournament_changed_tournament_service", queue.name)
        self.assertEqual("tournament.changed.42", publish_mock.await_args.kwargs["routing_key"])
