from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitQueue

from shared.messaging.config import DLX_EXCHANGE


async def declare_dead_letter_queue(broker: Any, queue: RabbitQueue) -> None:
    """Declare and bind a durable dead-letter queue to the shared DLX."""
    exchange = await broker.declare_exchange(DLX_EXCHANGE)
    declared_queue = await broker.declare_queue(queue)
    await declared_queue.bind(exchange, routing_key=queue.routing())
