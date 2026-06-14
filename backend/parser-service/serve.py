import sqlalchemy as sa
from faststream import FastStream
from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from shared.clients.s3 import S3Client
from shared.messaging.config import (
    ACHIEVEMENT_EVALUATE_QUEUE,
    PROCESS_MATCH_LOG_QUEUE,
    PROCESS_TOURNAMENT_LOGS_QUEUE,
    RANK_FETCH_PRIORITY_QUEUE,
    RANK_FETCH_QUEUE,
    TOURNAMENT_ENCOUNTER_COMPLETED_QUEUE,
    TOURNAMENT_EVENTS_EXCHANGE,
    TOURNAMENT_REGISTRATION_APPROVED_QUEUE,
)
from shared.observability import (
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
)

from src import models
from src.core import config, db
from src.services.achievement.engine.consumer import handle_achievement_evaluate
from src.services.match_logs import flows as logs_flows
from src.services.match_logs.result_events import publish_match_log_result
from src.services.overwatch_rank import tasks as rank_tasks
from src.services.s3 import service as s3_service

logger = setup_logging(
    service_name="parser-worker",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

broker = RabbitBroker(config.settings.rabbitmq_url, logger=logger)
app = FastStream(broker)

s3_client = S3Client(
    access_key=config.settings.s3_access_key,
    secret_key=config.settings.s3_secret_key,
    endpoint_url=config.settings.s3_endpoint_url,
    bucket_name=config.settings.s3_bucket_name,
    public_url=config.settings.s3_public_url,
)


@app.on_startup
async def start_worker() -> None:
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="parser-worker",
        environment=config.settings.environment,
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="parser-worker",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
    )
    start_worker_metrics_server(config.settings.worker_metrics_port)
    await s3_client.start()
    await rank_tasks.rank_client.start()
    logger.info("Parser worker started")


@app.on_shutdown
async def stop_worker() -> None:
    await s3_client.close()
    await rank_tasks.rank_client.close()
    await rank_tasks.close_redis()


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
            log.exception(
                f"Failed to process match log tournament_id={event.tournament_id} filename={event.filename}"
            )
            raise
        else:
            await publish_match_log_result(broker, event.tournament_id, event.filename, "done", logger=log)

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
