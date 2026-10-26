"""The stats worker process: every consumer and schedule, and no RPC handler.

Consumes ``stats.ingest.<discipline>`` for the disciplines ``STATS_DISCIPLINES`` selects (every installed one when
unset), the upload/tournament fanout, achievement evaluation, ``tournament.encounter.completed``, Discord member changes,
``cache.invalidated`` (the public read caches and the hero-stats materialized view) and each selected discipline
module's own jobs (the OverFast rank collector), and runs the reaper, failed-log retention, match-fetch (import by
external id), subscription and outbox-drain schedules. Run: ``faststream run serve_worker:app``.
"""

from collections.abc import Awaitable

from faststream.rabbit import Channel
from faststream.rabbit.annotations import RabbitMessage

from shared.disciplines import jobs as discipline_jobs
from shared.messaging.config import (
    ACHIEVEMENT_EVALUATE_DEFERRED_DLQ,
    ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE,
    ACHIEVEMENT_EVALUATE_DLQ,
    ACHIEVEMENT_EVALUATE_QUEUE,
    CACHE_INVALIDATION_EXCHANGE,
    CACHE_INVALIDATION_STATS_DLQ,
    CACHE_INVALIDATION_STATS_QUEUE,
    DISCORD_MEMBER_CHANGED_DLQ,
    PROCESS_TOURNAMENT_LOGS_DLQ,
    TOURNAMENT_ENCOUNTER_COMPLETED_DLQ,
    UPLOAD_MATCH_LOG_DLQ,
    ingest_dlq,
    ingest_replay_dlq,
)
from shared.messaging.outbox import drain_outbox
from shared.messaging.topology import declare_dead_letter_queue
from shared.observability import Readiness, observe_message_processing
from shared.schemas.events import CacheInvalidatedEvent
from shared.services.realtime import Resource
from shared.services.realtime.consumer import register_invalidation_consumer
from shared.services.scheduler import IntervalScheduler
from src.core import config, db
from src.core.clients import realtime_redis, s3_client
from src.core.lifecycle import close_clients, create_process, start_clients, start_observability
from src.services import hero_stats_refresh
from src.services.achievement.engine.consumer import (
    handle_achievement_evaluate,
    handle_achievement_evaluate_deferred,
)
from src.services.ingest import consumers as ingest_consumers
from src.services.ingest import fetch as match_fetch
from src.services.match_logs import consumers as match_log_consumers
from src.services.match_logs import reaper as logs_reaper
from src.services.match_logs import retention as logs_retention
from src.services.subscription_collection import member_events
from src.services.subscription_collection import scheduler as subscription_scheduler

SERVICE_NAME = "stats-worker"

logger, broker, app = create_process(SERVICE_NAME, prefetch_count=config.settings.rpc_prefetch_count)
readiness = Readiness(broker)

# Fails the import, hence the start, on an invalid STATS_DISCIPLINES (see config.select_disciplines).
SELECTED = config.settings.selected_disciplines

# The short handlers (upload, tournament fan-out, achievement evaluation) share one channel, off the RPC channel QoS;
# each discipline's ingest and replay queue has a channel of its own (``ingest_consumers.register``).
_JOBS_CHANNEL = Channel(prefetch_count=2)
# Deferred achievement recompute for unverified workspaces: a full-history run an operator asked for, on a workspace
# nobody has vouched for. One at a time, so it can never crowd out the parse-driven evaluations on _JOBS_CHANNEL.
_ACHIEVEMENT_DEFERRED_CHANNEL = Channel(prefetch_count=1)
# Cache-invalidation bursts must not compete with the jobs channels.
_INVALIDATION_CHANNEL = Channel(prefetch_count=4)

# Dead-letter queues this worker owns. Every queue it consumes carries x-dead-letter-exchange=dlx plus an x-message-ttl,
# but RabbitMQ creates nothing for the dead-letter routing key: without a declared, bound DLQ an expired job (a log the
# worker could not chew inside the 5-minute ingest TTL) is dropped without a trace while its row says "Queued". The rank
# and registration-check queues are consumed by the OverFast module, which declares their DLQs itself.
_OWNED_DLQS = (
    UPLOAD_MATCH_LOG_DLQ,
    *(ingest_dlq(spec.code) for spec in SELECTED),
    *(ingest_replay_dlq(spec.code) for spec in SELECTED),
    PROCESS_TOURNAMENT_LOGS_DLQ,
    ACHIEVEMENT_EVALUATE_DLQ,
    ACHIEVEMENT_EVALUATE_DEFERRED_DLQ,
    TOURNAMENT_ENCOUNTER_COMPLETED_DLQ,
    DISCORD_MEMBER_CHANGED_DLQ,
    CACHE_INVALIDATION_STATS_DLQ,
)

# stop_jobs() awaitables handed back at shutdown start, awaited once the consumers have drained.
_pending_closes: list[Awaitable[None]] = []
discipline_jobs.register_jobs(
    SELECTED, broker, session_factory=db.async_session_maker, redis=realtime_redis, logger=logger
)
member_events.register(broker, logger)
ingest_consumers.register(broker, logger, disciplines=SELECTED)
match_log_consumers.register(broker, logger, channel=_JOBS_CHANNEL)


async def _refresh_hero_stats(event: CacheInvalidatedEvent) -> None:
    """Debounced refresh of the global hero-stats materialized view.

    Gated on ``tournament.standings`` — the resource that carries "match data
    moved".
    """
    if Resource.TOURNAMENT_STANDINGS in event.resources:
        hero_stats_refresh.hero_stats_refresh_service.request_refresh(db.async_session_maker, logger)


# Worker replicas share CACHE_INVALIDATION_STATS_QUEUE: each message re-bumps the shared generations once, wherever it
# lands. No other service may consume it.
register_invalidation_consumer(
    broker,
    logger,
    queue=CACHE_INVALIDATION_STATS_QUEUE,
    exchange=CACHE_INVALIDATION_EXCHANGE,
    channel=_INVALIDATION_CHANNEL,
    on_event=_refresh_hero_stats,
)
# Publishes every committed event_outbox row (this worker's ingest requests, achievement runs, ...) once a second.
_outbox_scheduler = IntervalScheduler(job_id="event_outbox_drain", label="Outbox drain", logger=logger)


@app.on_startup
async def start_worker() -> None:
    await broker.connect()
    for dlq in _OWNED_DLQS:
        await declare_dead_letter_queue(broker, dlq)
    start_observability(SERVICE_NAME, readiness)
    await start_clients()
    # The selected disciplines' jobs: each selected game's collector (its dead-letter queues, upstream client and rank
    # schedule).
    await discipline_jobs.start_jobs(
        SELECTED, session_factory=db.async_session_maker, redis=realtime_redis, logger=logger
    )
    # Requeue ingest jobs the queue dropped (expired ProcessIngestJobEvent, worker killed mid-parse) through the outbox,
    # for the selected disciplines only. Redis leader-locked across worker replicas.
    logs_reaper.start_scheduler(redis=realtime_redis, disciplines=[spec.code for spec in SELECTED])
    # Drop failed match logs (S3 object + record) past their retention window.
    logs_retention.start_scheduler(redis=realtime_redis, s3=s3_client)
    # Pull the selected disciplines' matches requested by external id (a no-op without a module fetcher).
    match_fetch.start_scheduler(redis=realtime_redis, s3=s3_client, disciplines=[spec.code for spec in SELECTED])
    subscription_scheduler.start_scheduler()
    # Initial build of the hero global-stats materialized view: a debounced background task that never blocks startup.
    hero_stats_refresh.hero_stats_refresh_service.request_refresh(db.async_session_maker, logger)
    _outbox_scheduler.start(drain_outbox, seconds=1, args=(db.async_session_maker, broker))
    readiness.bind()


@app.after_startup
async def serve_worker() -> None:
    readiness.serving(True)
    logger.info("Stats worker started: ingest for {}", ", ".join(spec.code for spec in SELECTED))


@app.on_shutdown
async def stop_worker() -> None:
    readiness.serving(False)
    _pending_closes.extend(discipline_jobs.stop_jobs(SELECTED))
    logs_reaper.shutdown_scheduler()
    logs_retention.shutdown_scheduler()
    match_fetch.shutdown_scheduler()
    subscription_scheduler.shutdown_scheduler()
    _outbox_scheduler.shutdown()


@app.after_shutdown
async def close_worker_resources() -> None:
    # Consumers must finish before their HTTP, S3 and Redis clients are closed.
    await close_clients(_pending_closes)


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
