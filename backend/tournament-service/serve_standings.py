from faststream import FastStream
from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from shared.messaging.config import (
    TOURNAMENT_COMPUTE_EXCHANGE,
    TOURNAMENT_STANDINGS_JOBS_DLQ,
    TOURNAMENT_STANDINGS_JOBS_QUEUE,
)
from shared.messaging.topology import declare_dead_letter_queue
from shared.observability import observe_message_processing, setup_logging, setup_tracing, start_worker_metrics_server
from shared.schemas.events import TournamentComputationJobEvent

from src.core import config
from src.services.computation.standings_worker import process_standings_job

logger = setup_logging(
    service_name="tournament-standings-worker",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)
broker = RabbitBroker(config.settings.rabbitmq_url, logger=logger)
app = FastStream(broker)


@app.on_startup
async def start_worker() -> None:
    await broker.connect()
    await declare_dead_letter_queue(broker, TOURNAMENT_STANDINGS_JOBS_DLQ)
    setup_tracing(
        service_name="tournament-standings-worker",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
    )
    start_worker_metrics_server(config.settings.worker_metrics_port)
    logger.info("Tournament standings worker started")


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
