"""APScheduler trigger for the Twitch live-status poll tick.

Mirrors ``parser-service/src/services/subscription_collection/scheduler.py``.

The job fires on a short fixed heartbeat and decides *inside* the tick whether the
configured ``interval_seconds`` has elapsed, rather than being registered at that
interval: the interval is admin-editable at runtime through the
``stream.collection`` setting, and a scheduler pinned to its start-up value would
quietly make the number the admin sees a lie. "When did we last run" comes from
``stream:poll:last_run`` in Redis — the same key the admin re-poll clears to make
the next heartbeat due immediately.

Leader-locked across replicas so extra pods add RPC capacity without multiplying
Helix traffic on a rate-limit bucket shared with identity-service.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from shared.observability import observe_scheduled_job
from shared.services.settings_provider import settings_provider
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
)
from shared.services.scheduler import IntervalScheduler
from src.core import db
from src.rpc._clients import realtime_redis
from src.services import poller
from src.services.state import StreamStateStore

SCHEDULER_TICK_SECONDS = 30
LEADER_LOCK_KEY = "stream_poll:scheduler:leader"
LEADER_LOCK_TTL_SECONDS = SCHEDULER_TICK_SECONDS * 2

_scheduler = IntervalScheduler(job_id="stream_poll", label="Stream poll")


async def run_stream_poll_tick(
    session_factory: Any = db.async_session_maker,
    redis_client: Any = realtime_redis,
) -> int:
    """One scheduling pass: poll Twitch for every active tournament's channels."""
    try:
        token = await acquire_distributed_lock(
            redis_client,
            LEADER_LOCK_KEY,
            ttl_seconds=LEADER_LOCK_TTL_SECONDS,
            acquire_timeout_seconds=0.0,
        )
    except DistributedLockUnavailable:
        logger.debug("Another replica holds the stream poll leader lock; skipping tick")
        return 0

    async with observe_scheduled_job("stream_poll"):
        try:
            async with session_factory() as session:
                cfg = await settings_provider.get_stream_collection_config(session)

                last_run = await StreamStateStore(redis_client).get_last_run()
                if last_run is not None:
                    due_at = last_run + cfg.interval_seconds
                    if time.time() < due_at:
                        logger.debug("Stream poll not due for another {:.0f}s; skipping tick", due_at - time.time())
                        return 0

                # The `enabled` gate lives in `run_poll_tick` itself, not here: the
                # admin re-poll reaches the tick by a different route and must be
                # gated by the same line.
                count = await poller.run_poll_tick(session, redis_client, cfg)
                logger.info("Stream poll tick updated {} tournaments", count)
                return count
        except Exception:
            logger.exception("Stream poll tick failed")
            return 0
        finally:
            await release_distributed_lock(redis_client, token)


def start_scheduler(*, redis: Any | None = None) -> None:
    redis_client = redis or realtime_redis
    _scheduler.start(
        run_stream_poll_tick,
        seconds=SCHEDULER_TICK_SECONDS,
        args=[db.async_session_maker, redis_client],
    )


def shutdown_scheduler() -> None:
    _scheduler.shutdown()
