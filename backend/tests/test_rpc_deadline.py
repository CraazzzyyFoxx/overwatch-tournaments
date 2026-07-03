"""Tests for the shared RPC deadline-drop middleware."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from faststream.rabbit import RabbitBroker, TestRabbitBroker  # noqa: E402

from shared.rpc.deadline import (  # noqa: E402
    DEADLINE_HEADER,
    RPC_STALE_DROPPED_TOTAL,
    DeadlineDropMiddleware,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


class DeadlineDropTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.broker = RabbitBroker(middlewares=(DeadlineDropMiddleware,))
        self.calls: list[dict] = []

        @self.broker.subscriber("rpc.test.echo")
        async def handler(data: dict) -> dict:
            self.calls.append(data)
            return {"ok": True}

    async def test_expired_message_dropped_without_calling_handler(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 1}, "rpc.test.echo", headers={DEADLINE_HEADER: _now_ms() - 10_000})
        assert self.calls == []

    async def test_fresh_message_processed(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 1}, "rpc.test.echo", headers={DEADLINE_HEADER: _now_ms() + 60_000})
        assert self.calls == [{"x": 1}]

    async def test_message_without_header_processed(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 2}, "rpc.test.echo")
        assert self.calls == [{"x": 2}]

    async def test_unparseable_header_processed(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 5}, "rpc.test.echo", headers={DEADLINE_HEADER: "not-a-number"})
        assert self.calls == [{"x": 5}]

    async def test_slack_keeps_barely_late_message_alive(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 3}, "rpc.test.echo", headers={DEADLINE_HEADER: _now_ms() - 100})
        assert self.calls == [{"x": 3}]

    async def test_drop_increments_stale_counter(self) -> None:
        before = RPC_STALE_DROPPED_TOTAL.labels(queue="rpc.test.echo")._value.get()
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish({"x": 4}, "rpc.test.echo", headers={DEADLINE_HEADER: _now_ms() - 10_000})
        after = RPC_STALE_DROPPED_TOTAL.labels(queue="rpc.test.echo")._value.get()
        assert after == before + 1
