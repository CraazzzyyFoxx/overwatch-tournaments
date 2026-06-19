"""Lightweight headless RPC worker for analytics reads + job-control.

Hosts every ``rpc.analytics.*`` subscriber (public/auth reads, light
mutations, and job-control that enqueues to the heavy worker). The heavy ML
compute stays in ``serve.py`` (``analytics-worker``); this process must NOT
import ``serve`` or subscribe to the ``ANALYTICS_*`` job queues, or those
queues would be double-owned (messages would round-robin between processes).

Run with: ``faststream run serve_rpc:app``.
"""

from faststream import FastStream
from faststream.rabbit import RabbitBroker
from shared.observability import (
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)

from src.core import config
from src.rpc import jobs_control, mutations
from src.rpc import reads as rpc_reads

logger = setup_logging(
    service_name="analytics-svc",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

broker = RabbitBroker(config.settings.rabbitmq_url, logger=logger)
app = FastStream(broker)

# Typed read + mutation + job-control RPC methods served by the gateway
# (rpc.analytics.*). The heavy job queues are NOT registered here.
rpc_reads.register(broker, logger)
mutations.register(broker, logger)
jobs_control.register(broker, logger)


@app.on_startup
async def start_worker() -> None:
    await broker.connect()
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="analytics-svc",
        enable_logs=config.settings.sentry_enable_logs,
        logs_level=config.settings.sentry_logs_level,
        enable_metrics=config.settings.sentry_enable_metrics,
        environment=config.settings.environment,
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="analytics-svc",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
    )
    if config.settings.worker_metrics_port is not None:
        start_worker_metrics_server(config.settings.worker_metrics_port)
    logger.info("Analytics RPC service (analytics-svc) started")
