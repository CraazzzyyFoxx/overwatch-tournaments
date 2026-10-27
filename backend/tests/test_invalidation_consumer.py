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

from faststream.rabbit import RabbitBroker, TestRabbitBroker  # noqa: E402
from loguru import logger  # noqa: E402

from shared.messaging.config import (  # noqa: E402
    CACHE_INVALIDATION_EXCHANGE,
    CACHE_INVALIDATION_STATS_QUEUE,
)
from shared.services.cache_generations import current  # noqa: E402
from shared.services.realtime.consumer import register_invalidation_consumer  # noqa: E402
from shared.testing.cache import configure_test_cache  # noqa: E402

# The real topology: the binding pattern is part of what these tests pin.
EXCHANGE = CACHE_INVALIDATION_EXCHANGE
QUEUE = CACHE_INVALIDATION_STATS_QUEUE


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
        configure_test_cache()

        register_invalidation_consumer(
            self.broker,
            logger,
            queue=QUEUE,
            exchange=EXCHANGE,
            on_event=self._record,
        )

    async def _record(self, event: object) -> None:
        self.dropped.extend(getattr(event, "resources", ()))

    async def test_published_event_reaches_the_handler_and_bumps_the_generations(self) -> None:
        names = ("tournament:42:tournament.standings", "tournament:*:tournament.standings")
        before = [await current(name) for name in names]

        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish(_event(), exchange=EXCHANGE, routing_key="cache.invalidated.tournament.42")

        # The handler ran to completion: a rejected message never gets here.
        assert self.dropped == ["tournament.standings"]
        after = [await current(name) for name in names]
        assert [a != b for a, b in zip(after, before, strict=True)] == [True, True]

    async def test_unknown_resource_is_delivered_not_rejected(self) -> None:
        """A resource outside this build's vocabulary (a newer publisher) is a no-op, never a nack."""
        async with TestRabbitBroker(self.broker) as broker:
            await broker.publish(
                _event(resources=["tournament.from_the_future"]),
                exchange=EXCHANGE,
                routing_key="cache.invalidated.tournament.42",
            )
        assert self.dropped == ["tournament.from_the_future"]
