"""Tests for publishing match-log processing results back to discord-service.

The result rides a fanout RabbitMQ exchange (replacing pg LISTEN/NOTIFY, which
pgBouncer transaction pooling breaks). Publishing must never fail the worker.
"""

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

result_events = importlib.import_module("src.services.match_logs.result_events")


class PublishMatchLogResultTests(IsolatedAsyncioTestCase):
    async def test_publishes_done_event_to_result_exchange(self) -> None:
        broker = SimpleNamespace()
        with patch.object(result_events, "publish_message", AsyncMock()) as publish:
            await result_events.publish_match_log_result(broker, 73, "log.txt", "done")

        self.assertEqual(1, publish.await_count)
        args, kwargs = publish.await_args
        self.assertIs(broker, args[0])
        payload = args[1]
        self.assertEqual("match_log_processed", payload["event_type"])
        self.assertEqual(73, payload["tournament_id"])
        self.assertEqual("log.txt", payload["filename"])
        self.assertEqual("done", payload["status"])
        self.assertIs(result_events.MATCH_LOG_RESULT_EXCHANGE, kwargs["exchange"])

    async def test_publishes_failed_status(self) -> None:
        with patch.object(result_events, "publish_message", AsyncMock()) as publish:
            await result_events.publish_match_log_result(SimpleNamespace(), 1, "x", "failed")
        payload = publish.await_args.args[1]
        self.assertEqual("failed", payload["status"])

    async def test_broker_error_is_swallowed(self) -> None:
        with patch.object(result_events, "publish_message", AsyncMock(side_effect=RuntimeError("down"))):
            # Must not raise — a failed result publish should never fail the worker.
            await result_events.publish_match_log_result(SimpleNamespace(), 1, "x", "done")
