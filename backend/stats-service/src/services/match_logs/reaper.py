"""Stall recovery for match-log processing.

``stats.ingest.<discipline>`` carries ``x-message-ttl=300000``, so a ``ProcessIngestJobEvent``
that isn't consumed within five minutes is dead-lettered — and nothing looks at
the native ingest job again. A batch upload larger than the worker chews in
five minutes, a worker restart, or a publish that failed after the row committed
all leave records sitting on ``pending`` forever. A worker killed mid-parse
leaves the twin defect: ``processing`` with no live consumer.

Neither state self-heals, because the queue message — not the row — was the only
thing driving the work. This reaper inverts that: a leader-locked APScheduler
tick scans for records whose last touch predates the queue TTL and stages a fresh
ingest-request outbox event for each in the same transaction as the reset, so the
row is what drives the work and there is no committed-but-unpublished gap.
Requeueing is safe — terminal native jobs are returned unchanged and active revisions
serialize on the encounter/game and job locks.

``attempts`` (bumped by the processing transition) bounds the loop: a log
that kills the worker before it can mark itself failed is retried a few times and
then marked ``failed`` with an explicit message, instead of cycling forever.
Requeues that are never picked up don't consume an attempt, so a slow backlog
drains rather than burning its budget.

``failed`` and ``awaiting_link`` jobs are operator work, not stalls; the reaper
never retries them. Operators link/retry those from the console.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from shared.models import IngestJobStatus
from shared.observability import metrics, observe_scheduled_job
from shared.repository.stats import IngestJobRepository, stalled_conditions
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
)
from shared.services.scheduler import IntervalScheduler
from src.core import db
from src.core.config import settings
from src.services.match_logs.log_records import log_records_service

__all__ = ("ReaperResult", "reclaim_stalled_logs", "stalled_conditions")

LEADER_LOCK_KEY = "log_processing:reaper:leader"


def leader_lock_key(disciplines: Sequence[str] | None) -> str:
    """One leader per discipline set: a worker only reaps its own disciplines, so it must not starve another's."""
    return LEADER_LOCK_KEY if not disciplines else f"{LEADER_LOCK_KEY}:{','.join(sorted(set(disciplines)))}"


_scheduler = IntervalScheduler(job_id="match_log_stall_reaper", label="Match-log stall reaper")
_log_processing_repo = IngestJobRepository()


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
    tournament_id: int | None
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
    disciplines: Sequence[str] | None = None,
) -> tuple[list[_Stalled], list[int]]:
    """Reset stalled rows and stage their ingest requests in one transaction; return what was requeued and what died.

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
        disciplines=disciplines,
    )

    requeue: list[_Stalled] = []
    exhausted: list[int] = []
    for record in records:
        if (record.attempts or 0) >= max_attempts:
            await log_records_service.transition(
                session,
                record,
                IngestJobStatus.FAILED,
                now=now,
                error_message=f"Processing abandoned after {record.attempts} attempts without a terminal result. Retry manually.",
            )
            exhausted.append(record.id)
            continue

        # The PENDING transition stages the ingest request on this same commit.
        await log_records_service.transition(session, record, IngestJobStatus.PENDING, now=now)
        requeue.append(
            _Stalled(
                record_id=record.id,
                tournament_id=record.hint_tournament_id,
                filename=record.filename,
                workspace_id=record.workspace_id,
            )
        )

    await session.commit()
    return requeue, exhausted


async def reclaim_stalled_logs(
    *,
    redis: Any,
    session_factory: Any = db.async_session_maker,
    now: datetime | None = None,
    disciplines: Sequence[str] | None = None,
) -> ReaperResult:
    """One recovery pass: requeue stalled records, retire the spent ones.

    Leader-locked so replicas don't reset the same batch. Returns the pass
    outcome; never raises — a failed tick is logged and retried on the next one.
    """
    cfg = settings
    if not cfg.log_reaper_enabled:
        return ReaperResult()

    try:
        token = await acquire_distributed_lock(
            redis,
            leader_lock_key(disciplines),
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
                    disciplines=disciplines,
                )

            if not requeue and not exhausted:
                return ReaperResult()

            # The ingest requests were committed to the outbox with the reset itself, so delivery
            # outlives a broker outage and there is no reset-without-request window.
            metrics.count("stats.ingest.reclaimed", len(requeue), attributes={"outcome": "requeued"})
            metrics.count("stats.ingest.reclaimed", len(exhausted), attributes={"outcome": "exhausted"})
            logger.info(
                "Match-log reaper: stalled={} requeued={} exhausted={}",
                len(requeue) + len(exhausted),
                len(requeue),
                len(exhausted),
            )
            return ReaperResult(requeued=len(requeue), exhausted=len(exhausted))
        except Exception:
            logger.exception("Match-log stall recovery tick failed")
            return ReaperResult()
        finally:
            await release_distributed_lock(redis, token)


def start_scheduler(*, redis: Any, disciplines: Sequence[str] | None = None) -> None:
    if not settings.log_reaper_enabled:
        return
    _scheduler.start(
        reclaim_stalled_logs,
        seconds=settings.log_reaper_tick_seconds,
        kwargs={"redis": redis, "disciplines": disciplines},
    )


def shutdown_scheduler() -> None:
    _scheduler.shutdown()
