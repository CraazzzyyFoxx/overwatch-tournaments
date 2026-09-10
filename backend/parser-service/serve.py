import base64

import sqlalchemy as sa
from faststream import FastStream
from faststream.rabbit import Channel
from faststream.rabbit.annotations import RabbitMessage

from shared.core.social import SocialProvider, normalize_social_handle
from shared.messaging.config import (
    ACHIEVEMENT_EVALUATE_DEFERRED_DLQ,
    ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE,
    ACHIEVEMENT_EVALUATE_DLQ,
    ACHIEVEMENT_EVALUATE_QUEUE,
    PROCESS_MATCH_LOG_DLQ,
    PROCESS_MATCH_LOG_QUEUE,
    PROCESS_TOURNAMENT_LOGS_DLQ,
    PROCESS_TOURNAMENT_LOGS_QUEUE,
    RANK_FETCH_DLQ,
    RANK_FETCH_PRIORITY_DLQ,
    RANK_FETCH_PRIORITY_QUEUE,
    RANK_FETCH_QUEUE,
    TOURNAMENT_ENCOUNTER_COMPLETED_DLQ,
    TOURNAMENT_ENCOUNTER_COMPLETED_QUEUE,
    TOURNAMENT_EVENTS_EXCHANGE,
    TOURNAMENT_REGISTRATION_APPROVED_DLQ,
    TOURNAMENT_REGISTRATION_APPROVED_QUEUE,
    UPLOAD_MATCH_LOG_DLQ,
    UPLOAD_MATCH_LOG_QUEUE,
)
from shared.messaging.topology import declare_dead_letter_queue
from shared.models.ingestion.log_processing import LogProcessingSource
from shared.observability import (
    make_rabbit_broker,
    metrics,
    observe_message_processing,
    publish_message,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.schemas.events import (
    AchievementEvaluateEvent,
    EncounterCompletedEvent,
    ProcessMatchLogEvent,
    ProcessTournamentLogsEvent,
    UploadMatchLogEvent,
)
from shared.services.realtime import configure_realtime
from src import models
from src.clients.overfast import overfast_catalog_client
from src.core import config, db
from src.core.broker import set_worker_broker
from src.core.caching import configure_cache
from src.core.clients import realtime_redis, s3_client
from src.rpc import (
    achievements as rpc_achievements,
)
from src.rpc import (
    impact as rpc_impact,
)
from src.rpc import (
    logs as rpc_logs,
)
from src.rpc import (
    misc as rpc_misc,
)
from src.rpc import (
    rank as rpc_rank,
)
from src.rpc import (
    subscription as rpc_subscription,
)
from src.services.achievement.engine.consumer import (
    handle_achievement_evaluate,
    handle_achievement_evaluate_deferred,
)
from src.services.match_logs import flows as logs_flows
from src.services.match_logs import reaper as logs_reaper
from src.services.match_logs import uploads as upload_service
from src.services.match_logs.binary import binary_match_logs
from src.services.match_logs.result_events import publish_match_log_result
from src.services.overwatch_rank import scheduler as rank_scheduler
from src.services.overwatch_rank import tasks as rank_tasks
from src.services.subscription_collection import scheduler as subscription_scheduler

logger = setup_logging(
    service_name="parser-svc",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

broker = make_rabbit_broker(
    config.settings.rabbitmq_url, logger=logger, prefetch_count=config.settings.rpc_prefetch_count
)
app = FastStream(broker)

# Background jobs stay off the RPC channel QoS.
_JOBS_CHANNEL = Channel(prefetch_count=2)
# process_match_log is the one minutes-long handler here, and a delivery that
# outlives RabbitMQ's consumer_timeout (30 minutes by default) gets its whole
# channel closed — taking every consumer sharing it down with it. Its own channel
# keeps that blast radius to itself: upload_match_log, process_tournament_logs
# and achievement_evaluate stay live.
_MATCH_LOG_CHANNEL = Channel(prefetch_count=2)
# OverFast-protective prefetch (existing setting, previously unwired).
_RANK_FETCH_CHANNEL = Channel(prefetch_count=config.settings.rank_fetch_worker_prefetch)
# Deferred achievement recompute for unverified workspaces: a full-history run
# an operator asked for, on a workspace nobody has vouched for. One at a time,
# so it can never crowd out the parse-driven evaluations on _JOBS_CHANNEL.
_ACHIEVEMENT_DEFERRED_CHANNEL = Channel(prefetch_count=1)

# Dead-letter queues this worker owns. Every queue it consumes carries
# x-dead-letter-exchange=dlx plus an x-message-ttl, but nothing declared these or
# bound them to the DLX — so an expired job (a batch upload the worker could not
# chew inside the 5-minute process_match_log TTL) was routed to `dlx` with a
# routing key nothing was bound to and dropped without a trace. The log row kept
# saying "Queued" and there was no DLQ to prove why.
_OWNED_DLQS = (
    UPLOAD_MATCH_LOG_DLQ,
    PROCESS_MATCH_LOG_DLQ,
    PROCESS_TOURNAMENT_LOGS_DLQ,
    ACHIEVEMENT_EVALUATE_DLQ,
    ACHIEVEMENT_EVALUATE_DEFERRED_DLQ,
    RANK_FETCH_DLQ,
    RANK_FETCH_PRIORITY_DLQ,
    TOURNAMENT_ENCOUNTER_COMPLETED_DLQ,
    TOURNAMENT_REGISTRATION_APPROVED_DLQ,
)

# Expose the worker broker to publishers that don't thread one through (the
# APScheduler rank tick, the admin "collect now" RPC, the Challonge-import
# standings-recalculation enqueue, ...). Replaces the old task_router.broker
# fallback now that the fastapi RabbitRouter is gone.
set_worker_broker(broker)

# The cashews singleton is process-global with no default backend; configure it
# before any subscriber runs so cache reads/invalidation are routable.
configure_cache()

# Same reason and same place as configure_cache: shared/services/realtime has no
# settings of its own, and every emit() in this process publishes through it.
configure_realtime(redis_url=str(config.settings.redis_url))

# Typed-RPC subscribers for parser-unique domains served behind the gateway.
rpc_logs.register(broker, logger)
rpc_rank.register(broker, logger)
rpc_achievements.register(broker, logger)
rpc_misc.register(broker, logger)
rpc_impact.register(broker, logger)
rpc_subscription.register(broker, logger)


@app.on_startup
async def start_worker() -> None:
    await broker.connect()
    for dlq in _OWNED_DLQS:
        await declare_dead_letter_queue(broker, dlq)
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="parser-svc",
        enable_logs=config.settings.sentry_enable_logs,
        logs_level=config.settings.sentry_logs_level,
        enable_metrics=config.settings.sentry_enable_metrics,
        environment=config.settings.environment,
        release=config.settings.sentry_release,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="parser-svc",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
        environment=config.settings.environment,
        release=config.settings.sentry_release,
        engine=db.async_engine,
    )
    start_worker_metrics_server(config.settings.worker_metrics_port)
    await s3_client.start()
    await overfast_catalog_client.start()
    await rank_tasks.rank_client.start()
    # Periodic OverFast rank collection trigger (Redis leader-locked across worker
    # replicas, admin-settings-gated — no-ops while collection is disabled). Lives
    # in the worker now that the HTTP service is decommissioned.
    rank_scheduler.start_scheduler()
    # Requeue match-log records the queue dropped (expired ProcessMatchLogEvent,
    # worker killed mid-parse). Redis leader-locked across worker replicas.
    logs_reaper.start_scheduler(redis=realtime_redis, broker=broker)
    subscription_scheduler.start_scheduler()
    logger.info("Parser worker started")


@app.on_shutdown
async def stop_worker() -> None:
    rank_scheduler.shutdown_scheduler()
    logs_reaper.shutdown_scheduler()
    subscription_scheduler.shutdown_scheduler()
    await s3_client.close()
    await overfast_catalog_client.close()
    await rank_tasks.rank_client.close()
    await rank_tasks.close_redis()
    await realtime_redis.aclose()


@broker.subscriber(UPLOAD_MATCH_LOG_QUEUE, channel=_JOBS_CHANNEL)
async def process_upload_match_log(data: dict, msg: RabbitMessage) -> None:
    """Ingest a bot-uploaded match log carried over RabbitMQ (base64), then queue it.

    Replaces the former direct ``POST /logs/{id}/upload`` HTTP call from the bot:
    store the file to S3 + upsert the LogProcessingRecord, then publish a
    ProcessMatchLogEvent so the normal processing path (and result delivery) runs.
    """
    async with observe_message_processing(
        queue=UPLOAD_MATCH_LOG_QUEUE,
        handler="process_upload_match_log",
        message=msg,
        logger=logger,
    ):
        event = UploadMatchLogEvent.model_validate(data)
        log = logger.bind(tournament_id=event.tournament_id, filename=event.filename)
        content = base64.b64decode(event.content_b64)

        async with db.async_session_maker() as session:
            uploader_user_id: int | None = None
            if event.uploader_discord_name:
                source = LogProcessingSource.discord
                uploader_user_id = await session.scalar(
                    sa.select(models.SocialAccount.user_id)
                    .where(
                        models.SocialAccount.provider == SocialProvider.DISCORD,
                        models.SocialAccount.username_normalized
                        == normalize_social_handle(SocialProvider.DISCORD, event.uploader_discord_name),
                    )
                    .limit(1)
                )
            else:
                source = LogProcessingSource.manual

            await upload_service.store_uploaded_log_bytes(
                session,
                s3=s3_client,
                tournament_id=event.tournament_id,
                filename=event.filename,
                content=content,
                source=source,
                uploader_id=uploader_user_id,
            )

        await publish_message(
            broker,
            ProcessMatchLogEvent(tournament_id=event.tournament_id, filename=event.filename).model_dump(),
            PROCESS_MATCH_LOG_QUEUE,
            logger=log,
        )
        log.info("Uploaded match log ingested and queued for processing")


@broker.subscriber(PROCESS_MATCH_LOG_QUEUE, channel=_MATCH_LOG_CHANNEL)
async def process_match_log_async(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=PROCESS_MATCH_LOG_QUEUE,
        handler="process_match_log_async",
        message=msg,
        logger=logger,
    ):
        event = ProcessMatchLogEvent.model_validate(data)
        log = logger.bind(tournament_id=event.tournament_id, filename=event.filename)
        log.info("Processing match log from queue")

        # Process the log and report the outcome to the uploading bot. The result
        # is published exactly once per attempt, based solely on whether
        # process_match_log succeeded — the achievement evaluation below must not
        # flip it (and on retry the log is deduped, so it won't be reprocessed).
        try:
            async with db.async_session_maker() as session:
                await logs_flows.process_match_log(
                    session, event.tournament_id, event.filename, s3_client, is_raise=True
                )
        except Exception:
            await publish_match_log_result(broker, event.tournament_id, event.filename, "failed", logger=log)
            metrics.count("parser.match_log.processed", 1, attributes={"status": "failed"})
            log.exception(f"Failed to process match log tournament_id={event.tournament_id} filename={event.filename}")
            raise
        else:
            await publish_match_log_result(broker, event.tournament_id, event.filename, "done", logger=log)
            metrics.count("parser.match_log.processed", 1, attributes={"status": "done"})

        # Best-effort achievement evaluation (failure here retries the message).
        async with db.async_session_maker() as session:
            workspace_id = await session.scalar(
                sa.select(models.Tournament.workspace_id).where(models.Tournament.id == event.tournament_id)
            )
            if workspace_id is None:
                raise RuntimeError(f"Tournament {event.tournament_id} not found")
            achievement_event = AchievementEvaluateEvent(
                workspace_id=workspace_id,
                tournament_id=event.tournament_id,
                changed_tables=["matches.statistics", "matches.match", "tournament.encounter"],
            )
            await publish_message(
                broker,
                achievement_event.model_dump(),
                ACHIEVEMENT_EVALUATE_QUEUE,
                logger=log,
            )


@broker.subscriber(PROCESS_TOURNAMENT_LOGS_QUEUE, channel=_JOBS_CHANNEL)
async def process_tournament_log(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=PROCESS_TOURNAMENT_LOGS_QUEUE,
        handler="process_tournament_log",
        message=msg,
        logger=logger,
    ):
        event = ProcessTournamentLogsEvent.model_validate(data)
        logger.bind(tournament_id=event.tournament_id).info("Processing tournament logs from queue")
        try:
            async with db.async_session_maker() as session:
                tournament_exists = await session.scalar(
                    sa.select(models.Tournament.id).where(models.Tournament.id == event.tournament_id)
                )
                if tournament_exists is None:
                    raise RuntimeError(f"Tournament {event.tournament_id} not found")
                filenames = await binary_match_logs.get_logs_by_tournament(s3_client, event.tournament_id)

            # Fan out instead of parsing the whole tournament inline: an inline
            # loop holds one session (and one unacked delivery) for as long as it
            # takes to chew every file, which outruns RabbitMQ's consumer_timeout
            # and gets the delivery requeued — then dropped, because its 10-minute
            # TTL has long expired. Per-log messages ride the normal
            # process_match_log path, which is deduped, retried and reaped.
            for filename in filenames:
                await publish_message(
                    broker,
                    ProcessMatchLogEvent(tournament_id=event.tournament_id, filename=filename).model_dump(),
                    PROCESS_MATCH_LOG_QUEUE,
                    logger=logger.bind(tournament_id=event.tournament_id, filename=filename),
                )
            logger.info(f"Queued {len(filenames)} logs for tournament {event.tournament_id}.")
        except Exception:
            logger.exception(f"Failed to process tournament logs tournament_id={event.tournament_id}")
            raise


@broker.subscriber(ACHIEVEMENT_EVALUATE_QUEUE, channel=_JOBS_CHANNEL)
async def process_achievement_evaluate(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=ACHIEVEMENT_EVALUATE_QUEUE,
        handler="process_achievement_evaluate",
        message=msg,
        logger=logger,
    ):
        await handle_achievement_evaluate(data)


@broker.subscriber(ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE, channel=_ACHIEVEMENT_DEFERRED_CHANNEL)
async def process_achievement_evaluate_deferred(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE,
        handler="process_achievement_evaluate_deferred",
        message=msg,
        logger=logger,
    ):
        await handle_achievement_evaluate_deferred(data)


@broker.subscriber(TOURNAMENT_ENCOUNTER_COMPLETED_QUEUE, exchange=TOURNAMENT_EVENTS_EXCHANGE)
async def process_tournament_encounter_completed(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_ENCOUNTER_COMPLETED_QUEUE,
        handler="process_tournament_encounter_completed",
        message=msg,
        logger=logger,
    ):
        event = EncounterCompletedEvent.model_validate(data)
        async with db.async_session_maker() as session:
            workspace_id = await session.scalar(
                sa.select(models.Tournament.workspace_id).where(models.Tournament.id == event.tournament_id)
            )
            if workspace_id is None:
                raise RuntimeError(f"Tournament {event.tournament_id} not found")

        achievement_event = AchievementEvaluateEvent(
            workspace_id=workspace_id,
            tournament_id=event.tournament_id,
            changed_tables=["tournament.encounter"],
        )
        await publish_message(
            broker,
            achievement_event.model_dump(),
            ACHIEVEMENT_EVALUATE_QUEUE,
            logger=logger.bind(
                workspace_id=workspace_id,
                tournament_id=event.tournament_id,
                encounter_id=event.encounter_id,
            ),
        )


@broker.subscriber(RANK_FETCH_QUEUE, channel=_RANK_FETCH_CHANNEL)
async def process_rank_fetch(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=RANK_FETCH_QUEUE,
        handler="process_rank_fetch",
        message=msg,
        logger=logger,
    ):
        await rank_tasks.process_fetch_rank(data)


@broker.subscriber(RANK_FETCH_PRIORITY_QUEUE, channel=_RANK_FETCH_CHANNEL)
async def process_rank_fetch_priority(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=RANK_FETCH_PRIORITY_QUEUE,
        handler="process_rank_fetch_priority",
        message=msg,
        logger=logger,
    ):
        await rank_tasks.process_fetch_rank(data)


@broker.subscriber(TOURNAMENT_REGISTRATION_APPROVED_QUEUE, exchange=TOURNAMENT_EVENTS_EXCHANGE)
async def process_registration_approved_rank_check(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_REGISTRATION_APPROVED_QUEUE,
        handler="process_registration_approved_rank_check",
        message=msg,
        logger=logger,
    ):
        await rank_tasks.handle_registration_approved(data, broker=broker)
