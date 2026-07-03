from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.outbox import EventOutbox

PENDING_STATUSES = ("pending", "failed")


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
) -> EventOutbox:
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
    session.add(row)
    await session.flush()
    return row


async def publish_pending_outbox_events(
    session: AsyncSession,
    broker: Any,
    *,
    limit: int = 100,
    now: datetime | None = None,
    commit: bool = True,
) -> int:
    now = now or datetime.now(UTC)
    result = await session.execute(
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
    rows = list(result.scalars().all())
    published = 0

    for row in rows:
        try:
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
            row.status = "failed"
            row.attempts += 1
            row.last_error = str(exc)
            row.next_attempt_at = now + _retry_delay(row.attempts)
            logger.warning(
                f"Outbox publish failed for event {row.event_id} "
                f"(type={row.event_type}, attempt={row.attempts}): {exc}"
            )
        else:
            row.status = "published"
            row.published_at = now
            row.last_error = None
            published += 1

        await session.flush()
        if commit:
            await session.commit()

    return published


def _retry_delay(attempts: int) -> timedelta:
    return timedelta(seconds=min(2**max(attempts - 1, 0), 300))
