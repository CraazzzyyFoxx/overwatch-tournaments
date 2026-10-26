"""Tests for the shared RPC deadline middleware: stale drops, the process permit cap, cancellation, observability."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from faststream.rabbit import RabbitBroker, TestRabbitBroker  # noqa: E402
from prometheus_client import REGISTRY  # noqa: E402

from shared.observability.correlation import CORRELATION_ID_HEADER, get_correlation_id  # noqa: E402
from shared.rpc import deadline  # noqa: E402
from shared.rpc.deadline import (  # noqa: E402
    DEADLINE_HEADER,
    RPC_DEADLINE_CANCELLED_TOTAL,
    RPC_STALE_DROPPED_TOTAL,
    DeadlineDropMiddleware,
    configure_rpc_concurrency,
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


class PermitAndCancellationTests(IsolatedAsyncioTestCase):
    """Prefetch is per consumer; the permits are what bound a process, and the deadline is what ends a handler."""

    def setUp(self) -> None:
        self.broker = RabbitBroker(middlewares=(DeadlineDropMiddleware,))
        self.active = 0
        self.peak = 0
        self.finished: list[str] = []
        self.correlation: list[str | None] = []

        async def work(name: str, seconds: float) -> dict:
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(seconds)
            finally:
                self.active -= 1
            self.finished.append(name)
            return {"ok": True}

        # Two queues: each is its own consumer, as the ~250 RPC subjects of a service are.
        @self.broker.subscriber("rpc.test.a")
        async def a(data: dict) -> dict:
            return await work(data["name"], data["seconds"])

        @self.broker.subscriber("rpc.test.b")
        async def b(data: dict) -> dict:
            return await work(data["name"], data["seconds"])

        @self.broker.subscriber("rpc.test.missing")
        async def missing(data: dict) -> dict:
            self.correlation.append(get_correlation_id())
            return {"ok": False, "error": {"code": "not_found", "message": "nope"}}

    def tearDown(self) -> None:
        configure_rpc_concurrency(0)

    async def test_the_permits_cap_handlers_across_consumers(self) -> None:
        configure_rpc_concurrency(1)
        live = {DEADLINE_HEADER: _now_ms() + 60_000}
        async with TestRabbitBroker(self.broker) as broker:
            await asyncio.gather(
                broker.publish({"name": "a", "seconds": 0.05}, "rpc.test.a", headers=live),
                broker.publish({"name": "b", "seconds": 0.05}, "rpc.test.b", headers=live),
            )
        assert sorted(self.finished) == ["a", "b"]
        assert self.peak == 1

    async def test_an_uncapped_subject_runs_while_every_permit_is_held(self) -> None:
        """Token validation must not queue behind slow handlers: the gateway gives it 5 s before every request."""
        configure_rpc_concurrency(1)
        live = {DEADLINE_HEADER: _now_ms() + 60_000}
        with patch.object(deadline, "UNCAPPED_SUBJECTS", frozenset({"rpc.test.b"})):
            async with TestRabbitBroker(self.broker) as broker:
                slow = asyncio.create_task(broker.publish({"name": "slow", "seconds": 0.5}, "rpc.test.a", headers=live))
                await asyncio.sleep(0.05)  # "slow" holds the only permit
                await broker.publish({"name": "auth", "seconds": 0}, "rpc.test.b", headers=live)
                assert self.finished == ["auth"]
                await slow
        assert self.finished == ["auth", "slow"]

    async def test_a_request_that_expired_waiting_for_a_permit_never_runs(self) -> None:
        configure_rpc_concurrency(1)
        before = RPC_STALE_DROPPED_TOTAL.labels(queue="rpc.test.b")._value.get()
        async with TestRabbitBroker(self.broker) as broker:
            first = asyncio.create_task(
                broker.publish(
                    {"name": "a", "seconds": 0.6}, "rpc.test.a", headers={DEADLINE_HEADER: _now_ms() + 60_000}
                )
            )
            await asyncio.sleep(0.05)  # "a" holds the only permit
            # Live on arrival (within the slack), past its deadline by the time "a" lets go.
            await broker.publish({"name": "b", "seconds": 0}, "rpc.test.b", headers={DEADLINE_HEADER: _now_ms() - 300})
            await first
        assert self.finished == ["a"]
        assert RPC_STALE_DROPPED_TOTAL.labels(queue="rpc.test.b")._value.get() == before + 1

    async def test_a_handler_still_running_at_the_deadline_is_cancelled(self) -> None:
        before = RPC_DEADLINE_CANCELLED_TOTAL.labels(queue="rpc.test.a")._value.get()
        started = time.perf_counter()
        async with TestRabbitBroker(self.broker) as broker:
            # 200 ms left once the 500 ms slack is counted.
            await broker.publish(
                {"name": "slow", "seconds": 5}, "rpc.test.a", headers={DEADLINE_HEADER: _now_ms() - 300}
            )
        assert time.perf_counter() - started < 2
        assert self.finished == []
        assert self.active == 0
        assert RPC_DEADLINE_CANCELLED_TOTAL.labels(queue="rpc.test.a")._value.get() == before + 1

    async def test_messages_without_a_deadline_are_neither_capped_nor_cancelled(self) -> None:
        configure_rpc_concurrency(1)
        async with TestRabbitBroker(self.broker) as broker:
            await asyncio.gather(
                broker.publish({"name": "a", "seconds": 0.05}, "rpc.test.a"),
                broker.publish({"name": "b", "seconds": 0.05}, "rpc.test.b"),
            )
        assert self.peak == 2

    async def test_correlation_id_is_bound_and_the_reply_code_is_timed(self) -> None:
        labels = {"queue": "rpc.test.missing", "code": "not_found"}
        before = REGISTRY.get_sample_value("rpc_duration_seconds_count", labels) or 0
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish(
                {},
                "rpc.test.missing",
                headers={DEADLINE_HEADER: _now_ms() + 60_000, CORRELATION_ID_HEADER: "cid-42"},
            )
        assert self.correlation == ["cid-42"]
        assert get_correlation_id() is None
        assert REGISTRY.get_sample_value("rpc_duration_seconds_count", labels) == before + 1
