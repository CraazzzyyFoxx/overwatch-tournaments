"""Tests for the client-originated ephemeral publish path (live-drag overlay)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "realtime-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from shared.schemas.realtime import PublishOp  # noqa: E402

from src.routes import ws  # noqa: E402
from src.services.connection_manager import ConnectionState  # noqa: E402

TOPIC = "tournament:1:balancer"


def _state(user_id: int | None, *topics: str) -> ConnectionState:
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    return ConnectionState(websocket=MagicMock(), user=user, topics=set(topics))


def _drag_op(topic: str = TOPIC, event_type: str = "balancer.drag") -> PublishOp:
    return PublishOp(op="publish", topic=topic, event_type=event_type, data={"phase": "start"})


class HandlePublishTests(IsolatedAsyncioTestCase):
    async def test_anonymous_connection_is_rejected(self) -> None:
        state = _state(None, TOPIC)
        with patch.object(ws, "connection_manager") as mgr:
            mgr.send = AsyncMock()
            mgr.route = AsyncMock()
            await ws._handle_publish(state, _drag_op())
        mgr.route.assert_not_awaited()
        self.assertEqual(mgr.send.await_args.args[1]["code"], "forbidden")

    async def test_publish_to_unsubscribed_topic_is_rejected(self) -> None:
        state = _state(5)  # authenticated but not subscribed to TOPIC
        with patch.object(ws, "connection_manager") as mgr:
            mgr.send = AsyncMock()
            mgr.route = AsyncMock()
            await ws._handle_publish(state, _drag_op())
        mgr.route.assert_not_awaited()
        self.assertEqual(mgr.send.await_args.args[1]["code"], "not_subscribed")

    async def test_non_allowlisted_event_type_is_rejected(self) -> None:
        state = _state(5, TOPIC)
        with patch.object(ws, "connection_manager") as mgr:
            mgr.send = AsyncMock()
            mgr.route = AsyncMock()
            await ws._handle_publish(state, _drag_op(event_type="balancer.balance_saved"))
        mgr.route.assert_not_awaited()
        self.assertEqual(mgr.send.await_args.args[1]["code"], "forbidden_event")

    async def test_valid_publish_fans_out_with_server_stamped_actor(self) -> None:
        state = _state(5, TOPIC)
        with patch.object(ws, "connection_manager") as mgr:
            mgr.send = AsyncMock()
            mgr.route = AsyncMock()
            await ws._handle_publish(state, _drag_op())

        mgr.send.assert_not_awaited()  # no error frame
        mgr.route.assert_awaited_once()
        args, kwargs = mgr.route.await_args
        self.assertEqual(args[0], TOPIC)
        self.assertIs(kwargs["exclude"], state)  # sender does not echo to itself
        event = args[1]["event"]
        self.assertEqual(event["event_id"], 0)  # ephemeral, never persisted
        self.assertEqual(event["event_type"], "balancer.drag")
        self.assertEqual(event["actor_user_id"], 5)  # stamped from connection, not client

    async def test_rate_limit_drops_excess_frames(self) -> None:
        state = _state(5, TOPIC)
        with patch.object(ws, "connection_manager") as mgr, patch.object(ws, "monotonic", return_value=1000.0):
            mgr.send = AsyncMock()
            mgr.route = AsyncMock()
            for _ in range(ws.MAX_PUBLISH_PER_SECOND + 10):
                await ws._handle_publish(state, _drag_op())

        self.assertEqual(mgr.route.await_count, ws.MAX_PUBLISH_PER_SECOND)


class PublishOpValidationTests(TestCase):
    def test_data_key_count_is_bounded(self) -> None:
        # A handful of keys is fine (drag payloads carry ~7 scalar fields).
        PublishOp(op="publish", topic=TOPIC, event_type="balancer.drag", data={"phase": "start"})

        # An oversized data dict is rejected before fan-out (DoS amplification guard).
        oversized = {f"k{i}": i for i in range(33)}
        with pytest.raises(ValidationError):
            PublishOp(op="publish", topic=TOPIC, event_type="balancer.drag", data=oversized)
