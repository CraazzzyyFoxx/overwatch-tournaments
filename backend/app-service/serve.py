"""Headless RPC worker for app-service (app-svc).

Hosts every ``rpc.app.*`` subscriber (public reads via the shared CRUD read
engine + bespoke reads, workspace writes, binary base64 endpoints) plus the
``tournament_changed`` cache-invalidation consumer. Replaces the HTTP
app-service (compose ``backend``) behind the Go gateway.

Run with: ``faststream run serve:app``.
"""

from cashews import cache
from faststream import FastStream

from shared.observability import (
    make_rabbit_broker,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from src.core import config, db
from src.core.caching import configure_cache
from src.rpc import (
    _clients,
    achievements,
    admin_crud,
    binary,
    gamemodes,
    heroes,
    maps,
    metadata_admin,
    reads_generic,
    statistics,
    users,
    users_admin,
    workspaces,
)
from src.services import hero_stats_refresh, tournament_events

logger = setup_logging(
    service_name="app-svc",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

broker = make_rabbit_broker(config.settings.rabbitmq_url, logger=logger)
app = FastStream(broker)

# The cashews singleton is process-global and has no default backend. The
# @cache-decorated flows AND the tournament_changed invalidation consumer both
# raise NotConfiguredError without this — call it before any subscriber runs.
configure_cache()

# Cache-invalidation consumer (single owner of TOURNAMENT_CHANGED_APP_QUEUE).
tournament_events.register(broker, logger)

# Phase 1 — public reads.
# hero/map/gamemode/achievement get+list via the shared CRUD read engine:
reads_generic.register(broker, logger)
# bespoke reads (aggregations, lookups, users/*) + workspace reads/writes/members:
for _mod in (users, heroes, maps, gamemodes, achievements, statistics, workspaces):
    _mod.register(broker, logger)

# Phase 2 — workspace update/delete via the shared CRUD engine.
admin_crud.register(broker, logger)

# Game-metadata admin CRUD (hero/map/gamemode), relocated from parser-service.
metadata_admin.register(broker, logger)

# User + identity admin CRUD, profile merge, avatar, CSV import (from parser-service).
users_admin.register(broker, logger)

# Phase 3 — binary/multipart endpoints (icons, assets, match-log) over base64.
binary.register(broker, logger)


@app.on_startup
async def start_worker() -> None:
    await broker.connect()
    await _clients.s3_client.start()
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="app-svc",
        enable_logs=config.settings.sentry_enable_logs,
        logs_level=config.settings.sentry_logs_level,
        enable_metrics=config.settings.sentry_enable_metrics,
        environment=config.settings.environment,
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="app-svc",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
    )
    if config.settings.worker_metrics_port is not None:
        start_worker_metrics_server(config.settings.worker_metrics_port)
    # Drop stale cache on (re)deploy, mirroring the HTTP service lifespan.
    await cache.delete_match("fastapi:*")
    await cache.delete_match("backend:*")
    # Kick off the initial build of the hero global-stats materialized view as a
    # debounced background task — never blocks startup or the event consumer.
    hero_stats_refresh.request_refresh(db.async_session_maker, logger)
    logger.info("App RPC service (app-svc) started")


@app.on_shutdown
async def stop_worker() -> None:
    await _clients.s3_client.close()
