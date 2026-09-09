"""APScheduler trigger for Subscription Collection.

Periodically checks subscriptions for active tournament participants.
Leader-locked across worker replicas via Redis.

The job fires on a short fixed heartbeat and decides *inside* the tick whether the
configured ``interval_seconds`` has elapsed, rather than being registered at that
interval: the interval is admin-editable at runtime, and the admin dashboard
echoes it, so a scheduler pinned to its start-up value would quietly make that
number a lie. "When did we last run" is read from the check log itself — the same
append-only history the admin tab renders — so this needs no extra state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from loguru import logger

from shared import models
from shared.core.enums import SubscriptionCollectionSource
from shared.observability import observe_scheduled_job
from shared.services import settings_provider
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
)
from shared.services.scheduler import IntervalScheduler
from src.core import db
from src.core.broker import optional_broker
from src.core.clients import realtime_redis
from src.core.config import settings

from .service import subscription_collection_service

SCHEDULER_TICK_SECONDS = 60
LEADER_LOCK_KEY = "subscription_collection:scheduler:leader"
LEADER_LOCK_TTL_SECONDS = SCHEDULER_TICK_SECONDS * 2

_scheduler = IntervalScheduler(job_id="subscription_collection", label="Subscription collection")


async def last_scheduled_run_at(session: Any) -> datetime | None:
    """Completion time of the most recent *scheduled* check, or ``None``.

    Scoped to ``source=scheduled`` on purpose: a manual admin re-check or a
    registration gate firing must not push the background sweep back.
    """
    log = models.SubscriptionCheckLog
    return await session.scalar(
        sa.select(sa.func.max(log.created_at)).where(log.source == SubscriptionCollectionSource.scheduled.value)
    )


async def run_subscription_collection_tick(
    session_factory: Any = db.async_session_maker,
    redis_client: Any = realtime_redis,
) -> int:
    """One scheduling pass: resolve subscriptions for active tournament participants."""
    try:
        token = await acquire_distributed_lock(
            redis_client,
            LEADER_LOCK_KEY,
            ttl_seconds=LEADER_LOCK_TTL_SECONDS,
            acquire_timeout_seconds=0.0,
        )
    except DistributedLockUnavailable:
        logger.debug("Another replica holds the subscription collection leader lock; skipping tick")
        return 0

    async with observe_scheduled_job("subscription_collection"):
        try:
            async with session_factory() as session:
                cfg = await settings_provider.get_subscription_collection_config(session)
                if not cfg.enabled:
                    logger.debug("Subscription collection disabled in settings; skipping tick")
                    return 0

                last_run = await last_scheduled_run_at(session)
                if last_run is not None:
                    # Rows carry tz-aware timestamps, but a naive value from an older
                    # driver/dialect combination must not raise here and kill the job.
                    if last_run.tzinfo is None:
                        last_run = last_run.replace(tzinfo=UTC)
                    due_at = last_run + timedelta(seconds=cfg.interval_seconds)
                    if datetime.now(UTC) < due_at:
                        logger.debug("Subscription collection not due until {}; skipping tick", due_at)
                        return 0

                active_broker = optional_broker()

                count = await subscription_collection_service.collect_subscriptions_for_active_tournaments(
                    session,
                    discord_bot_token=settings.discord_token,
                    twitch_client_id=settings.twitch_client_id,
                    broker=active_broker,
                    proxy=settings.proxy_url,
                    batch_size=cfg.batch_size,
                )
                logger.info("Subscription collection tick processed {} users", count)
                return count
        except Exception:
            logger.exception("Subscription collection tick failed")
            return 0
        finally:
            await release_distributed_lock(redis_client, token)


def start_scheduler(*, redis: Any | None = None) -> None:
    redis_client = redis or realtime_redis
    _scheduler.start(
        run_subscription_collection_tick,
        seconds=SCHEDULER_TICK_SECONDS,
        args=[db.async_session_maker, redis_client],
    )


def shutdown_scheduler() -> None:
    _scheduler.shutdown()
