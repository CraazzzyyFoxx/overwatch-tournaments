"""Worker lifecycle of the Deadlock rank collector: its three consumers, its schedules and the deadlock-api client.

A worker that does not select ``deadlock`` never imports this module (the registry's hooks import it on call).
"""

from collections.abc import Awaitable
from typing import Any

from faststream.rabbit import Channel
from faststream.rabbit.annotations import RabbitMessage

from shared.disciplines.deadlock import collector
from shared.messaging.config import PLAYER_EVENTS_EXCHANGE
from shared.messaging.topology import declare_dead_letter_queue
from shared.observability import observe_message_processing
from shared.observability.broker import require_broker


def register_jobs(broker: Any, *, session_factory: Any, redis: Any, logger: Any) -> None:
    collector.configure(session_factory=session_factory, redis=redis, broker=broker)
    # Both fetch queues share one channel, one batch at a time: a batch is up to 1000 accounts in one request.
    fetch_channel = Channel(prefetch_count=1)

    def fetch(queue: Any, name: str) -> None:
        async def handle(data: dict, msg: RabbitMessage) -> None:
            async with observe_message_processing(queue=queue, handler=name, message=msg, logger=logger):
                await collector.process_fetch(data)

        handle.__name__ = name
        broker.subscriber(queue, channel=fetch_channel)(handle)

    fetch(collector.FETCH_QUEUE, "process_deadlock_rank_fetch")
    fetch(collector.FETCH_PRIORITY_QUEUE, "process_deadlock_rank_fetch_priority")

    # Registration approved / re-checked, mix signup: the handler skips another game's request.
    @broker.subscriber(collector.PLAYER_REFRESH_QUEUE, exchange=PLAYER_EVENTS_EXCHANGE)
    async def process_deadlock_player_refresh(data: dict, msg: RabbitMessage) -> None:
        async with observe_message_processing(
            queue=collector.PLAYER_REFRESH_QUEUE, handler="process_deadlock_player_refresh", message=msg, logger=logger
        ):
            await collector.handle_player_refresh(data, broker=broker)


async def start_jobs(*, session_factory: Any, redis: Any, logger: Any) -> None:
    collector.configure(session_factory=session_factory, redis=redis)
    broker = require_broker(collector._broker)
    for dlq in collector.OWNED_DLQS:
        await declare_dead_letter_queue(broker, dlq)
    await collector.rank_client.start()
    # Leader-locked across worker replicas, admin-settings-gated: no-ops while collection is disabled.
    collector.start_scheduler()
    logger.info("Deadlock rank collector started")


def stop_jobs() -> Awaitable[None]:
    """Stops the schedules now; the returned awaitable closes the deadlock-api client (after the consumers drained)."""
    collector.shutdown_scheduler()
    return collector.rank_client.close()
