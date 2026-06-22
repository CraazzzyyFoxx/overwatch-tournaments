from apscheduler.schedulers.asyncio import AsyncIOScheduler
from faststream import FastStream
from faststream.rabbit.annotations import RabbitMessage
from shared.messaging.config import (
    TOURNAMENT_BRACKET_JOBS_DLQ,
    TOURNAMENT_BRACKET_JOBS_QUEUE,
    TOURNAMENT_COMPUTE_EXCHANGE,
    TOURNAMENT_STANDINGS_JOBS_DLQ,
    TOURNAMENT_STANDINGS_JOBS_QUEUE,
)
from shared.messaging.outbox import publish_pending_outbox_events
from shared.messaging.topology import declare_dead_letter_queue
from shared.observability import (
    make_rabbit_broker,
    observe_message_processing,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.schemas.events import TournamentComputationJobEvent

from src.core import config, db
from src.core.broker import set_worker_broker
from src.core.caching import configure_cache
from src.rpc import admin_misc, integrations, public_rpc, reads as rpc_reads, registration_admin, stage_admin
from src.services.admin import registry as admin_registry
from src.services.challonge import sync as challonge_sync
from src.services.computation.bracket_worker import process_bracket_job
from src.services.computation.standings_worker import process_standings_job

# Import for side effects: registers the SQLAlchemy after-commit listeners that
# publish encounter map-veto realtime signals (encounter:{id}:map-veto).
from src.services.encounter import realtime_commit as _encounter_realtime_commit  # noqa: F401
from src.services.registration import admin as registration_service
from src.services.tournament import recalculation_events

logger = setup_logging(
    service_name="tournament-svc",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

broker = make_rabbit_broker(config.settings.rabbitmq_url, logger=logger)
app = FastStream(broker)
scheduler = AsyncIOScheduler()

# Expose the worker broker to event publishers that don't thread one through
# (e.g. standings-invalidation enqueues from the bracket/standings workers).
set_worker_broker(broker)

# The cashews cache is a process-global singleton; the worker must configure it
# (like the API does) or after-commit cache invalidation raises NotConfiguredError.
configure_cache()

# Typed read RPC methods served by the gateway (rpc.tournament.*).
rpc_reads.register(broker, logger)
# Generic admin CRUD (rpc.tournament.admin.*) via the shared engine.
admin_registry.register(broker)
# Bespoke admin + integrations + division-grid typed RPC.
admin_misc.register(broker, logger)
registration_admin.register(broker, logger)
integrations.register(broker, logger)
stage_admin.register(broker, logger)
public_rpc.register(broker, logger)
# Recalculation-event consumers (tournament.changed / standings.invalidated).
# Previously mounted by the deleted HTTP main.py; the worker now hosts them so
# cache invalidation + standings recalculation run on those domain events.
broker.include_router(recalculation_events.task_router)


async def drain_outbox() -> None:
    async with db.async_session_maker() as session:
        published = await publish_pending_outbox_events(session, broker, limit=100, commit=True)
        if published:
            logger.info("Published %d outbox events", published)


async def sync_registration_google_sheet_feeds() -> None:
    results = await registration_service.sync_due_google_sheet_feeds(db.async_session_maker)
    if results:
        logger.info("Registration Google Sheets sync completed", results=results)


async def sync_challonge_active_tournaments() -> None:
    results = await challonge_sync.sync_active_challonge_tournaments(db.async_session_maker)
    if results:
        logger.info("Challonge auto-sync completed", results=results)


@app.on_startup
async def start_worker() -> None:
    await broker.connect()
    await declare_dead_letter_queue(broker, TOURNAMENT_BRACKET_JOBS_DLQ)
    await declare_dead_letter_queue(broker, TOURNAMENT_STANDINGS_JOBS_DLQ)
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="tournament-svc",
        enable_logs=config.settings.sentry_enable_logs,
        logs_level=config.settings.sentry_logs_level,
        enable_metrics=config.settings.sentry_enable_metrics,
        environment=config.settings.environment,
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="tournament-svc",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
    )
    start_worker_metrics_server(config.settings.worker_metrics_port)
    scheduler.add_job(drain_outbox, "interval", seconds=1, id="event_outbox_drain")
    scheduler.add_job(
        sync_registration_google_sheet_feeds,
        "interval",
        minutes=5,
        id="registration_google_sheet_sync",
    )
    scheduler.add_job(
        sync_challonge_active_tournaments,
        "interval",
        minutes=config.settings.challonge_auto_sync_interval_minutes,
        id="challonge_active_sync",
    )
    scheduler.start()
    logger.info("Tournament worker scheduler started")


@app.on_shutdown
async def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)


@broker.subscriber(TOURNAMENT_BRACKET_JOBS_QUEUE, exchange=TOURNAMENT_COMPUTE_EXCHANGE)
async def consume_bracket_job(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_BRACKET_JOBS_QUEUE,
        handler="consume_bracket_job",
        message=msg,
        logger=logger,
    ):
        event = TournamentComputationJobEvent.model_validate(data)
        await process_bracket_job(event.job_id)


@broker.subscriber(TOURNAMENT_STANDINGS_JOBS_QUEUE, exchange=TOURNAMENT_COMPUTE_EXCHANGE)
async def consume_standings_job(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_STANDINGS_JOBS_QUEUE,
        handler="consume_standings_job",
        message=msg,
        logger=logger,
    ):
        event = TournamentComputationJobEvent.model_validate(data)
        await process_standings_job(event.job_id)
