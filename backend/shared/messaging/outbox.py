from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from prometheus_client import Counter, Gauge
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.messaging.config import EXCHANGES_BY_NAME
from shared.models.platform.outbox import EventOutbox
from shared.observability.worker import observe_scheduled_job
from shared.services.stats_evidence import capture_stats_evidence, owner_scopes, stage_stats_evidence

PENDING_STATUSES = ("pending", "failed")
#: Failed publishes after which a row is parked as ``dead``: kept for inspection, never drained again.
MAX_ATTEMPTS = 20
#: Bounds one publish (and the batch's exchange declares): a blocked broker (memory/disk alarm) never answers.
PUBLISH_TIMEOUT_SECONDS = 10
#: A batch starts no publish after this many seconds. Its transaction sits idle-in-transaction while it publishes, and
#: pgBouncer's ``idle_transaction_timeout`` (60 s) kills a connection idle longer, losing the batch's bookkeeping and
#: unlocking rows it already published for another drain to publish again. Budget + one publish timeout = 30 s.
BATCH_BUDGET_SECONDS = 20
#: How long ``purge_outbox`` keeps published rows (debugging) before deleting them.
PUBLISHED_RETENTION = timedelta(days=7)
PURGE_BATCH = 5000

OUTBOX_DEAD_TOTAL = Counter(
    "outbox_dead_total",
    f"Outbox rows parked as dead after {MAX_ATTEMPTS} failed publishes.",
)
OUTBOX_OLDEST_PENDING_AGE_SECONDS = Gauge(
    "outbox_oldest_pending_age_seconds",
    "Age of the oldest pending or failed event_outbox row (0 when none), as of this process's latest drain tick.",
)


async def drain_outbox(session_factory: Any, broker: Any, *, limit: int = 100) -> None:
    """One scheduler tick of the outbox relay, run by every service that writes outbox rows.

    Schedule it every second (``scheduler.add_job(drain_outbox, "interval", seconds=1, args=(factory, broker))``
    or ``IntervalScheduler.start(drain_outbox, seconds=1, args=(...))``). Concurrent drains across services and
    replicas are safe: the batch is taken ``FOR UPDATE SKIP LOCKED``, so no row is published by two of them.
    """
    async with observe_scheduled_job("event_outbox_drain"), session_factory() as session:
        published = await publish_pending_outbox_events(session, broker, limit=limit, commit=True)
        if published:
            logger.info("Published {} outbox events", published)


async def purge_outbox(session_factory: Any) -> int:
    """Delete published rows older than ``PUBLISHED_RETENTION``; returns how many went.

    Daily scheduler job. ``PURGE_BATCH`` rows per transaction so no single delete holds locks or bloats WAL for long.
    The batches walk the primary key upward from the last id deleted, so none rescans the dead tuples of the ones
    before it (a first purge of a never-purged table would otherwise be quadratic). Pending, failed and dead rows are
    never purged.
    """
    cutoff = datetime.now(UTC) - PUBLISHED_RETENTION
    deleted, last_id = 0, 0
    async with observe_scheduled_job("event_outbox_purge"):
        while True:
            batch = (
                select(EventOutbox.id)
                .where(EventOutbox.id > last_id, EventOutbox.status == "published", EventOutbox.published_at < cutoff)
                .order_by(EventOutbox.id)
                .limit(PURGE_BATCH)
            )
            statement = (
                delete(EventOutbox)
                .where(EventOutbox.id.in_(batch))
                .returning(EventOutbox.id)
                .execution_options(synchronize_session=False)
            )
            async with session_factory() as session:
                ids = list(await session.scalars(statement))
                await session.commit()
            deleted += len(ids)
            if len(ids) < PURGE_BATCH:
                break
            last_id = max(ids)
    if deleted:
        logger.info("Purged {} published outbox events", deleted)
    return deleted


def _name(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "name", value))


def _event_payload(event: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, BaseModel):
        return event.model_dump(mode="json")
    return dict(event)


async def enqueue_outbox_event(
    session: AsyncSession,
    event: BaseModel | dict[str, Any],
    *,
    exchange: Any,
    routing_key: str,
    event_id: str | None = None,
    event_type: str | None = None,
    flush: bool = True,
) -> EventOutbox:
    """Stage ``event`` in the caller's transaction; the drain publishes it after commit.

    ``flush=False`` only adds the row, for a caller that enqueues a batch and flushes once. A ``changed_tables``
    payload flushes regardless: its stats evidence is captured around the inserted row.
    """
    payload = _event_payload(event)
    resolved_event_id = str(event_id or payload.get("event_id") or "")
    if not resolved_event_id:
        raise ValueError("Outbox events require payload.event_id")

    row = EventOutbox(
        event_id=resolved_event_id,
        event_type=str(event_type or payload.get("event_type") or event.__class__.__name__),
        exchange=_name(exchange),
        routing_key=routing_key,
        payload_json=payload,
        status="pending",
        attempts=0,
    )
    before = None
    if "changed_tables" in payload:
        row.id = await session.scalar(text("SELECT nextval(pg_get_serial_sequence('event_outbox', 'id'))"))
        scopes = owner_scopes("outbox", (row.id,))
        before = await capture_stats_evidence(session, scopes=scopes)
    session.add(row)
    if flush or before is not None:
        await session.flush()
    if before is not None:
        after = await capture_stats_evidence(session, scopes=scopes)
        await stage_stats_evidence(
            session,
            operation="stats.reference_update",
            before=before,
            after=after,
            workspace_id=payload.get("workspace_id"),
            entity_type="event_outbox",
            entity_id=row.id,
        )
    return row


#: Exchange names this process has declared already; declaring is idempotent but costs a broker round trip.
_declared_exchanges: set[str] = set()


async def _declare_exchanges(broker: Any, names: set[str]) -> None:
    """Declare every known exchange the batch publishes to, once per process.

    An unknown name is left alone: its publish fails with the broker's own ``NOT_FOUND`` and the row backs off,
    which is the right signal for a routing key pointed at an exchange ``config.py`` does not define.
    """
    for name in names - _declared_exchanges:
        exchange = EXCHANGES_BY_NAME.get(name)
        if exchange is None:
            continue
        await broker.declare_exchange(exchange)
        _declared_exchanges.add(name)


async def publish_pending_outbox_events(
    session: AsyncSession,
    broker: Any,
    *,
    limit: int = 100,
    now: datetime | None = None,
    commit: bool = True,
) -> int:
    now = now or datetime.now(UTC)
    due = (
        select(EventOutbox)
        .where(
            EventOutbox.status.in_(PENDING_STATUSES),
            or_(
                EventOutbox.next_attempt_at.is_(None),
                EventOutbox.next_attempt_at <= now,
            ),
        )
        .order_by(EventOutbox.created_at.asc(), EventOutbox.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )

    # One locked batch, one commit at the end of it. The batch must stay locked
    # for as long as this drain is publishing it: every replica of every
    # producing service runs this each second, and a row released early is free
    # for another drain to take and publish a second time (duplicate Discord
    # DMs). That is what rules out a commit per row, which would also cost a
    # transaction, a ``SET LOCAL statement_timeout`` and a separate locking
    # SELECT per event. ``BATCH_BUDGET_SECONDS`` keeps that commit inside
    # pgBouncer's idle-in-transaction limit: rows the budget leaves untried stay
    # pending for the next tick. Delivery stays
    # at-least-once: a crash between a publish and the commit replays the whole
    # batch. No consumer dedupes on ``x-event-id``; every consumer is
    # idempotent through its own state instead (a job row's status, a
    # ``discord_message`` row, a cache key that is simply dropped again, a
    # version fence) — a new consumer must be too.
    # Table-wide, not this batch's: a failing row backs off out of every batch, and a broker outage fails them all.
    pending = select(func.min(EventOutbox.created_at)).where(EventOutbox.status.in_(PENDING_STATUSES))
    oldest = await session.scalar(pending)
    OUTBOX_OLDEST_PENDING_AGE_SECONDS.set(max((now - oldest).total_seconds(), 0) if oldest is not None else 0)
    rows = list(await session.scalars(due))
    if not rows:
        return 0

    loop = asyncio.get_running_loop()
    stop_at = loop.time() + BATCH_BUDGET_SECONDS
    async with asyncio.timeout(PUBLISH_TIMEOUT_SECONDS):
        await _declare_exchanges(broker, {row.exchange for row in rows if row.exchange})
    published = 0
    for row in rows:
        if loop.time() >= stop_at:
            break
        try:
            # A timed-out publish may still have reached the broker: the retry makes it at-least-once, as above.
            async with asyncio.timeout(PUBLISH_TIMEOUT_SECONDS):
                await broker.publish(
                    row.payload_json,
                    "",
                    row.exchange,
                    routing_key=row.routing_key,
                    message_id=row.event_id,
                    headers={"x-event-id": row.event_id},
                    persist=True,
                )
        except Exception as exc:
            _record_failure(row, exc, now)
            if isinstance(exc, TimeoutError):
                break  # a broker that sat on one publish (a resource alarm blocks every publisher) sits on the next
        else:
            row.status = "published"
            row.published_at = now
            row.last_error = None
            published += 1

    await session.flush()
    if commit:
        await session.commit()

    return published


def _record_failure(row: EventOutbox, exc: Exception, now: datetime) -> None:
    """Count a failed publish: back off, or park the row as ``dead`` on its ``MAX_ATTEMPTS``-th failure."""
    row.attempts += 1
    row.last_error = str(exc) or type(exc).__name__
    if row.attempts >= MAX_ATTEMPTS:
        row.status = "dead"
        OUTBOX_DEAD_TOTAL.inc()
        logger.error(
            f"Outbox event {row.event_id} (type={row.event_type}) is dead after {row.attempts} attempts: {row.last_error}"
        )
        return
    row.status = "failed"
    row.next_attempt_at = now + _retry_delay(row.attempts)
    logger.warning(
        f"Outbox publish failed for event {row.event_id} (type={row.event_type}, attempt={row.attempts}): "
        f"{row.last_error}"
    )


def _retry_delay(attempts: int) -> timedelta:
    return timedelta(seconds=min(2 ** max(attempts - 1, 0), 300))
