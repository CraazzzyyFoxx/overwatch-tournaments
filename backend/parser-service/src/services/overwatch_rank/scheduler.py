"""APScheduler trigger for OverFast rank collection.

The scheduler only *selects and enqueues* due battle tags — the actual HTTP
fetches happen in the worker. It runs in the FastAPI process; a Redis leader
lock ensures only one replica enqueues per tick. The tick cadence is fixed; the
effective per-tag cadence is governed by ``next_eligible_at`` (set from the
admin-configured ``interval_seconds``), so changing the interval needs no
restart.
"""

from __future__ import annotations

import math
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


def compute_per_tick(
    total_in_scope: int,
    *,
    interval_seconds: int,
    tick_seconds: int,
    rate_limit_per_minute: int,
    batch_size: int,
    max_per_tick: int | None,
) -> int:
    """How many tags to claim this tick to cover the population once per interval.

    ``needed`` is the steady rate that spreads the whole in-scope population
    evenly across ``interval_seconds``. It is capped by the per-tick share of the
    OverFast rate budget (and ``batch_size`` / ``max_per_tick``); when ``needed``
    exceeds that cap the effective interval gracefully stretches.
    """
    needed = math.ceil(total_in_scope * tick_seconds / interval_seconds)
    rate_budget = max(1, math.floor(rate_limit_per_minute * tick_seconds / 60))
    cap = batch_size if max_per_tick is None else min(batch_size, max_per_tick)
    cap = min(cap, rate_budget)
    return max(1, min(needed, cap))


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
        total_in_scope = 0
        limit = 0
        async with session_factory() as session:
            cfg = await settings_provider.get_rank_collection_config(session)
            if not cfg.enabled:
                logger.debug("OverFast rank collection disabled; skipping tick")
                return 0
            if cfg.scope == "all":
                seeded = await service.seed_states_for_all_battle_tags(
                    session, interval_seconds=cfg.interval_seconds
                )
            else:
                seeded = await service.seed_states_from_registrations(
                    session,
                    interval_seconds=cfg.interval_seconds,
                    extra_accounts=cfg.extra_accounts_per_registration,
                )

            if cfg.auto_pace:
                total_in_scope = await service.count_in_scope(session, scope=cfg.scope)
                limit = compute_per_tick(
                    total_in_scope,
                    interval_seconds=cfg.interval_seconds,
                    tick_seconds=SCHEDULER_TICK_SECONDS,
                    rate_limit_per_minute=cfg.rate_limit_per_minute,
                    batch_size=cfg.batch_size,
                    max_per_tick=cfg.max_per_tick,
                )
            else:
                limit = cfg.batch_size

            due = await service.select_and_claim_due(
                session,
                limit=limit,
                scope=cfg.scope,
                interval_seconds=cfg.interval_seconds,
                jitter_fraction=cfg.jitter_fraction,
            )
            items = [(s.social_account_id, s.battle_tag) for s in due]
            await session.commit()

        # Coverage stretches past the configured interval when the population is
        # larger than the rate budget allows; surface it rather than failing.
        effective_interval = cfg.interval_seconds
        if cfg.auto_pace and limit > 0 and total_in_scope > 0:
            effective_interval = math.ceil(total_in_scope / limit) * SCHEDULER_TICK_SECONDS
            if effective_interval > cfg.interval_seconds:
                logger.warning(
                    "OverFast rank collection rate-bound: in_scope={} per_tick={} "
                    "effective_interval={}s exceeds configured {}s (raise "
                    "rate_limit_per_minute/batch_size or narrow scope)",
                    total_in_scope,
                    limit,
                    effective_interval,
                    cfg.interval_seconds,
                )

        enqueued = 0
        for social_account_id, battle_tag in items:
            event = FetchRankEvent(
                social_account_id=social_account_id,
                battle_tag=battle_tag,
                source="scheduled",
            )
            if await tasks.enqueue_fetch(event, priority=False, broker=broker, redis=redis_client):
                enqueued += 1
        logger.info(
            "OverFast rank tick: scope={} in_scope={} seeded={} per_tick={} due={} "
            "enqueued={} effective_interval={}s",
            cfg.scope,
            total_in_scope,
            seeded,
            limit,
            len(items),
            enqueued,
            effective_interval,
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
