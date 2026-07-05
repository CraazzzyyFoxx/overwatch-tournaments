import time

from faststream import FastStream
from faststream.rabbit.annotations import RabbitMessage
from redis.asyncio import Redis
from shared.messaging.config import (
    ANALYTICS_INFER_QUEUE,
    ANALYTICS_JOB_QUEUE,
    ANALYTICS_TRAIN_QUEUE,
)
from shared.observability import (
    make_rabbit_broker,
    metrics,
    observe_message_processing,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.schemas.events import (
    AnalyticsInferRequest,
    AnalyticsJobRequested,
    AnalyticsTrainRequest,
)

from src.core import config, db
from src.scheduler import register_jobs
from src.services.jobs.runner import run_job
from src.services.ml.inference.runner import run_for_tournament
from src.services.ml.training.orchestrator import train_all_models
from src.worker import balance_snapshot

logger = setup_logging(
    service_name="analytics-worker",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

broker = make_rabbit_broker(config.settings.rabbitmq_url, logger=logger)
app = FastStream(broker)
scheduler = register_jobs()
redis_client: Redis | None = None

# Domain-event consumer: analytics owns the writes to analytics.balance_snapshot
# + balance_player_snapshot; balancer-service emits balance_exported via its outbox.
balance_snapshot.register(broker, logger)


@app.on_startup
async def start_worker() -> None:
    global redis_client
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="analytics-worker",
        enable_logs=config.settings.sentry_enable_logs,
        logs_level=config.settings.sentry_logs_level,
        enable_metrics=config.settings.sentry_enable_metrics,
        environment=config.settings.environment,
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="analytics-worker",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
    )
    if config.settings.worker_metrics_port is not None:
        start_worker_metrics_server(config.settings.worker_metrics_port)
    # Redis is used to publish analytics_job realtime envelopes for the
    # gateway WS fan-out. Missing/broken Redis degrades to "no
    # progress events", not an outright failure.
    try:
        redis_client = Redis.from_url(str(config.settings.redis_url))
        await redis_client.ping()
    except Exception:
        logger.exception("Failed to connect to Redis; realtime events disabled")
        redis_client = None
    scheduler.start()
    logger.info("Analytics worker started")


@app.on_shutdown
async def stop_worker() -> None:
    scheduler.shutdown(wait=False)
    if redis_client is not None:
        try:
            await redis_client.aclose()
        except Exception:
            logger.exception("Failed to close Redis client")
    logger.info("Analytics worker stopped")


@broker.subscriber(ANALYTICS_JOB_QUEUE)
async def consume_analytics_job(data: dict, msg: RabbitMessage) -> None:
    """Single dispatcher for the unified analytics-job pipeline.

    Replaces the v1 ``Recalculate`` + v2 ``Train ML`` + v2 ``Run inference``
    consumers. Looks up the persisted :class:`AnalyticsJob` row by id,
    dispatches by ``kind``, and publishes progress events to the
    ``workspace:{id}:analytics_jobs`` realtime topic.
    """
    async with observe_message_processing(
        queue=ANALYTICS_JOB_QUEUE,
        handler="consume_analytics_job",
        message=msg,
        logger=logger,
    ):
        event = AnalyticsJobRequested.model_validate(data)
        logger.bind(job_id=event.job_id).info("Consuming analytics job")
        async with db.async_session_maker() as session:
            await run_job(session, redis_client, event.job_id)


@broker.subscriber(ANALYTICS_TRAIN_QUEUE)
async def consume_train_request(data: dict, msg: RabbitMessage) -> None:
    """Run :func:`train_all_models` for the cutoff carried in the message.

    Training can take many minutes (especially for backfills), so the HTTP
    endpoint dispatches via this queue and returns 202 immediately.
    """
    async with observe_message_processing(
        queue=ANALYTICS_TRAIN_QUEUE,
        handler="consume_train_request",
        message=msg,
        logger=logger,
    ):
        event = AnalyticsTrainRequest.model_validate(data)
        logger.bind(
            cutoff_tournament_id=event.cutoff_tournament_id,
            model_kinds=event.model_kinds,
            workspace_id=event.workspace_id,
        ).info("Running v2 ML training job")
        async with db.async_session_maker() as session:
            summary = await train_all_models(
                session,
                cutoff_tournament_id=event.cutoff_tournament_id,
                model_kinds=event.model_kinds,
                workspace_id=event.workspace_id,
                workspace_ids=event.workspace_ids,
            )
            await session.commit()
        logger.bind(summary=summary).info("v2 ML training job complete")


@broker.subscriber(ANALYTICS_INFER_QUEUE)
async def consume_infer_request(data: dict, msg: RabbitMessage) -> None:
    """Run :func:`run_for_tournament` for the tournament in the message."""
    async with observe_message_processing(
        queue=ANALYTICS_INFER_QUEUE,
        handler="consume_infer_request",
        message=msg,
        logger=logger,
    ):
        event = AnalyticsInferRequest.model_validate(data)
        logger.bind(
            tournament_id=event.tournament_id,
            model_kinds=event.model_kinds,
            workspace_id=event.workspace_id,
        ).info("Running v2 ML inference job")
        started_at = time.perf_counter()
        async with db.async_session_maker() as session:
            summary = await run_for_tournament(
                session,
                event.tournament_id,
                workspace_id=event.workspace_id,
                model_kinds=event.model_kinds,
            )
        metrics.distribution(
            "analytics.inference.duration",
            (time.perf_counter() - started_at) * 1000,
            unit="millisecond",
            attributes={"tournament_id": event.tournament_id},
        )
        logger.bind(summary=summary).info("v2 ML inference job complete")


# Subscribers (recalculate-on-event handlers) are wired in
# src.worker.handlers — they will be imported here once the v1 analytics
# module is moved over in the next Phase 0 step.
