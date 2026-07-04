from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.platform.realtime import WorkspaceEvent
from shared.schemas.realtime import EventFrame, WorkspaceEventEnvelope
from shared.services.realtime_topics import realtime_channel

__all__ = (
    "event_to_envelope",
    "publish_envelope_to_redis",
    "publish_event",
    "publish_event_to_redis_url",
)


def event_to_envelope(event: WorkspaceEvent) -> WorkspaceEventEnvelope:
    return WorkspaceEventEnvelope(
        event_id=int(event.id),
        event_type=event.event_type,
        schema_version=event.schema_version,
        occurred_at=event.occurred_at,
        actor_user_id=event.actor_user_id,
        data=event.payload,
    )


async def publish_envelope_to_redis(
    redis: Redis,
    *,
    topic: str,
    envelope: WorkspaceEventEnvelope,
) -> None:
    frame = EventFrame(topic=topic, event=envelope)
    await redis.publish(
        realtime_channel(topic),
        frame.model_dump_json(),
    )


async def publish_event_to_redis_url(
    redis_url: str,
    *,
    topic: str,
    envelope: WorkspaceEventEnvelope,
) -> None:
    redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        await publish_envelope_to_redis(redis, topic=topic, envelope=envelope)
    finally:
        await redis.aclose()


async def publish_event(
    session: AsyncSession,
    redis: Redis | None,
    *,
    topic: str,
    event_type: str,
    payload: dict[str, Any],
    workspace_id: int | None = None,
    tournament_id: int | None = None,
    actor_user_id: int | None = None,
    schema_version: int = 1,
) -> WorkspaceEventEnvelope:
    event = WorkspaceEvent(
        topic=topic,
        event_type=event_type,
        workspace_id=workspace_id,
        tournament_id=tournament_id,
        actor_user_id=actor_user_id,
        schema_version=schema_version,
        payload=payload,
    )
    session.add(event)
    await session.flush()

    # PostgreSQL normally returns server defaults. Keep tests and alternate
    # dialects predictable if occurred_at was not populated by RETURNING.
    if event.occurred_at is None:
        event.occurred_at = datetime.now(UTC)

    envelope = event_to_envelope(event)
    if redis is not None:
        try:
            await publish_envelope_to_redis(redis, topic=topic, envelope=envelope)
        except Exception:
            logger.exception("Failed to publish realtime event", topic=topic, event_type=event_type)
    return envelope
