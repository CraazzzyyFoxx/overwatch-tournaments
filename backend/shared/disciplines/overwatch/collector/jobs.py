"""Worker lifecycle of the OverFast rank collector: consumers, schedules, the OverFast client.

The registry's lazy wrappers (``shared.disciplines.overwatch``) call these; a worker that does not select Overwatch
never imports this module.

Topology: the scheduler publishes one ``FetchRankEvent`` per due battle tag; the consumers perform the HTTP call.
The rank-fetch queues get their own channel prefetch (OverFast-protective); the player-refresh consumer rides the
broker's default channel. Their dead-letter queues are declared by ``start_jobs`` (the module owns them).
"""

from collections.abc import Awaitable
from typing import Any

from faststream.rabbit import Channel
from faststream.rabbit.annotations import RabbitMessage

from shared.messaging.config import (
    PLAYER_EVENTS_EXCHANGE,
    RANK_FETCH_DLQ,
    RANK_FETCH_PRIORITY_DLQ,
    RANK_FETCH_PRIORITY_QUEUE,
    RANK_FETCH_QUEUE,
    RANK_PLAYER_REFRESH_DLQ,
    RANK_PLAYER_REFRESH_QUEUE,
)
from shared.messaging.topology import declare_dead_letter_queue
from shared.observability import observe_message_processing
from shared.observability.broker import require_broker

from . import runtime, scheduler, tasks
from .settings import settings

#: Every queue ``register_jobs`` consumes dead-letters; nothing else would declare or bind these.
OWNED_DLQS = (
    RANK_FETCH_DLQ,
    RANK_FETCH_PRIORITY_DLQ,
    RANK_PLAYER_REFRESH_DLQ,
)


def register_jobs(broker: Any, *, session_factory: Any, redis: Any, logger: Any) -> None:
    runtime.configure(session_factory=session_factory, redis=redis, broker=broker)
    rank_fetch_channel = Channel(prefetch_count=settings().rank_fetch_worker_prefetch)

    @broker.subscriber(RANK_FETCH_QUEUE, channel=rank_fetch_channel)
    async def process_rank_fetch(data: dict, msg: RabbitMessage) -> None:
        async with observe_message_processing(
            queue=RANK_FETCH_QUEUE, handler="process_rank_fetch", message=msg, logger=logger
        ):
            await tasks.process_fetch_rank(data)

    @broker.subscriber(RANK_FETCH_PRIORITY_QUEUE, channel=rank_fetch_channel)
    async def process_rank_fetch_priority(data: dict, msg: RabbitMessage) -> None:
        async with observe_message_processing(
            queue=RANK_FETCH_PRIORITY_QUEUE, handler="process_rank_fetch_priority", message=msg, logger=logger
        ):
            await tasks.process_fetch_rank(data)

    # Player refresh (registration approved / re-checked, mix signup): the handler skips another game's request.
    @broker.subscriber(RANK_PLAYER_REFRESH_QUEUE, exchange=PLAYER_EVENTS_EXCHANGE)
    async def process_player_refresh(data: dict, msg: RabbitMessage) -> None:
        async with observe_message_processing(
            queue=RANK_PLAYER_REFRESH_QUEUE,
            handler="process_player_refresh",
            message=msg,
            logger=logger,
        ):
            await tasks.handle_player_refresh(data, broker=broker)


async def start_jobs(*, session_factory: Any, redis: Any, logger: Any) -> None:
    runtime.configure(session_factory=session_factory, redis=redis)
    broker = require_broker(runtime.broker())
    for dlq in OWNED_DLQS:
        await declare_dead_letter_queue(broker, dlq)
    await tasks.rank_client.start()
    # Periodic OverFast rank collection trigger (Redis leader-locked across worker replicas, admin-settings-gated —
    # no-ops while collection is disabled).
    scheduler.start_scheduler()
    logger.info("OverFast rank collector started")


def stop_jobs() -> Awaitable[None]:
    """Stops the schedules now; the returned awaitable closes the OverFast client (after the consumers drained)."""
    scheduler.shutdown_scheduler()
    return tasks.rank_client.close()
