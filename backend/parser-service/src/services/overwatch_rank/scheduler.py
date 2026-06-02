"""APScheduler trigger for OverFast rank collection.

The scheduler only *selects and enqueues* due battle tags — the actual HTTP
fetches happen in the worker. It runs in the FastAPI process; a Redis leader
lock ensures only one replica enqueues per tick. The tick cadence is fixed; the
effective per-tag cadence is governed by ``next_eligible_at`` (set from the
admin-configured ``interval_seconds``), so changing the interval needs no
restart.
"""

from __future__ import annotations

from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from shared.schemas.events import FetchRankEvent
from shared.services import settings_provider
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
)

from src.core import db

from . import service, tasks

SCHEDULER_TICK_SECONDS = 60
LEADER_LOCK_KEY = "ow_rank:scheduler:leader"
LEADER_LOCK_TTL_SECONDS = SCHEDULER_TICK_SECONDS * 2

_scheduler: AsyncIOScheduler | None = None


async def run_collection_tick(
    *,
    redis: Any | None = None,
    broker: Any | None = None,
    session_factory: Any = db.async_session_maker,
) -> int:
    """One scheduling pass: enqueue due tags. Returns how many were enqueued."""
    redis_client = redis or await tasks.get_redis()

    try:
        token = await acquire_distributed_lock(
            redis_client,
            LEADER_LOCK_KEY,
            ttl_seconds=LEADER_LOCK_TTL_SECONDS,
            acquire_timeout_seconds=0.5,
        )
    except DistributedLockUnavailable:
        return 0  # another replica holds leadership this tick

    try:
        seeded = 0
        async with session_factory() as session:
            cfg = await settings_provider.get_rank_collection_config(session)
            if not cfg.enabled:
                logger.debug("OverFast rank collection disabled; skipping tick")
                return 0
            if cfg.scope == "all":
                seeded = await service.seed_states_for_all_battle_tags(session)
            else:
                seeded = await service.seed_states_from_registrations(
                    session, extra_accounts=cfg.extra_accounts_per_registration
                )
            due = await service.select_and_claim_due(
                session,
                limit=cfg.batch_size,
                scope=cfg.scope,
                interval_seconds=cfg.interval_seconds,
            )
            items = [(s.battle_tag_id, s.battle_tag) for s in due]
            await session.commit()

        enqueued = 0
        for battle_tag_id, battle_tag in items:
            event = FetchRankEvent(
                battle_tag_id=battle_tag_id,
                battle_tag=battle_tag,
                source="scheduled",
            )
            if await tasks.enqueue_fetch(event, priority=False, broker=broker, redis=redis_client):
                enqueued += 1
        logger.info(
            "OverFast rank tick: scope={} seeded={} due={} enqueued={}",
            cfg.scope,
            seeded,
            len(items),
            enqueued,
        )
        return enqueued
    except Exception:
        logger.exception("OverFast rank collection tick failed")
        return 0
    finally:
        await release_distributed_lock(redis_client, token)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        run_collection_tick,
        "interval",
        seconds=SCHEDULER_TICK_SECONDS,
        id="ow_rank_collection",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("OverFast rank scheduler started (tick={}s)", SCHEDULER_TICK_SECONDS)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
