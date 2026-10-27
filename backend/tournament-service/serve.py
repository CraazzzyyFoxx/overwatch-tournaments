import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

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
    MATCH_INGESTED_TOURNAMENT_DLQ,
    TOURNAMENT_BRACKET_JOBS_DLQ,
    TOURNAMENT_BRACKET_JOBS_QUEUE,
    TOURNAMENT_CHALLONGE_PUSH_DLQ,
    TOURNAMENT_COMPUTE_EXCHANGE,
    TOURNAMENT_PICK_BAN_ROOM_OPEN_DLQ,
    TOURNAMENT_STANDINGS_INVALIDATED_DLQ,
    TOURNAMENT_STANDINGS_JOBS_DLQ,
    TOURNAMENT_STANDINGS_JOBS_QUEUE,
)
from shared.messaging.outbox import drain_outbox, purge_outbox
from shared.messaging.topology import declare_dead_letter_queue
from shared.observability import (
    Readiness,
    instrument_scheduler,
    make_rabbit_broker,
    observe_message_processing,
    observe_scheduled_job,
    register_db_pool_metrics,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_loop_lag_monitor,
    start_worker_metrics_server,
)
from shared.quota import close as close_quota
from shared.quota import configure as configure_quota
from shared.repository import ChatMessageRepository, ChatMuteRepository
from shared.schemas.events import TournamentComputationJobEvent
from shared.services.realtime import configure_realtime
from shared.services.realtime.consumer import register_invalidation_consumer
from src.core import config, db
from src.core.broker import set_worker_broker
from src.core.caching import configure_cache
from src.core.redis import close_realtime_redis
from src.rpc import (
    admin_misc,
    dashboard,
    ffa,
    integrations,
    match_import,
    pick_ban_admin,
    public_rpc,
    registration_admin,
    registration_team_binary,
    scrim,
    stage_admin,
    team_binary,
    team_format,
    tournament_binary,
)
from src.rpc import reads as rpc_reads
from src.services.admin import registry as admin_registry
from src.services.challonge import sync as challonge_sync
from src.services.computation.bracket_worker import process_bracket_job
from src.services.computation.jobs import purge_finished_jobs
from src.services.computation.standings_worker import process_standings_job
from src.services.division_grid.import_jobs import process_import_job, recover_stale_import_jobs
from src.services.encounter import challonge_push_events, log_evidence_events, room_open_events, room_reconcile
from src.services.registration import sheet_sync
from src.services.tournament import auto_transitions, recalculation_events

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
# ``GET /health`` on the metrics port: unready until the consumers run, again once shutdown begins.
readiness = Readiness(broker)

# Long-running compute jobs get their own AMQP channel so a burst of bracket /
# standings recomputes can't occupy the RPC channel. Its prefetch is per
# consumer (QoS is not process-wide), so the three compute queues can hold 12
# deliveries; ``_COMPUTE_SLOTS`` is what caps the process at 4 running jobs.
_JOBS_CHANNEL = Channel(prefetch_count=4)
_COMPUTE_SLOTS = asyncio.Semaphore(4)

# Expose the worker broker to event publishers that don't thread one through
# (e.g. standings-invalidation enqueues from the bracket/standings workers).
set_worker_broker(broker)

# The cashews cache is a process-global singleton; the worker must configure it
# before any cached read runs.
configure_cache()

# Same reason, same place: ``emit`` publishes through this Redis URL, and the
# cache generations every service's invalidations bump live there too.
configure_realtime(redis_url=str(config.settings.redis_url))

# Quota policy lives in the ``quota`` schema, consumption in Redis; the gate needs
# both before the first metered RPC. Its own client rather than
# ``core.redis.get_realtime_redis``: the realtime client decodes responses and is
# documented as realtime-only, and a limiter that must fail closed should not
# share a pool with a publisher that must fail open.
configure_quota(
    session_factory=db.async_session_maker,
    redis_url=str(config.settings.redis_url),
    enabled=config.settings.quota_enabled,
    edge_workspace_metering=config.settings.quota_edge_workspace_metering,
)

# Durable half of the cross-service invalidations: re-bumps a generation only
# when the writer's commit-time bump for that event was lost.
register_invalidation_consumer(
    broker,
    logger,
    queue=CACHE_INVALIDATION_TOURNAMENT_QUEUE,
    exchange=CACHE_INVALIDATION_EXCHANGE,
)

# Typed read RPC methods served by the gateway (rpc.tournament.*).
rpc_reads.register(broker, logger)
# Generic admin CRUD (rpc.tournament.admin.*) via the shared engine.
admin_registry.register(broker)
# Bespoke admin + integrations + division-grid typed RPC.
admin_misc.register(broker, logger)
# Organizer dashboard: readiness checklist, workspace dashboard and its trends.
dashboard.register(broker, logger)
registration_admin.register(broker, logger)
integrations.register(broker, logger)
stage_admin.register(broker, logger)
pick_ban_admin.register(broker, logger)
# FFA lobbies: the public table reads and the organizer's three result levers.
ffa.register(broker, logger)
public_rpc.register(broker, logger)
# A game's match imported by external id (captain or organizer), forwarded to the stats service.
match_import.register(broker, logger)
# Team logo upload/delete (binary body, base64 on the wire).
team_binary.register(broker, logger)
# Registered-team crest upload/delete — same wire format, captain-gated.
registration_team_binary.register(broker, logger)
# Tournament cover/logo upload/delete — same wire format, two slots.
tournament_binary.register(broker, logger)
team_format.register(broker, logger)
# Ad-hoc scrim rooms. Provisioning only — a room is then played through the
# pre-game subjects registered just above.
scrim.register(broker, logger)
# standings.invalidated: each event becomes a durable standings job, which the
# compute consumers at the bottom of this file run.
broker.include_router(recalculation_events.task_router)
# Ingest evidence (match.ingested): the match layer alone decides whether a log becomes official.
broker.include_router(log_evidence_events.task_router)
# Confirmed results of Challonge-linked encounters, staged by every confirm path, pushed here.
broker.include_router(challonge_push_events.task_router)
# A mix match started with hero bans: open its room.
broker.include_router(room_open_events.task_router)


async def settle_due_pick_ban_rooms() -> None:
    async with observe_scheduled_job("pick_ban_room_due"):
        await room_reconcile.reconcile_due_rooms()


async def sweep_stalled_pick_ban_rooms() -> None:
    async with observe_scheduled_job("pick_ban_room_sweep"):
        await room_reconcile.reconcile_stalled_rooms()


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
    """Drop realtime rows nobody can still replay: brackets, invalidations, chat.

    Three statements, one per topic family, each a single unbatched DELETE.
    Bracket and invalidation only, never pregame/draft: those sessions have no
    upper bound on duration, so a 7-day floor would cut a live one. ``%:chat``
    joins them because chat history lives in ``chat_message``; the rows here are
    a duplicate nothing reads.

    The patterns are BOUND, not inlined: a literal `:` inside ``text()`` is
    parsed as a bind-parameter marker (here `:bracket`), not a plain character,
    and raises ``InvalidRequestError`` at execute time with no value supplied.
    """
    async with observe_scheduled_job("realtime_workspace_event_purge"), session_factory() as session:
        for pattern in ("tournament:%:bracket", "%:invalidation", "%:chat"):
            await session.execute(
                text(
                    "DELETE FROM realtime.workspace_event "
                    "WHERE topic LIKE :topic_pattern AND occurred_at < now() - interval '7 days'"
                ),
                {"topic_pattern": pattern},
            )
        await session.commit()


async def purge_chat(
    session_factory: async_sessionmaker[AsyncSession] = db.async_session_maker,
) -> None:
    """Retention for the room chat: 90 days of messages, then gone.

    Room chatter has a short useful life; what was *decided* lives in
    ``encounter_result_audit`` / ``draft_audit_event``, not here. Expired mutes
    age out on the same clock -- an expired row is already inert, this just
    stops it accumulating. ``chat_room`` rows are tiny and left alone.
    """
    cutoff = datetime.now(UTC) - timedelta(days=90)
    async with observe_scheduled_job("chat_purge"), session_factory() as session:
        await ChatMessageRepository().purge_older_than(session, cutoff)
        await ChatMuteRepository().purge_expired_before(session, cutoff)
        await session.commit()


async def purge_retention(job: str, purge: Callable[[async_sessionmaker[AsyncSession]], Awaitable[int]]) -> None:
    """A retention purge (computation jobs, Challonge sync log) as one observed job; the purge logs its own count."""
    async with observe_scheduled_job(job):
        await purge(db.async_session_maker)


@app.on_startup
async def start_worker() -> None:
    await broker.connect()
    await declare_dead_letter_queue(broker, TOURNAMENT_BRACKET_JOBS_DLQ)
    await declare_dead_letter_queue(broker, TOURNAMENT_STANDINGS_JOBS_DLQ)
    await declare_dead_letter_queue(broker, DIVISION_GRID_IMPORT_JOBS_DLQ)
    await declare_dead_letter_queue(broker, CACHE_INVALIDATION_TOURNAMENT_DLQ)
    await declare_dead_letter_queue(broker, MATCH_INGESTED_TOURNAMENT_DLQ)
    await declare_dead_letter_queue(broker, TOURNAMENT_STANDINGS_INVALIDATED_DLQ)
    await declare_dead_letter_queue(broker, TOURNAMENT_CHALLONGE_PUSH_DLQ)
    await declare_dead_letter_queue(broker, TOURNAMENT_PICK_BAN_ROOM_OPEN_DLQ)
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
    readiness.bind()
    start_worker_metrics_server(config.settings.worker_metrics_port, ready=readiness)
    register_db_pool_metrics(db.async_engine, "tournament-svc")
    start_loop_lag_monitor("tournament-svc")
    await recover_stale_import_jobs()
    scheduler.add_job(
        recover_stale_import_jobs,
        "interval",
        minutes=5,
        id="division_grid_import_recovery",
    )
    scheduler.add_job(
        drain_outbox, "interval", seconds=1, id="event_outbox_drain", args=(db.async_session_maker, broker)
    )
    # A step's timer running out is the only thing that moves a room with nobody
    # writing anything, so it needs its own tick. The sweep is a backstop for a
    # room left owing a step anyway (a missed tick, a writer that died after its
    # commit). Both take the encounter lock with SKIP LOCKED, which is what makes
    # running them on every replica safe.
    scheduler.add_job(settle_due_pick_ban_rooms, "interval", seconds=1, id="pick_ban_room_due")
    scheduler.add_job(sweep_stalled_pick_ban_rooms, "interval", minutes=5, id="pick_ban_room_sweep")
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
    # Retention runs at a wall-clock hour, not every 24 h of uptime: a worker
    # redeployed more often than daily would never reach an interval job's first
    # run. The grace keeps a busy loop at 04:00 from skipping the day.
    daily = {"trigger": "cron", "hour": 4, "jitter": 600, "misfire_grace_time": 3600}
    scheduler.add_job(purge_stale_realtime_events, id="realtime_workspace_event_purge", **daily)
    scheduler.add_job(purge_chat, id="chat_purge", **daily)
    # purge_outbox observes itself as "event_outbox_purge".
    scheduler.add_job(purge_outbox, id="event_outbox_purge", args=(db.async_session_maker,), **daily)
    for job, purge in (
        ("computation_job_purge", purge_finished_jobs),
        ("challonge_sync_log_purge", challonge_sync.purge_sync_log),
    ):
        scheduler.add_job(purge_retention, id=job, args=(job, purge), **daily)
    instrument_scheduler(scheduler, "tournament-svc")
    scheduler.start()
    logger.info("Tournament worker scheduler started")


@app.after_startup
async def serve_worker() -> None:
    readiness.serving(True)


@app.on_shutdown
async def stop_scheduler() -> None:
    readiness.serving(False)
    # The asyncio executor cancels in-flight scheduled jobs (outbox drain,
    # sheet/Challonge sync); it cannot wait for them. This is safe: a cancelled
    # outbox batch rolls back and is republished on the next tick (at-least-once),
    # and each sheet feed / each Challonge tournament commits once, at its end (a
    # Challonge import's per-match savepoints only isolate a failing match), so an
    # interrupted one rolls back whole and the next tick re-runs it idempotently.
    scheduler.shutdown(wait=False)


@app.after_shutdown
async def close_clients() -> None:
    # Only once broker.stop() has let the in-flight handlers finish: they publish
    # through these. Unclosed, each pooled client (realtime publisher,
    # challonge.sync's lock, the quota gate's own) leaks a connection per restart.
    await close_realtime_redis()
    await challonge_sync.close_redis()
    await close_quota()


@broker.subscriber(TOURNAMENT_BRACKET_JOBS_QUEUE, exchange=TOURNAMENT_COMPUTE_EXCHANGE, channel=_JOBS_CHANNEL)
async def consume_bracket_job(data: dict, msg: RabbitMessage) -> None:
    async with (
        _COMPUTE_SLOTS,
        observe_message_processing(
            queue=TOURNAMENT_BRACKET_JOBS_QUEUE,
            handler="consume_bracket_job",
            message=msg,
            logger=logger,
        ),
    ):
        event = TournamentComputationJobEvent.model_validate(data)
        await process_bracket_job(event.job_id)


@broker.subscriber(TOURNAMENT_STANDINGS_JOBS_QUEUE, exchange=TOURNAMENT_COMPUTE_EXCHANGE, channel=_JOBS_CHANNEL)
async def consume_standings_job(data: dict, msg: RabbitMessage) -> None:
    async with (
        _COMPUTE_SLOTS,
        observe_message_processing(
            queue=TOURNAMENT_STANDINGS_JOBS_QUEUE,
            handler="consume_standings_job",
            message=msg,
            logger=logger,
        ),
    ):
        event = TournamentComputationJobEvent.model_validate(data)
        await process_standings_job(event.job_id)


@broker.subscriber(
    DIVISION_GRID_IMPORT_JOBS_QUEUE,
    exchange=TOURNAMENT_COMPUTE_EXCHANGE,
    channel=_JOBS_CHANNEL,
)
async def consume_division_grid_import_job(data: dict, msg: RabbitMessage) -> None:
    async with (
        _COMPUTE_SLOTS,
        observe_message_processing(
            queue=DIVISION_GRID_IMPORT_JOBS_QUEUE,
            handler="consume_division_grid_import_job",
            message=msg,
            logger=logger,
        ),
    ):
        await process_import_job(int(data["job_id"]))
