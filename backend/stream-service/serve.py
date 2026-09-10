"""Headless worker for tournament stream live-status.

Hosts every ``rpc.stream.*`` subscriber (the public tournament-streams read and
the admin re-poll) and runs the APScheduler Twitch poll tick in the same
process. One process is enough: the tick is Redis leader-locked, so extra
replicas add RPC capacity without multi-firing the poller.

The service owns no Postgres schema. Live status lives in Redis
(``stream:live:{tournament_id}``) with a TTL — everything it reads from
``tournament.*`` / ``players.*`` / ``balancer.*`` is read-only, and the only row
it ever writes is an audit entry for the admin re-poll.

Run with: ``faststream run serve:app``.
"""

from faststream import FastStream

from shared.observability import (
    make_rabbit_broker,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.services.realtime import configure_realtime
from src.core import config, db
from src.core.broker import set_worker_broker
from src.rpc import admin as rpc_admin
from src.rpc import reads as rpc_reads
from src.services import scheduler as poll_scheduler

logger = setup_logging(
    service_name="stream-svc",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

broker = make_rabbit_broker(
    config.settings.rabbitmq_url, logger=logger, prefetch_count=config.settings.rpc_prefetch_count
)
app = FastStream(broker)

# The poll tick publishes the `stream.updated` realtime envelope from outside any
# subscriber, so it resolves the connected broker through src.core.broker rather
# than being handed one.
set_worker_broker(broker)

# The poll tick stages its stream.updated / tournament.streams events through
# shared/services/realtime, which has no settings of its own.
configure_realtime(redis_url=str(config.settings.redis_url))

rpc_reads.register(broker, logger)
rpc_admin.register(broker, logger)


@app.on_startup
async def start_worker() -> None:
    await broker.connect()
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="stream-svc",
        enable_logs=config.settings.sentry_enable_logs,
        logs_level=config.settings.sentry_logs_level,
        enable_metrics=config.settings.sentry_enable_metrics,
        environment=config.settings.environment,
        release=config.settings.sentry_release,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="stream-svc",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
        environment=config.settings.environment,
        release=config.settings.sentry_release,
        engine=db.async_engine,
    )
    if config.settings.worker_metrics_port is not None:
        start_worker_metrics_server(config.settings.worker_metrics_port)
    # Periodic Twitch live-status poll (Redis leader-locked across replicas,
    # admin-settings-gated — no-ops while `stream.collection.enabled` is false).
    poll_scheduler.start_scheduler()
    logger.info("Stream service (stream-svc) started")


@app.on_shutdown
async def stop_worker() -> None:
    poll_scheduler.shutdown_scheduler()
