import base64

import sqlalchemy as sa
from faststream import FastStream
from faststream.rabbit.annotations import RabbitMessage
from shared.messaging.config import (
    ACHIEVEMENT_EVALUATE_QUEUE,
    PROCESS_MATCH_LOG_QUEUE,
    PROCESS_TOURNAMENT_LOGS_QUEUE,
    RANK_FETCH_PRIORITY_QUEUE,
    RANK_FETCH_QUEUE,
    TOURNAMENT_ENCOUNTER_COMPLETED_QUEUE,
    TOURNAMENT_EVENTS_EXCHANGE,
    TOURNAMENT_REGISTRATION_APPROVED_QUEUE,
    UPLOAD_MATCH_LOG_QUEUE,
)
from shared.models.log_processing import LogProcessingSource
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

from src import models
from src.core import config, db
from src.core.broker import set_worker_broker
from src.core.caching import configure_cache
from src.rpc import (
    _clients,
    achievements as rpc_achievements,
    bootstrap as rpc_bootstrap,
    logs as rpc_logs,
    misc as rpc_misc,
    rank as rpc_rank,
)
from src.services.achievement.engine.consumer import handle_achievement_evaluate
from src.services.match_logs import flows as logs_flows
from src.services.match_logs import realtime as logs_realtime
from src.services.match_logs import uploads as upload_service
from src.services.match_logs.result_events import publish_match_log_result
from src.services.overwatch_rank import scheduler as rank_scheduler
from src.services.overwatch_rank import tasks as rank_tasks
from src.services.s3 import service as s3_service

logger = setup_logging(
    service_name="parser-svc",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

broker = make_rabbit_broker(config.settings.rabbitmq_url, logger=logger)
app = FastStream(broker)

# Expose the worker broker to publishers that don't thread one through (the
# APScheduler rank tick, the admin "collect now" RPC, the Challonge-import
# standings-recalculation enqueue, ...). Replaces the old task_router.broker
# fallback now that the fastapi RabbitRouter is gone.
set_worker_broker(broker)

# The cashews singleton is process-global with no default backend; configure it
# before any subscriber runs so cache reads/invalidation are routable.
configure_cache()

# Process-global S3 client shared with the match-log RPC/binary handlers.
s3_client = _clients.s3_client

# Typed-RPC subscribers for parser-unique domains served behind the gateway.
rpc_logs.register(broker, logger)
rpc_rank.register(broker, logger)
rpc_achievements.register(broker, logger)
rpc_misc.register(broker, logger)
rpc_bootstrap.register(broker, logger)


@app.on_startup
async def start_worker() -> None:
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="parser-svc",
        enable_logs=config.settings.sentry_enable_logs,
        logs_level=config.settings.sentry_logs_level,
        enable_metrics=config.settings.sentry_enable_metrics,
        environment=config.settings.environment,
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="parser-svc",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
    )
    start_worker_metrics_server(config.settings.worker_metrics_port)
    await s3_client.start()
    await rank_tasks.rank_client.start()
    # Periodic OverFast rank collection trigger (Redis leader-locked across worker
    # replicas, admin-settings-gated — no-ops while collection is disabled). Lives
    # in the worker now that the HTTP service is decommissioned.
    rank_scheduler.start_scheduler()
    logger.info("Parser worker started")


@app.on_shutdown
async def stop_worker() -> None:
    rank_scheduler.shutdown_scheduler()
    await s3_client.close()
    await rank_tasks.rank_client.close()
    await rank_tasks.close_redis()
    await _clients.realtime_redis.aclose()


@broker.subscriber(UPLOAD_MATCH_LOG_QUEUE)
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
                discord_user = await session.scalar(
                    sa.select(models.UserDiscord)
                    .where(models.UserDiscord.name == event.uploader_discord_name)
                    .limit(1)
                )
                if discord_user is not None:
                    uploader_user_id = discord_user.user_id
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


@broker.subscriber(PROCESS_MATCH_LOG_QUEUE)
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
            log.exception(
                f"Failed to process match log tournament_id={event.tournament_id} filename={event.filename}"
            )
            try:
                async with db.async_session_maker() as session:
                    failed_workspace_id = await session.scalar(
                        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == event.tournament_id)
                    )
                await logs_realtime.publish_logs_updated(_clients.realtime_redis, failed_workspace_id, reason="failed")
            except Exception:
                log.exception("Failed to emit logs.updated realtime signal")
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
            await logs_realtime.publish_logs_updated(_clients.realtime_redis, workspace_id, reason="done")
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


@broker.subscriber(PROCESS_TOURNAMENT_LOGS_QUEUE)
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
                for log in await s3_service.get_logs_by_tournament(s3_client, event.tournament_id):
                    await logs_flows.process_match_log(session, event.tournament_id, log, s3_client, is_raise=False)
            logger.info(f"All logs for tournament {event.tournament_id} are queued for processing.")
        except Exception:
            logger.exception(f"Failed to process tournament logs tournament_id={event.tournament_id}")
            raise


@broker.subscriber(ACHIEVEMENT_EVALUATE_QUEUE)
async def process_achievement_evaluate(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=ACHIEVEMENT_EVALUATE_QUEUE,
        handler="process_achievement_evaluate",
        message=msg,
        logger=logger,
    ):
        await handle_achievement_evaluate(data)


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


@broker.subscriber(RANK_FETCH_QUEUE)
async def process_rank_fetch(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=RANK_FETCH_QUEUE,
        handler="process_rank_fetch",
        message=msg,
        logger=logger,
    ):
        await rank_tasks.process_fetch_rank(data)


@broker.subscriber(RANK_FETCH_PRIORITY_QUEUE)
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
