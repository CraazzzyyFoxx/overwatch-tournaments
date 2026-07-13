"""RabbitMQ publishing + worker handler for OverFast rank fetches.

Topology: the scheduler (FastAPI process) publishes one ``FetchRankEvent`` per
due battle tag; the worker (serve.py) consumes and performs the HTTP call. Redis
provides per-tag enqueue/in-flight dedup, a soft global rate limiter and a 429
cooldown so a fleet of workers can't overrun the self-hosted OverFast instance.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from redis import asyncio as redis_async

from shared.core import enums
from shared.messaging.config import RANK_FETCH_PRIORITY_QUEUE, RANK_FETCH_QUEUE
from shared.observability import publish_message
from shared.schemas.events import FetchRankEvent, RegistrationApprovedEvent
from shared.services import settings_provider
from src.core import config, db
from src.core.broker import require_broker

from . import mapping, service
from .client import OverFastError, OverFastRankClient, OverFastRateLimited

PENDING_TTL_SECONDS = 15 * 60
INFLIGHT_TTL_SECONDS = 180
COOLDOWN_KEY = "ow_rank:cooldown"

rank_client = OverFastRankClient(
    base_url=config.settings.overfast_base_url,
    timeout=config.settings.overfast_timeout,
    max_retries=config.settings.overfast_max_retries,
)

_redis_client: redis_async.Redis | None = None


async def get_redis() -> redis_async.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_async.from_url(str(config.settings.redis_url), decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is None:
        return
    await _redis_client.aclose()
    _redis_client = None


def _pending_key(social_account_id: int) -> str:
    return f"ow_rank:fetch:pending:{social_account_id}"


def _inflight_key(social_account_id: int) -> str:
    return f"ow_rank:fetch:inflight:{social_account_id}"


async def _set_once(redis: Any, key: str, ttl_seconds: int) -> bool:
    return bool(await redis.set(key, "1", nx=True, ex=ttl_seconds))


async def _allow_request(redis: Any, limit: int) -> bool:
    """Fixed-window per-minute limiter; returns False when the window is full."""
    bucket = int(datetime.now(UTC).timestamp() // 60)
    key = f"ow_rank:rl:{bucket}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 70)
    return count <= limit


async def enqueue_fetch(
    event: FetchRankEvent,
    *,
    priority: bool = False,
    force: bool = False,
    broker: Any | None = None,
    redis: Any | None = None,
) -> bool:
    """Publish a fetch event once per battle tag (Redis-deduped).

    ``force=True`` bypasses the enqueue dedup (used by manual admin triggers so a
    "collect now" always runs even if a fetch is already pending).
    """
    redis_client = redis or await get_redis()
    pending = _pending_key(event.social_account_id)
    if force:
        await redis_client.set(pending, "1", ex=PENDING_TTL_SECONDS)
    elif not await _set_once(redis_client, pending, PENDING_TTL_SECONDS):
        return False

    queue = RANK_FETCH_PRIORITY_QUEUE if priority else RANK_FETCH_QUEUE
    try:
        await publish_message(
            require_broker(broker),
            event.model_dump(),
            queue,
            logger=logger.bind(social_account_id=event.social_account_id, source=event.source),
        )
    except Exception:
        await redis_client.delete(pending)
        raise
    return True


async def handle_registration_approved(
    data: dict[str, Any],
    *,
    broker: Any | None = None,
    redis: Any | None = None,
    session_factory: Any = db.async_session_maker,
) -> int:
    """On registration approval, prioritize + enqueue a rank check for the player.

    Reference-only: snapshots are stored for admin display; the player's declared
    registration rank is never overwritten. Skips unlinked registrations (the
    feature attaches to ``players.user``). Returns the number of tags enqueued.
    """
    event = RegistrationApprovedEvent.model_validate(data)
    if event.user_id is None:
        return 0

    async with session_factory() as session:
        cfg = await settings_provider.get_rank_collection_config(session)
        # Only the registered pool (main + smurfs) + up to N extra accounts —
        # not every battle tag the registrant owns.
        tags = await service.resolve_registration_targets(
            session,
            registration_id=event.registration_id,
            fallback_battle_tag=event.battle_tag,
            user_id=event.user_id,
            extra_accounts=cfg.extra_accounts_per_registration,
        )
        for social_account_id, battle_tag in tags:
            await service.ensure_state(session, social_account_id, battle_tag, priority_tier=2)
        await session.commit()

    enqueued = 0
    for social_account_id, battle_tag in tags:
        fetch = FetchRankEvent(
            social_account_id=social_account_id,
            battle_tag=battle_tag,
            source="registration",
            registration_id=event.registration_id,
            tournament_id=event.tournament_id,
        )
        if await enqueue_fetch(fetch, priority=True, broker=broker, redis=redis):
            enqueued += 1
    return enqueued


async def process_fetch_rank(
    data: dict[str, Any],
    *,
    redis: Any | None = None,
    client: OverFastRankClient | None = None,
    session_factory: Any = db.async_session_maker,
) -> None:
    """Handle one fetch event: rate-limit, call OverFast, persist snapshot/state."""
    event = FetchRankEvent.model_validate(data)
    redis_client = redis or await get_redis()
    client = client or rank_client
    inflight = _inflight_key(event.social_account_id)

    if not await _set_once(redis_client, inflight, INFLIGHT_TTL_SECONDS):
        logger.info("Rank fetch already in flight", social_account_id=event.social_account_id)
        return

    try:
        async with session_factory() as session:
            cfg = await settings_provider.get_rank_collection_config(session)

            if await redis_client.get(COOLDOWN_KEY):
                await service.defer_tag(
                    session,
                    social_account_id=event.social_account_id,
                    delay_seconds=cfg.backoff_base_seconds,
                )
                await session.commit()
                return

            if not await _allow_request(redis_client, cfg.rate_limit_per_minute):
                await asyncio.sleep(min(2.0, 60.0 / max(cfg.rate_limit_per_minute, 1)))

            lookup, version = await mapping.get_rank_mapping(session)

            try:
                result = await client.fetch_summary(event.battle_tag)
            except OverFastRateLimited as exc:
                await redis_client.set(COOLDOWN_KEY, "1", ex=int(exc.retry_after or 60))
                await service.record_failure(
                    session,
                    social_account_id=event.social_account_id,
                    battle_tag=event.battle_tag,
                    status=enums.RankCollectionStatus.rate_limited,
                    error="429 rate limited",
                    config=cfg,
                    transient=True,
                )
                await service.log_fetch(
                    session,
                    social_account_id=event.social_account_id,
                    battle_tag=event.battle_tag,
                    status=enums.RankCollectionStatus.rate_limited.value,
                    source=event.source,
                    error="429 rate limited",
                )
                await session.commit()
                return

            written = await service.record_result(
                session,
                social_account_id=event.social_account_id,
                battle_tag=event.battle_tag,
                source=event.source,
                result=result,
                lookup=lookup,
                mapping_version=version,
                config=cfg,
            )
            await service.log_fetch(
                session,
                social_account_id=event.social_account_id,
                battle_tag=event.battle_tag,
                status=result.status.value,
                source=event.source,
                error=result.error,
                snapshots_written=written,
            )
            await session.commit()
    except OverFastError as exc:
        logger.warning("OverFast error for {}: {}", event.battle_tag, exc)
        async with session_factory() as session:
            cfg = await settings_provider.get_rank_collection_config(session)
            await service.record_failure(
                session,
                social_account_id=event.social_account_id,
                battle_tag=event.battle_tag,
                status=enums.RankCollectionStatus.error,
                error=str(exc),
                config=cfg,
                transient=True,
            )
            await service.log_fetch(
                session,
                social_account_id=event.social_account_id,
                battle_tag=event.battle_tag,
                status=enums.RankCollectionStatus.error.value,
                source=event.source,
                error=str(exc),
            )
            await session.commit()
        raise
    finally:
        await redis_client.delete(inflight)
        await redis_client.delete(_pending_key(event.social_account_id))
