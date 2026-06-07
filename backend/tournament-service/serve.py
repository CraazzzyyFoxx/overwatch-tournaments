from apscheduler.schedulers.asyncio import AsyncIOScheduler
from faststream import FastStream
from faststream.rabbit import RabbitBroker
from shared.messaging.outbox import publish_pending_outbox_events
from shared.observability import (
    setup_logging,
    setup_tracing,
    start_worker_metrics_server,
)

from src.core import config, db
from src.services.registration import admin as registration_service

logger = setup_logging(
    service_name="tournament-worker",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

broker = RabbitBroker(config.settings.rabbitmq_url, logger=logger)
app = FastStream(broker)
scheduler = AsyncIOScheduler()


async def drain_outbox() -> None:
    async with db.async_session_maker() as session:
        published = await publish_pending_outbox_events(session, broker, limit=100, commit=True)
        if published:
            logger.info("Published %d outbox events", published)


async def sync_registration_google_sheet_feeds() -> None:
    results = await registration_service.sync_due_google_sheet_feeds(db.async_session_maker)
    if results:
        logger.info("Registration Google Sheets sync completed", results=results)


@app.on_startup
async def start_scheduler() -> None:
    setup_tracing(
        service_name="tournament-worker",
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
    scheduler.start()
    logger.info("Tournament worker scheduler started")


@app.on_shutdown
async def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
