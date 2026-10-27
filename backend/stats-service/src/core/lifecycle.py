"""Setup, readiness and teardown the two stats processes share (``serve_rpc.py`` and ``serve_worker.py``).

Each process owns its broker, FastStream app and clients; this module holds only what would otherwise be written twice,
so neither entry point can drift on the order of startup or shutdown.
"""

from __future__ import annotations

from collections.abc import Awaitable, Iterable
from typing import Any

from faststream import FastStream

from shared.observability import (
    Readiness,
    make_rabbit_broker,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.quota import close as close_quota
from shared.quota import configure as configure_quota
from shared.services.realtime import configure_realtime
from src.core import config, db
from src.core.broker import set_worker_broker
from src.core.caching import configure_cache
from src.core.clients import realtime_redis, s3_client


def create_process(service_name: str, *, prefetch_count: int) -> tuple[Any, Any, FastStream]:
    """The logger, broker and app of one process, with the process-global wiring every handler of this service reads."""
    settings = config.settings
    logger = setup_logging(
        service_name=service_name,
        log_level=settings.log_level,
        logs_root_path=settings.logs_root_path,
        json_output=settings.json_logging,
    )
    broker = make_rabbit_broker(settings.rabbitmq_url, logger=logger, prefetch_count=prefetch_count)
    # Publishers that thread no broker through (the admin "collect now" RPC, the Challonge-import standings enqueue, the
    # achievement runner, ...) resolve this one.
    set_worker_broker(broker)
    # The cashews singleton is process-global with no default backend: configure it before any handler can read it.
    configure_cache()
    # shared/services/realtime has no settings of its own; every emit() in this process publishes through it.
    configure_realtime(redis_url=str(settings.redis_url))
    # Quota policy lives in the ``quota`` schema and consumption in Redis; the gate needs both before a metered call.
    configure_quota(
        session_factory=db.async_session_maker,
        redis_url=str(settings.redis_url),
        enabled=settings.quota_enabled,
        edge_workspace_metering=settings.quota_edge_workspace_metering,
    )
    return logger, broker, FastStream(broker)


def start_observability(service_name: str, readiness: Readiness) -> None:
    settings = config.settings
    setup_sentry(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        service_name=service_name,
        enable_logs=settings.sentry_enable_logs,
        logs_level=settings.sentry_logs_level,
        enable_metrics=settings.sentry_enable_metrics,
        environment=settings.environment,
        release=settings.sentry_release,
        http_proxy=settings.sentry_http_proxy_url,
        https_proxy=settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name=service_name,
        otlp_endpoint=settings.otlp_endpoint,
        enabled=settings.tracing_enabled,
        sampler_name=settings.otel_traces_sampler,
        sampler_arg=settings.otel_traces_sampler_arg,
        environment=settings.environment,
        release=settings.sentry_release,
        engine=db.async_engine,
    )
    start_worker_metrics_server(settings.worker_metrics_port, ready=readiness)


async def start_clients() -> None:
    await s3_client.start()


async def close_clients(pending: Iterable[Awaitable[None]] = ()) -> None:
    """Close what the process opened, once its consumers have drained.

    ``pending`` are the close-awaitables modules handed back when shutdown began (their HTTP clients).
    """
    await s3_client.close()
    for closing in pending:
        await closing
    await realtime_redis.aclose()
    # The quota gate holds its own process-global Redis client (see shared.quota.configure); every restart leaks a
    # connection without this.
    await close_quota()
