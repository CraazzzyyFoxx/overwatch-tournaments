"""The invalidation consumer must actually consume.

``invalidate_from_event`` was unit-tested directly, so nothing exercised the
registered subscriber's own signature — and a loose ``msg`` annotation made
FastStream treat it as a payload field: every message failed validation and was
rejected into the DLQ, silently, with the cache never dropped. Found on the dev
stand (5 of 5 messages dead-lettered). These tests publish through the broker,
which is the only place that mistake is visible.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from cashews import cache  # noqa: E402
from faststream.rabbit import RabbitBroker, TestRabbitBroker  # noqa: E402
from loguru import logger  # noqa: E402

from shared.messaging.config import (  # noqa: E402
    CACHE_INVALIDATION_APP_QUEUE,
    CACHE_INVALIDATION_EXCHANGE,
)
from shared.services.realtime.consumer import register_invalidation_consumer  # noqa: E402

# The real topology: the binding pattern is part of what these tests pin.
EXCHANGE = CACHE_INVALIDATION_EXCHANGE
QUEUE = CACHE_INVALIDATION_APP_QUEUE


def _event(**overrides: object) -> dict:
    payload = {
        "event_type": "cache_invalidated",
        "schema_version": 1,
        "scope_kind": "tournament",
        "scope_id": 42,
        "resources": ["tournament.standings"],
        "entity_ids": {},
    }
    payload.update(overrides)
    return payload


class InvalidationConsumerTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.broker = RabbitBroker()
        self.dropped: list[str] = []
        # cashews routes delete_match by prefix and has no default backend.
        cache.setup("mem://", prefix="fastapi:")

        def standings(scope_id: int) -> tuple[str, ...]:
            return (f"fastapi:*standings*:{scope_id}:*",)

        register_invalidation_consumer(
            self.broker,
            logger,
            queue=QUEUE,
            exchange=EXCHANGE,
            patterns={"tournament.standings": standings},
            on_event=self._record,
        )

    async def _record(self, event: object) -> None:
        self.dropped.extend(getattr(event, "resources", ()))

    async def test_published_event_reaches_the_handler(self) -> None:
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish(_event(), exchange=EXCHANGE, routing_key="cache.invalidated.tournament.42")
        # The handler ran to completion: a rejected message never gets here.
        assert self.dropped == ["tournament.standings"]

    async def test_unknown_resource_is_delivered_not_rejected(self) -> None:
        """A resource this service has no rule for is a no-op, never a nack."""
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish(
                _event(resources=["workspace.pickup_mix"]),
                exchange=EXCHANGE,
                routing_key="cache.invalidated.workspace.7",
            )
        assert self.dropped == ["workspace.pickup_mix"]
