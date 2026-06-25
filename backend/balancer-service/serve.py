import asyncio
import json
from typing import Any

from faststream import FastStream
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
from src.core import db
from src.core.caching import configure_cache
from src.core.config import config
from src.rpc import admin as rpc_admin
from src.rpc import binary as rpc_binary
from src.rpc import config as rpc_config
from src.rpc import draft as rpc_draft
from src.rpc import jobs as rpc_jobs
from src.services.balancer.jobs import execute_balance_job
from src.services.draft.clock import draft_clock_supervisor

logger = setup_logging(
    service_name="balancer-svc",
    log_level=config.log_level,
    logs_root_path=config.logs_root_path,
    json_output=config.json_logging,
)

broker = make_rabbit_broker(config.rabbitmq_url, logger=logger)
app = FastStream(broker)

# The cashews singleton is process-global with no default backend; the HTTP app
# (main.py) configures it at import, the worker must do so before any RPC read
# path hits the cache (see lesson: cashews-worker-not-configured).
configure_cache()

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
        release=config.version,
        http_proxy=config.sentry_http_proxy_url,
        https_proxy=config.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="balancer-svc",
        otlp_endpoint=config.otlp_endpoint,
        enabled=config.tracing_enabled,
        sampler_name=config.otel_traces_sampler,
        sampler_arg=config.otel_traces_sampler_arg,
    )
    start_worker_metrics_server(config.worker_metrics_port)
    logger.info("Balancer worker started")


@app.on_startup
async def start_draft_clock() -> None:
    # Single server-authoritative clock owner per LIVE draft (guarded by a Redis
    # lock inside the loop, so multiple worker replicas are safe).
    redis = Redis.from_url(config.redis_url, decode_responses=True)
    asyncio.create_task(draft_clock_supervisor(db.async_session_maker, redis))
    logger.info("Draft clock supervisor started")


@app.on_shutdown
async def close_rpc_clients() -> None:
    # Gracefully close the draft realtime Redis client (worker-lifetime singleton).
    await rpc_draft.close()


@broker.subscriber(BALANCER_JOBS_QUEUE, decoder=_decode_balancer_message)
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
