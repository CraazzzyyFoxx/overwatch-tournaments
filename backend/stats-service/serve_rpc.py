"""The stats RPC process: typed ``rpc.stats.*`` handlers behind the gateway, and nothing that runs in the background.

It registers no ingest, rank, achievement or tournament-event consumer and starts no schedule but the outbox drain (its
handlers commit outbox rows, which must go out even while no worker runs); the rest belongs to ``serve_worker.py``.
The public reads (``rpc.stats.{statistics,users,achievements}.*``) are the hottest anonymous traffic in the system and
run on their own channel. QoS is per consumer (FastStream ``global_qos=False``), not per channel, so they and the
admin/ingest handlers draw on the same process-wide ``RPC_PREFETCH_COUNT`` handler permits (``shared.rpc.deadline``).
Run: ``faststream run serve_rpc:app``.
"""

from faststream.rabbit import Channel
from redis.asyncio import Redis

from shared.disciplines import DISCIPLINES
from shared.disciplines import jobs as discipline_jobs
from shared.messaging.outbox import drain_outbox
from shared.observability import Readiness
from shared.services.scheduler import IntervalScheduler
from src.core import config, db
from src.core.caching import backend_cache_url
from src.core.clients import realtime_redis
from src.core.lifecycle import close_clients, create_process, start_clients, start_observability
from src.rpc import (
    achievement_reads as rpc_achievement_reads,
)
from src.rpc import (
    achievements as rpc_achievements,
)
from src.rpc import (
    impact as rpc_impact,
)
from src.rpc import (
    ingest as rpc_ingest,
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
    statistics as rpc_statistics,
)
from src.rpc import (
    subscription as rpc_subscription,
)
from src.rpc import (
    users as rpc_users,
)

SERVICE_NAME = "stats-svc"

logger, broker, app = create_process(SERVICE_NAME, prefetch_count=config.settings.rpc_prefetch_count)
readiness = Readiness(broker)
_outbox_scheduler = IntervalScheduler(job_id="event_outbox_drain", label="Outbox drain", logger=logger)

rpc_logs.register(broker, logger)
rpc_rank.register(broker, logger)
rpc_achievements.register(broker, logger)
rpc_misc.register(broker, logger)
rpc_impact.register(broker, logger)
rpc_ingest.register(broker, logger)
rpc_subscription.register(broker, logger)

_PUBLIC_READS_CHANNEL = Channel(prefetch_count=config.settings.rpc_prefetch_count)
rpc_statistics.register(broker, logger, channel=_PUBLIC_READS_CHANNEL)
rpc_users.register(broker, logger, channel=_PUBLIC_READS_CHANNEL)
rpc_achievement_reads.register(broker, logger, channel=_PUBLIC_READS_CHANNEL)

# The collection handlers (``rank.collect``, ...) run here but their consumers and schedules run in the worker: wire only
# the module runtime they read. Every installed discipline, not the worker's selection: the RPC surface is not partial.
discipline_jobs.configure_runtime(
    DISCIPLINES.values(), broker, session_factory=db.async_session_maker, redis=realtime_redis
)


@app.on_startup
async def start_rpc() -> None:
    await broker.connect()
    start_observability(SERVICE_NAME, readiness)
    await start_clients()
    await _flush_read_caches()
    readiness.bind()
    _outbox_scheduler.start(drain_outbox, seconds=1, args=(db.async_session_maker, broker))


async def _flush_read_caches() -> None:
    """Drop stale read caches on (re)deploy: one FLUSHDB of the cache database, which holds nothing but cache — never a
    keyspace SCAN, which times out under load and loses the drop."""
    client = Redis.from_url(backend_cache_url())
    try:
        await client.flushdb(asynchronous=True)
    finally:
        await client.aclose()


@app.after_startup
async def serve_rpc() -> None:
    readiness.serving(True)
    logger.info("Stats RPC process started")


@app.on_shutdown
async def stop_rpc() -> None:
    readiness.serving(False)
    _outbox_scheduler.shutdown()


@app.after_shutdown
async def close_rpc_resources() -> None:
    await close_clients()
