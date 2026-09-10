from apscheduler.schedulers.asyncio import AsyncIOScheduler
from faststream import FastStream
from faststream.rabbit import Channel
from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.messaging.config import (
    CACHE_INVALIDATION_EXCHANGE,
    CACHE_INVALIDATION_TOURNAMENT_DLQ,
    CACHE_INVALIDATION_TOURNAMENT_QUEUE,
    DIVISION_GRID_IMPORT_JOBS_DLQ,
    DIVISION_GRID_IMPORT_JOBS_QUEUE,
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
    observe_scheduled_job,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.schemas.events import TournamentComputationJobEvent
from shared.services.realtime import configure_realtime
from shared.services.realtime.consumer import register_invalidation_consumer
from src.core import config, db
from src.core.broker import set_worker_broker
from src.core.caching import configure_cache
from src.core.redis import close_realtime_redis
from src.rpc import (
    admin_misc,
    integrations,
    pick_ban_admin,
    public_rpc,
    registration_admin,
    registration_team_binary,
    scrim,
    stage_admin,
    team_binary,
    tournament_binary,
)
from src.rpc import reads as rpc_reads
from src.services.admin import registry as admin_registry
from src.services.challonge import sync as challonge_sync
from src.services.computation.bracket_worker import process_bracket_job
from src.services.computation.standings_worker import process_standings_job
from src.services.division_grid.import_jobs import process_import_job, recover_stale_import_jobs
from src.services.registration import sheet_sync
from src.services.tournament import auto_transitions, recalculation_events
from src.services.tournament.cache_invalidation import invalidate_tournament_resources
from src.services.tournament.cache_resources import RESOURCE_CACHE_PATTERNS

logger = setup_logging(
    service_name="tournament-svc",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

broker = make_rabbit_broker(
    config.settings.rabbitmq_url, logger=logger, prefetch_count=config.settings.rpc_prefetch_count
)
app = FastStream(broker)
scheduler = AsyncIOScheduler()

# Long-running compute jobs get their own AMQP channel so a burst of bracket /
# standings recomputes can't occupy the RPC default-channel QoS slots.
_JOBS_CHANNEL = Channel(prefetch_count=4)

# Expose the worker broker to event publishers that don't thread one through
# (e.g. standings-invalidation enqueues from the bracket/standings workers).
set_worker_broker(broker)

# The cashews cache is a process-global singleton; the worker must configure it
# (like the API does) or after-commit cache invalidation raises NotConfiguredError.
configure_cache()

# Same reason, same place: ``emit`` publishes through this Redis URL and drops
# this service's own cashews keys through the invalidator before doing so.
configure_realtime(
    redis_url=str(config.settings.redis_url),
    cache_invalidator=invalidate_tournament_resources,
)

# Cross-service half: resources another service stales that this one caches.
register_invalidation_consumer(
    broker,
    logger,
    queue=CACHE_INVALIDATION_TOURNAMENT_QUEUE,
    exchange=CACHE_INVALIDATION_EXCHANGE,
    patterns=RESOURCE_CACHE_PATTERNS,
)

# Typed read RPC methods served by the gateway (rpc.tournament.*).
rpc_reads.register(broker, logger)
# Generic admin CRUD (rpc.tournament.admin.*) via the shared engine.
admin_registry.register(broker)
# Bespoke admin + integrations + division-grid typed RPC.
admin_misc.register(broker, logger)
registration_admin.register(broker, logger)
integrations.register(broker, logger)
stage_admin.register(broker, logger)
pick_ban_admin.register(broker, logger)
public_rpc.register(broker, logger)
# Team logo upload/delete (binary body, base64 on the wire).
team_binary.register(broker, logger)
# Registered-team crest upload/delete — same wire format, captain-gated.
registration_team_binary.register(broker, logger)
# Tournament cover/logo upload/delete — same wire format, two slots.
tournament_binary.register(broker, logger)
# Ad-hoc scrim rooms (docs/plans/2026-08-12-scrim-rooms.md). Provisioning only —
# a room is then played through the pre-game subjects registered just above.
scrim.register(broker, logger)
# Recalculation-event consumers (tournament.changed / standings.invalidated).
# Previously mounted by the deleted HTTP main.py; the worker now hosts them so
# cache invalidation + standings recalculation run on those domain events.
broker.include_router(recalculation_events.task_router)


async def drain_outbox() -> None:
    async with observe_scheduled_job("event_outbox_drain"), db.async_session_maker() as session:
        published = await publish_pending_outbox_events(session, broker, limit=100, commit=True)
        if published:
            logger.info("Published %d outbox events", published)


async def sync_registration_google_sheet_feeds() -> None:
    async with observe_scheduled_job("registration_google_sheet_sync"):
        results = await sheet_sync.sync_due_google_sheet_feeds(db.async_session_maker)
        if results:
            logger.info("Registration Google Sheets sync completed", results=results)


async def sync_challonge_active_tournaments() -> None:
    async with observe_scheduled_job("challonge_active_sync"):
        results = await challonge_sync.sync_service.sync_active_challonge_tournaments(db.async_session_maker)
        if results:
            logger.info("Challonge auto-sync completed", results=results)


async def auto_transition_tournaments() -> None:
    async with observe_scheduled_job("auto_transition_tournaments"):
        results = await auto_transitions.run_due_transitions(db.async_session_maker)
        if results:
            logger.info("Tournament auto-transitions applied", results=results)


async def purge_stale_realtime_events(
    session_factory: async_sessionmaker[AsyncSession] = db.async_session_maker,
) -> None:
    """Drop realtime rows nobody can still replay: brackets and invalidations.

    Two statements, one per topic family, each a single unbatched DELETE (design
    decision D2 of docs/plans/2026-08-24-realtime-shared-library.md). Bracket and
    invalidation only, never pregame/draft: those sessions have no upper bound on
    duration, so a 7-day floor would cut a live one.

    The patterns are BOUND, not inlined: a literal `:` inside ``text()`` is
    parsed as a bind-parameter marker (here `:bracket`), not a plain character,
    and raises ``InvalidRequestError`` at execute time with no value supplied.
    """
    async with observe_scheduled_job("realtime_workspace_event_purge"), session_factory() as session:
        for pattern in ("tournament:%:bracket", "%:invalidation"):
            await session.execute(
                text(
                    "DELETE FROM realtime.workspace_event "
                    "WHERE topic LIKE :topic_pattern AND occurred_at < now() - interval '7 days'"
                ),
                {"topic_pattern": pattern},
            )
        await session.commit()


@app.on_startup
async def start_worker() -> None:
    await broker.connect()
    await declare_dead_letter_queue(broker, TOURNAMENT_BRACKET_JOBS_DLQ)
    await declare_dead_letter_queue(broker, TOURNAMENT_STANDINGS_JOBS_DLQ)
    await declare_dead_letter_queue(broker, DIVISION_GRID_IMPORT_JOBS_DLQ)
    await declare_dead_letter_queue(broker, CACHE_INVALIDATION_TOURNAMENT_DLQ)
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="tournament-svc",
        enable_logs=config.settings.sentry_enable_logs,
        logs_level=config.settings.sentry_logs_level,
        enable_metrics=config.settings.sentry_enable_metrics,
        environment=config.settings.environment,
        release=config.settings.sentry_release,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="tournament-svc",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
        environment=config.settings.environment,
        release=config.settings.sentry_release,
        engine=db.async_engine,
    )
    start_worker_metrics_server(config.settings.worker_metrics_port)
    await recover_stale_import_jobs()
    scheduler.add_job(
        recover_stale_import_jobs,
        "interval",
        minutes=5,
        id="division_grid_import_recovery",
    )
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
    scheduler.add_job(
        auto_transition_tournaments,
        "interval",
        seconds=30,
        id="auto_transition_tournaments",
    )
    scheduler.add_job(
        purge_stale_realtime_events,
        "interval",
        days=1,
        id="realtime_workspace_event_purge",
    )
    scheduler.start()
    logger.info("Tournament worker scheduler started")


@app.on_shutdown
async def stop_scheduler() -> None:
    # wait=False intentionally abandons in-flight scheduled jobs (outbox drain,
    # sheet/Challonge sync) instead of blocking shutdown for up to minutes.
    # This is safe: the outbox drain is transactional per-row, and the sync
    # flows commit incrementally (per encounter / per batch) and are idempotent
    # on re-run, so an interrupted job resumes cleanly on the next tick.
    scheduler.shutdown(wait=False)
    # The realtime publisher's pooled client: unclosed, it leaks a connection per
    # worker restart (the same leak challonge.sync's own client was fixed for
    # — that fix was never applied to challonge.sync itself; it is now).
    await close_realtime_redis()
    await challonge_sync.close_redis()


@broker.subscriber(TOURNAMENT_BRACKET_JOBS_QUEUE, exchange=TOURNAMENT_COMPUTE_EXCHANGE, channel=_JOBS_CHANNEL)
async def consume_bracket_job(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_BRACKET_JOBS_QUEUE,
        handler="consume_bracket_job",
        message=msg,
        logger=logger,
    ):
        event = TournamentComputationJobEvent.model_validate(data)
        await process_bracket_job(event.job_id)


@broker.subscriber(TOURNAMENT_STANDINGS_JOBS_QUEUE, exchange=TOURNAMENT_COMPUTE_EXCHANGE, channel=_JOBS_CHANNEL)
async def consume_standings_job(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=TOURNAMENT_STANDINGS_JOBS_QUEUE,
        handler="consume_standings_job",
        message=msg,
        logger=logger,
    ):
        event = TournamentComputationJobEvent.model_validate(data)
        await process_standings_job(event.job_id)


@broker.subscriber(
    DIVISION_GRID_IMPORT_JOBS_QUEUE,
    exchange=TOURNAMENT_COMPUTE_EXCHANGE,
    channel=_JOBS_CHANNEL,
)
async def consume_division_grid_import_job(data: dict, msg: RabbitMessage) -> None:
    async with observe_message_processing(
        queue=DIVISION_GRID_IMPORT_JOBS_QUEUE,
        handler="consume_division_grid_import_job",
        message=msg,
        logger=logger,
    ):
        await process_import_job(int(data["job_id"]))
