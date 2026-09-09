"""Stall recovery for match-log processing.

``process_match_log`` carries ``x-message-ttl=300000``, so a ``ProcessMatchLogEvent``
that isn't consumed within five minutes is dead-lettered — and nothing looks at
the ``LogProcessingRecord`` again. A batch upload larger than the worker chews in
five minutes, a worker restart, or a publish that failed after the row committed
all leave records sitting on ``pending`` forever; that is the admin monitor
showing files stuck on "Queued" weeks after upload. A worker killed mid-parse
leaves the twin defect: ``processing`` with no live consumer.

Neither state self-heals, because the queue message — not the row — was the only
thing driving the work. This reaper inverts that: a leader-locked APScheduler
tick scans for records whose last touch predates the queue TTL and republishes a
``ProcessMatchLogEvent`` for each, so the row is what drives the work. Requeueing
is safe — ``flows.process_match_log`` dedupes on content hash, so a log that did
finish is finalized without a second parse.

``attempts`` (bumped by ``log_records.set_processing``) bounds the loop: a log
that kills the worker before it can mark itself failed is retried a few times and
then marked ``failed`` with an explicit message, instead of cycling forever.
Requeues that are never picked up don't consume an attempt, so a slow backlog
drains rather than burning its budget.

``failed`` records are left alone on purpose — the parser rejected them, so
auto-retrying is a loop on bad data. Operators retry those from the console.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from shared.messaging.config import PROCESS_MATCH_LOG_QUEUE
from shared.models.ingestion.log_processing import LogProcessingStatus
from shared.observability import metrics, observe_scheduled_job, publish_message
from shared.repository.support import LogProcessingRepository, stalled_conditions
from shared.schemas.events import ProcessMatchLogEvent
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
)
from shared.services.scheduler import IntervalScheduler
from src.core import db
from src.core.broker import require_broker
from src.core.config import settings
from src.services.match_logs import realtime as logs_realtime

# Re-exported: a test constructs this directly to pin the exact WHERE shape,
# and the module attribute must stay resolvable as ``reaper.stalled_conditions``.
__all__ = ("ReaperResult", "reclaim_stalled_logs", "stalled_conditions")

LEADER_LOCK_KEY = "log_processing:reaper:leader"

_scheduler = IntervalScheduler(job_id="match_log_stall_reaper", label="Match-log stall reaper")
_log_processing_repo = LogProcessingRepository()


@dataclass(frozen=True)
class ReaperResult:
    """Outcome of one reaper pass."""

    requeued: int = 0
    exhausted: int = 0

    @property
    def touched(self) -> int:
        return self.requeued + self.exhausted


@dataclass(frozen=True)
class _Stalled:
    """A record claimed for requeue, flattened before the session closes."""

    record_id: int
    tournament_id: int
    filename: str
    workspace_id: int | None


async def _claim_stalled(
    session: Any,
    *,
    now: datetime,
    pending_after_seconds: int,
    processing_after_seconds: int,
    max_attempts: int,
    limit: int,
) -> tuple[list[_Stalled], list[int]]:
    """Reset stalled rows in one transaction; return what to publish and what died.

    Rows are stamped with ``updated_at=now`` even when the status is already
    ``pending`` (a no-op status assignment would not flush, leaving the row
    eligible again on the very next tick).
    """
    records = await _log_processing_repo.claim_stalled(
        session,
        now=now,
        pending_after_seconds=pending_after_seconds,
        processing_after_seconds=processing_after_seconds,
        limit=limit,
    )

    requeue: list[_Stalled] = []
    exhausted: list[int] = []
    for record in records:
        if (record.attempts or 0) >= max_attempts:
            record.status = LogProcessingStatus.failed
            record.finished_at = now
            record.error_message = (
                f"Processing abandoned after {record.attempts} attempts without a terminal result "
                "(worker died mid-parse or the log is unprocessable). Retry manually to try again."
            )
            exhausted.append(record.id)
            continue

        record.status = LogProcessingStatus.pending
        record.started_at = None
        record.finished_at = None
        record.updated_at = now
        requeue.append(
            _Stalled(
                record_id=record.id,
                tournament_id=record.tournament_id,
                filename=record.filename,
                workspace_id=record.tournament.workspace_id if record.tournament else None,
            )
        )

    # Staged inside the claim transaction rather than after it: the monitor must
    # only learn about a requeue that actually persisted.
    for workspace_id in {item.workspace_id for item in requeue if item.workspace_id}:
        await logs_realtime.emit_logs_updated(session, workspace_id, change="requeued")

    await session.commit()
    return requeue, exhausted


async def reclaim_stalled_logs(
    *,
    redis: Any,
    broker: Any | None = None,
    session_factory: Any = db.async_session_maker,
    now: datetime | None = None,
) -> ReaperResult:
    """One recovery pass: requeue stalled records, retire the spent ones.

    Leader-locked so replicas don't publish the same batch. Returns the pass
    outcome; never raises — a failed tick is logged and retried on the next one.
    """
    cfg = settings
    if not cfg.log_reaper_enabled:
        return ReaperResult()

    try:
        token = await acquire_distributed_lock(
            redis,
            LEADER_LOCK_KEY,
            ttl_seconds=cfg.log_reaper_tick_seconds * 2,
            acquire_timeout_seconds=0.5,
        )
    except DistributedLockUnavailable:
        return ReaperResult()  # another replica reaps this tick

    moment = now or datetime.now(UTC)
    async with observe_scheduled_job("match_log_stall_reaper"):
        try:
            async with session_factory() as session:
                requeue, exhausted = await _claim_stalled(
                    session,
                    now=moment,
                    pending_after_seconds=cfg.log_reaper_pending_after_seconds,
                    processing_after_seconds=cfg.log_reaper_processing_after_seconds,
                    max_attempts=cfg.log_reaper_max_attempts,
                    limit=cfg.log_reaper_batch_size,
                )

            if not requeue and not exhausted:
                return ReaperResult()

            # Publish only after the reset committed: a message for a row we failed to
            # persist would be processed against stale state.
            published = 0
            target = require_broker(broker)
            for item in requeue:
                event = ProcessMatchLogEvent(tournament_id=item.tournament_id, filename=item.filename)
                try:
                    await publish_message(target, event.model_dump(), PROCESS_MATCH_LOG_QUEUE, logger=logger)
                except Exception:
                    # The row stays pending and is picked up again once its window
                    # reopens, so a broker blip costs a delay, not the work.
                    logger.exception(
                        f"Failed to requeue stalled match log record={item.record_id} filename={item.filename}"
                    )
                    continue
                published += 1

            metrics.count("parser.match_log.reclaimed", published, attributes={"outcome": "requeued"})
            metrics.count("parser.match_log.reclaimed", len(exhausted), attributes={"outcome": "exhausted"})
            logger.info(
                "Match-log reaper: stalled={} requeued={} exhausted={}",
                len(requeue) + len(exhausted),
                published,
                len(exhausted),
            )
            return ReaperResult(requeued=published, exhausted=len(exhausted))
        except Exception:
            logger.exception("Match-log stall recovery tick failed")
            return ReaperResult()
        finally:
            await release_distributed_lock(redis, token)


def start_scheduler(*, redis: Any, broker: Any | None = None) -> None:
    if not settings.log_reaper_enabled:
        return
    _scheduler.start(
        reclaim_stalled_logs,
        seconds=settings.log_reaper_tick_seconds,
        kwargs={"redis": redis, "broker": broker},
    )


def shutdown_scheduler() -> None:
    _scheduler.shutdown()
