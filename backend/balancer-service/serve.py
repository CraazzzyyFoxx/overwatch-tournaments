import asyncio
import contextlib
import json
from typing import Any

from faststream import FastStream
from faststream.rabbit import Channel
from faststream.rabbit.annotations import RabbitMessage
from pydantic import ValidationError
from redis.asyncio import Redis

from shared.messaging.config import BALANCER_JOBS_QUEUE
from shared.observability import (
    make_rabbit_broker,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.schemas.events import BalancerJobEvent
from shared.services.realtime import configure_realtime
from src.core import db
from src.core.caching import configure_cache
from src.core.config import config
from src.core.job_store import close_job_store
from src.core.security.api_key_limiter import close_api_key_limiter
from src.rpc import admin as rpc_admin
from src.rpc import binary as rpc_binary
from src.rpc import config as rpc_config
from src.rpc import custom as rpc_custom
from src.rpc import draft as rpc_draft
from src.rpc import jobs as rpc_jobs
from src.rpc import players as rpc_players
from src.services.balancer.jobs import execute_balance_job
from src.services.draft.clock import draft_clock_service

logger = setup_logging(
    service_name="balancer-svc",
    log_level=config.log_level,
    logs_root_path=config.logs_root_path,
    json_output=config.json_logging,
)

broker = make_rabbit_broker(config.rabbitmq_url, logger=logger, prefetch_count=config.rpc_prefetch_count)
app = FastStream(broker)

# The cashews singleton is process-global with no default backend; the HTTP app
# (main.py) configures it at import, the worker must do so before any RPC read
# path hits the cache (see lesson: cashews-worker-not-configured).
configure_cache()
# Same reason, same place: the realtime rail is a process-global too, and every
# `emit` in this worker is a no-op until it knows where to publish. No
# `cache_invalidator` — balancer-service keeps no cashews table of its own, so
# there is nothing local to drop before the publish.
configure_realtime(redis_url=config.redis_url)

# Typed-RPC subscribers replacing the HTTP balancer-service behind the Go gateway.
# Phase 1 — public config read + admin balance/config writes + teams import.
rpc_config.register(broker, logger)
rpc_admin.register(broker, logger)
rpc_binary.register(broker, logger)
# Phase 2 — live draft (public reads + lifecycle + pick actions).
rpc_draft.register(broker, logger)
# Phase 3 — public job API (create + status + result; create publishes to the
# job queue this same worker consumes). The SSE stream is not migrated.
rpc_jobs.register(broker, logger)
rpc_custom.register(broker, logger)
rpc_players.register(broker, logger)


# Balance jobs run for minutes (MOO solver); isolate them from the RPC channel.
_JOBS_CHANNEL = Channel(prefetch_count=2)


def _decode_balancer_message(message: Any) -> Any:
    body = getattr(message, "body", None)

    if isinstance(body, bytes):
        return json.loads(body.decode("utf-8"))

    if isinstance(body, bytearray):
        return json.loads(bytes(body).decode("utf-8"))

    return body


@app.on_startup
async def setup_worker_observability() -> None:
    setup_sentry(
        dsn=config.sentry_dsn,
        traces_sample_rate=config.sentry_traces_sample_rate,
        profiles_sample_rate=config.sentry_profiles_sample_rate,
        service_name="balancer-svc",
        enable_logs=config.sentry_enable_logs,
        logs_level=config.sentry_logs_level,
        enable_metrics=config.sentry_enable_metrics,
        environment=config.environment,
        release=config.sentry_release,
        http_proxy=config.sentry_http_proxy_url,
        https_proxy=config.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="balancer-svc",
        otlp_endpoint=config.otlp_endpoint,
        enabled=config.tracing_enabled,
        sampler_name=config.otel_traces_sampler,
        sampler_arg=config.otel_traces_sampler_arg,
        environment=config.environment,
        release=config.sentry_release,
        engine=db.async_engine,
    )
    start_worker_metrics_server(config.worker_metrics_port)
    logger.info("Balancer worker started")


# The clock supervisor outlives every message, so its handle and its Redis client
# have to be reachable at shutdown. Left unanchored, asyncio's weak task
# reference let it be reclaimed ("Task was destroyed but it is pending!"), and
# nothing cancelled it before the loop closed -- so its in-flight asyncpg
# connection kept resolving/cancelling on a dead loop ("Event loop is closed").
_draft_clock_task: asyncio.Task[None] | None = None
_draft_clock_redis: Redis | None = None


@app.on_startup
async def start_draft_clock() -> None:
    global _draft_clock_task, _draft_clock_redis
    # Single server-authoritative clock owner per LIVE draft (guarded by a Redis
    # lock inside the loop, so multiple worker replicas are safe).
    _draft_clock_redis = Redis.from_url(config.redis_url, decode_responses=True)
    _draft_clock_task = asyncio.create_task(
        draft_clock_service.draft_clock_supervisor(db.async_session_maker, _draft_clock_redis)
    )
    logger.info("Draft clock supervisor started")


@app.on_shutdown
async def close_rpc_clients() -> None:
    # Gracefully close the draft realtime Redis client (worker-lifetime singleton).
    await rpc_draft.close()

    # Job-store and API-key-limiter Redis clients are process-global singletons
    # (see get_job_store/get_api_key_limiter); close them explicitly or every
    # worker restart leaks a connection.
    await close_job_store()
    await close_api_key_limiter()

    # Stop the clock BEFORE the engine goes: cancelling it lets its session unwind
    # on a live loop instead of being torn down after the loop is gone.
    if _draft_clock_task is not None:
        _draft_clock_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _draft_clock_task
    if _draft_clock_redis is not None:
        await _draft_clock_redis.aclose()
    await db.async_engine.dispose()


@broker.subscriber(BALANCER_JOBS_QUEUE, decoder=_decode_balancer_message, channel=_JOBS_CHANNEL)
async def process_balancer_job(data: dict, msg: RabbitMessage) -> None:
    try:
        event = BalancerJobEvent.model_validate(data)
    except ValidationError as exc:
        logger.error(f"Invalid balancer job payload: {exc}")
        return

    try:
        await execute_balance_job(event.job_id)
        logger.success(f"Balancer job completed: {event.job_id}")
    except Exception as exc:  # pragma: no cover - defensive worker guard
        logger.exception(f"Balancer job failed ({event.job_id}): {exc}")
        raise
