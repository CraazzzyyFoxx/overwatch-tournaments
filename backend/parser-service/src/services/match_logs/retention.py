"""Retention for match logs the parser rejected.

A failed log stays in S3 (and in the admin console) for
``failed_log_retention_days`` so an operator can inspect or retry it; after that
the object and its ``failed`` record are dropped. Unfinished logs (no MatchEnd)
never reach this: ``MatchLogProcessor.validate`` deletes them on the spot.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from shared.observability import observe_scheduled_job
from shared.repository.support import LogProcessingRepository
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
)
from shared.services.scheduler import IntervalScheduler
from src.core import db
from src.core.config import settings
from src.services.match_logs.binary import binary_match_logs

__all__ = ("purge_expired_failed_logs", "shutdown_scheduler", "start_scheduler")

LEADER_LOCK_KEY = "log_processing:retention:leader"
TICK_SECONDS = 3600
BATCH_SIZE = 100

_scheduler = IntervalScheduler(job_id="failed_match_log_retention", label="Failed match-log retention")
_repo = LogProcessingRepository()


async def purge_expired_failed_logs(
    *,
    redis: Any,
    s3: Any,
    session_factory: Any = db.async_session_maker,
    now: datetime | None = None,
) -> int:
    """Drop one batch of expired failed logs; return how many records went.

    Never raises — a failed tick is logged and the next one picks the rest up.
    """
    try:
        token = await acquire_distributed_lock(
            redis, LEADER_LOCK_KEY, ttl_seconds=TICK_SECONDS, acquire_timeout_seconds=0.5
        )
    except DistributedLockUnavailable:
        return 0

    cutoff = (now or datetime.now(UTC)) - timedelta(days=settings.failed_log_retention_days)
    async with observe_scheduled_job("failed_match_log_retention"):
        try:
            async with session_factory() as session:
                rows = await _repo.claim_expired_failed(session, cutoff=cutoff, limit=BATCH_SIZE)
                purged: list[int] = []
                for record_id, tournament_id, filename in rows:
                    in_use = await _repo.log_file_in_use(
                        session, record_id=record_id, tournament_id=tournament_id, filename=filename, cutoff=cutoff
                    )
                    # Keep the row when S3 refused the delete, so the next tick retries it.
                    if in_use or await binary_match_logs.delete_log(s3, tournament_id, filename):
                        purged.append(record_id)
                await _repo.delete_by_ids(session, purged)
                await session.commit()
            if purged:
                logger.info("Failed match-log retention: purged={}", len(purged))
            return len(purged)
        except Exception:
            logger.exception("Failed match-log retention tick failed")
            return 0
        finally:
            await release_distributed_lock(redis, token)


def start_scheduler(*, redis: Any, s3: Any) -> None:
    _scheduler.start(purge_expired_failed_logs, seconds=TICK_SECONDS, kwargs={"redis": redis, "s3": s3})


def shutdown_scheduler() -> None:
    _scheduler.shutdown()
