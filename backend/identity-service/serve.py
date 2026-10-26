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

from shared.messaging.config import STEAM_ACCOUNT_CHANGED_DLQ, WORKSPACE_MEMBER_CHANGED_DLQ
from shared.messaging.topology import declare_dead_letter_queue
from shared.observability import (
    make_rabbit_broker,
    observe_scheduled_job,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.quota import close as close_quota
from shared.quota import configure as configure_quota
from shared.services.scheduler import IntervalScheduler
from src.core import db
from src.core.config import settings
from src.core.redis import close_redis, init_redis
from src.core.s3 import s3_client
from src.rpc import api_keys, auth, avatars, oauth, players, rbac, steam_names, tokens, workspace_member_events
from src.services.oauth_accounts import oauth_accounts
from src.services.oauth_providers import close_http_client, oauth_providers
from src.services.security import token_codec
from src.services.session_cache import session_cache
from src.services.sessions import refresh_tokens
from src.services.steam_profiles import refresh_display_names

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

# The quota enforcer is a process-global with its own Redis client and session
# factory: ``src.core.redis``'s singleton is only created by the startup hook,
# after the first handler import. identity-service meters nothing; it configures
# the gate because its per-key limit writes and usage reads need the same resolver.
configure_quota(
    session_factory=db.async_session_maker,
    redis_url=settings.REDIS_URL,
    enabled=settings.quota_enabled,
    edge_workspace_metering=settings.quota_edge_workspace_metering,
)

# IDENTITY_RPC_ROLE splits the one image into processes: production runs "credentials" (password and OAuth RPCs:
# bcrypt and provider round trips) apart from "core" (validate_token's hot path and the rest), so a login burst cannot
# queue the gateway's token checks. Dev runs "all".
_ROLE_MODULES = {
    "credentials": (auth, oauth),
    "core": (tokens, api_keys, rbac, players, avatars, workspace_member_events, steam_names),
}
_ROLE_MODULES["all"] = _ROLE_MODULES["credentials"] + _ROLE_MODULES["core"]
# Schedulers and startup jobs run in "core" / "all" only.
_RUNS_JOBS = settings.IDENTITY_RPC_ROLE != "credentials"

for _module in _ROLE_MODULES[settings.IDENTITY_RPC_ROLE]:
    _module.register(broker, logger)

_purge_scheduler = IntervalScheduler(job_id="refresh_token_purge", label="Refresh-token purge", logger=logger)
_steam_names_scheduler = IntervalScheduler(
    job_id="steam_display_names", label="Steam display-name refresh", logger=logger
)


async def purge_expired_refresh_tokens() -> None:
    async with observe_scheduled_job("refresh_token_purge"), db.async_session_maker() as session:
        # Commits per batch of PURGE_BATCH_SIZE rows.
        deleted = await refresh_tokens.purge_expired(session, retention=REFRESH_TOKEN_RETENTION)
    if deleted:
        logger.info("Refresh-token purge: dropped {} rows expired before {}", deleted, REFRESH_TOKEN_RETENTION)


async def refresh_steam_display_names() -> None:
    """Every Steam account's persona name; the event-driven fetch (``steam_names``) covers new accounts between runs."""
    async with observe_scheduled_job("steam_display_names"), db.async_session_maker() as session:
        changed = await refresh_display_names(session, oauth_providers.http.client())
        await session.commit()
    logger.info("Steam display-name refresh: {} names changed", changed)


@app.on_startup
async def setup_worker() -> None:
    await broker.connect()
    await declare_dead_letter_queue(broker, WORKSPACE_MEMBER_CHANGED_DLQ)
    await declare_dead_letter_queue(broker, STEAM_ACCOUNT_CHANGED_DLQ)
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
    if _RUNS_JOBS:
        # Membership-change events expire in the queue after minutes; entries cached before a restart may have
        # missed their drop, so none of them is trusted.
        flushed = await session_cache.flush_rbac_cache()
        logger.info("RBAC cache flushed at startup: {} entries", flushed)
        # Seals Discord/Twitch tokens still stored in clear and drops the rest; refuses to start without the key.
        async with db.async_session_maker() as session:
            await oauth_accounts.seal_stored_tokens(session)
        _purge_scheduler.start(purge_expired_refresh_tokens, seconds=24 * 60 * 60)
        # ponytail: unlocked, every replica refreshes (idempotent writes, ~1 request per 100 accounts each); add a
        # leader lock if identity scales out far.
        _steam_names_scheduler.start(refresh_steam_display_names, seconds=24 * 60 * 60, run_now=True)
    # The gateway's JWT_PUBLIC_KEY must equal this (also `make jwt-public-key`).
    logger.info(
        "identity-svc started (role={}, JWT public key {})", settings.IDENTITY_RPC_ROLE, token_codec.public_key_b64
    )


@app.on_shutdown
async def teardown_worker() -> None:
    _purge_scheduler.shutdown()
    _steam_names_scheduler.shutdown()
    await s3_client.close()
    await close_http_client()
    await close_redis()
    # Its own connection pool, so ``close_redis`` above leaves it open.
    await close_quota()
