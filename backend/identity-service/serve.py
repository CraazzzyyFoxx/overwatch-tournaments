"""identity-svc: headless FastStream worker exposing identity RPC methods.

The Go gateway calls these over RabbitMQ request-reply (reply_to + correlation_id);
a handler simply returns the reply envelope and FastStream answers automatically.

This module is the entrypoint and nothing else: logging/tracing/metrics, the
broker, the lifespan hooks, and one ``register(broker, logger)`` call per
transport module. The handlers themselves live in ``src/rpc/<domain>.py``; every
authorization decision, query and error message belongs to ``src/services/**``.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta

from faststream import FastStream

from shared.observability import (
    make_rabbit_broker,
    observe_scheduled_job,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.services.scheduler import IntervalScheduler
from src.core import db
from src.core.config import settings
from src.core.redis import close_redis, init_redis
from src.core.s3 import s3_client
from src.rpc import api_keys, auth, avatars, oauth, players, rbac, tokens
from src.services.oauth_providers import close_http_client
from src.services.sessions import refresh_tokens

# Rotation writes a refresh-token row per refresh and revocation only flags it,
# so the table grows for as long as nobody deletes. Nothing authenticates
# against an expired row; a month past expiry keeps the session-history lists
# meaningful and lets the row go.
REFRESH_TOKEN_RETENTION = timedelta(days=30)


def _install_uvloop() -> None:
    """Swap in uvloop where it ships (see the `platform_system == 'Linux'` dep marker)."""
    if sys.platform != "linux":
        return
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


logger = setup_logging(
    service_name="identity-svc",
    log_level=settings.log_level,
    logs_root_path=settings.logs_root_path,
    json_output=settings.json_logging,
)

_install_uvloop()

broker = make_rabbit_broker(settings.rabbitmq_url, logger=logger, prefetch_count=settings.rpc_prefetch_count)
app = FastStream(broker)

for _module in (tokens, auth, oauth, api_keys, rbac, players, avatars):
    _module.register(broker, logger)

_purge_scheduler = IntervalScheduler(job_id="refresh_token_purge", label="Refresh-token purge", logger=logger)


async def purge_expired_refresh_tokens() -> None:
    async with observe_scheduled_job("refresh_token_purge"), db.async_session_maker() as session:
        deleted = await refresh_tokens.purge_expired(session, retention=REFRESH_TOKEN_RETENTION)
        await session.commit()
    if deleted:
        logger.info("Refresh-token purge: dropped {} rows expired before {}", deleted, REFRESH_TOKEN_RETENTION)


@app.on_startup
async def setup_worker() -> None:
    setup_sentry(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        service_name="identity-svc",
        enable_logs=settings.sentry_enable_logs,
        logs_level=settings.sentry_logs_level,
        enable_metrics=settings.sentry_enable_metrics,
        environment=settings.environment,
        release=settings.sentry_release,
        http_proxy=settings.sentry_http_proxy_url,
        https_proxy=settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="identity-svc",
        otlp_endpoint=settings.otlp_endpoint,
        enabled=settings.tracing_enabled,
        sampler_name=settings.otel_traces_sampler,
        sampler_arg=settings.otel_traces_sampler_arg,
        environment=settings.environment,
        release=settings.sentry_release,
        engine=db.async_engine,
    )
    if settings.worker_metrics_port:
        start_worker_metrics_server(settings.worker_metrics_port)
    await init_redis()
    await s3_client.start()
    _purge_scheduler.start(purge_expired_refresh_tokens, seconds=24 * 60 * 60)
    logger.info("identity-svc started")


@app.on_shutdown
async def teardown_worker() -> None:
    _purge_scheduler.shutdown()
    await s3_client.close()
    await close_http_client()
    await close_redis()
