"""RabbitMQ publishing + worker handler for OverFast rank fetches.

Topology: the scheduler (FastAPI process) publishes one ``FetchRankEvent`` per
due battle tag; the worker (serve_worker.py) consumes and performs the HTTP call. Redis
provides per-tag enqueue/in-flight dedup, a global per-minute ceiling (over it, a
tag is deferred past the window rather than fetched) and a 429 cooldown so a
fleet of workers can't overrun the self-hosted OverFast instance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from shared.clients.circuit_breaker import CircuitBreakerOpen
from shared.core import enums
from shared.core.social import SocialProvider
from shared.messaging.config import RANK_FETCH_PRIORITY_QUEUE, RANK_FETCH_QUEUE
from shared.observability import publish_message
from shared.observability.broker import require_broker
from shared.schemas.events import FetchRankEvent, PlayerRefreshRequestedEvent
from shared.services.settings_provider import settings_provider

from . import runtime, service
from .client import OverFastError, OverFastRankClient, OverFastRateLimited
from .settings import settings

PENDING_TTL_SECONDS = 15 * 60
INFLIGHT_TTL_SECONDS = 180
COOLDOWN_KEY = "ow_rank:cooldown"

rank_client = OverFastRankClient(
    base_url=settings().overfast_base_url,
    timeout=settings().overfast_timeout,
    max_retries=settings().overfast_max_retries,
)


def _pending_key(social_account_id: int) -> str:
    return f"ow_rank:fetch:pending:{social_account_id}"


def _inflight_key(social_account_id: int) -> str:
    return f"ow_rank:fetch:inflight:{social_account_id}"


async def _set_once(redis: Any, key: str, ttl_seconds: int) -> bool:
    return bool(await redis.set(key, "1", nx=True, ex=ttl_seconds))


async def _reserve_slot(redis: Any, limit: int) -> int:
    """Fixed-window per-minute limiter.

    Returns 0 when the caller may proceed, otherwise the seconds until the
    current window resets. A non-positive ``limit`` disables the limiter
    (pass-through), matching the convention used by the gateway's limiters.

    The counter keeps incrementing on rejection: the window is already full, so
    the extra INCRs cost one round-trip and cannot let a request slip through.
    """
    if limit <= 0:
        return 0
    now = datetime.now(UTC).timestamp()
    key = f"ow_rank:rl:{int(now // 60)}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 70)
    if count <= limit:
        return 0
    return max(1, int(60 - (now % 60)))


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
    redis_client = redis or runtime.redis()
    pending = _pending_key(event.social_account_id)
    if force:
        await redis_client.set(pending, "1", ex=PENDING_TTL_SECONDS)
    elif not await _set_once(redis_client, pending, PENDING_TTL_SECONDS):
        return False

    queue = RANK_FETCH_PRIORITY_QUEUE if priority else RANK_FETCH_QUEUE
    try:
        await publish_message(
            require_broker(broker or runtime.broker()),
            event.model_dump(),
            queue,
            logger=logger.bind(social_account_id=event.social_account_id, source=event.source),
        )
    except Exception:
        await redis_client.delete(pending)
        raise
    return True


async def handle_player_refresh(
    data: dict[str, Any],
    *,
    broker: Any | None = None,
    redis: Any | None = None,
    session_factory: Any | None = None,
) -> int:
    """On an Overwatch player refresh (registration approved or re-checked, mix signup),
    prioritize + enqueue a rank check for the player.

    Reference-only: snapshots are stored for admin display; the player's declared
    registration rank is never overwritten. Another game's request is skipped.
    Returns the number of tags enqueued.
    """
    event = PlayerRefreshRequestedEvent.model_validate(data)
    if event.discipline != service.DISCIPLINE:
        return 0

    session_factory = session_factory or runtime.session_factory()
    async with session_factory() as session:
        cfg = await settings_provider.get_rank_collection_config(session)
        # Only the registered pool (main + smurfs) + up to N extra accounts —
        # not every battle tag the registrant owns.
        tags = await service.resolve_registration_targets(
            session,
            registration_id=event.registration_id,
            fallback_battle_tag=event.identity.handle
            if event.identity and event.identity.provider == SocialProvider.BATTLENET
            else None,
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
        )
        if await enqueue_fetch(fetch, priority=True, broker=broker, redis=redis):
            enqueued += 1
    return enqueued


async def process_fetch_rank(
    data: dict[str, Any],
    *,
    redis: Any | None = None,
    client: OverFastRankClient | None = None,
    session_factory: Any | None = None,
) -> None:
    """Handle one fetch event: rate-limit, call OverFast, persist snapshot/state."""
    event = FetchRankEvent.model_validate(data)
    redis_client = redis or runtime.redis()
    session_factory = session_factory or runtime.session_factory()
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

            # Over the per-minute ceiling: push the tag past the window and let
            # the scheduler re-enqueue it rather than issuing the request anyway.
            # This is the only rate control on the priority queue (registration
            # approvals bypass the scheduler's per-tick pacing). Not written to
            # fetch_log: self-throttling is not an upstream failure and the
            # admin error rate counts `rate_limited` rows as errors.
            retry_after = await _reserve_slot(redis_client, cfg.rate_limit_per_minute)
            if retry_after:
                await service.defer_tag(
                    session,
                    social_account_id=event.social_account_id,
                    delay_seconds=retry_after,
                )
                await session.commit()
                logger.info(
                    "OverFast rank fetch deferred: over {}/min, retry in {}s",
                    cfg.rate_limit_per_minute,
                    retry_after,
                )
                return

        # The OverFast call runs with no DB transaction open. A session held
        # across this await sits idle-in-transaction for the call's full
        # duration; a slow/timed-out upstream response can outlast the server's
        # idle_in_transaction_session_timeout=30s, which kills the connection
        # server-side, and the session's close()/rollback then hits an
        # already-closed connection.
        try:
            result = await client.fetch_summary(event.battle_tag)
        except OverFastRateLimited as exc:
            await redis_client.set(COOLDOWN_KEY, "1", ex=int(exc.retry_after or 60))
            async with session_factory() as session:
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

        async with session_factory() as session:
            written = await service.record_result(
                session,
                social_account_id=event.social_account_id,
                battle_tag=event.battle_tag,
                source=event.source,
                result=result,
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
    except (OverFastError, CircuitBreakerOpen) as exc:
        # Transient upstream failure (OverFast 5xx / timeout, or the breaker
        # holding the door shut while it is down). It is fully handled here:
        # recorded with exponential backoff (transient=True never disables the
        # tag) and logged. Retries are scheduler-driven via ``next_eligible_at`` — the
        # message needs no RabbitMQ redelivery, so we swallow it instead of re-raising.
        # Re-raising would escalate an expected outage to a FastStream/Sentry error
        # and, for CircuitBreakerOpen, bury every message of the outage in rank_fetch.dlq.
        logger.warning("OverFast fetch failed for {} via {}: {}", event.battle_tag, rank_client.base_url, exc)
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
    finally:
        await redis_client.delete(inflight)
        await redis_client.delete(_pending_key(event.social_account_id))
