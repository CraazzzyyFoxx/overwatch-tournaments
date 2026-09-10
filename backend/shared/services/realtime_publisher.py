"""Wire-level helpers behind ``shared.services.realtime.emit``.

What is left here is the Redis leg: turning a persisted ``WorkspaceEvent`` into
the envelope clients receive, and putting a frame on the channel. The
publication POLICY — when, in what order, on whose session — belongs to
``emit``, which is the only caller.

The former ``publish_event`` / ``publish_patch`` entry points are gone: they
published inside the caller's transaction, before its commit, so an event could
describe a write that then rolled back.
"""

from __future__ import annotations

from redis.asyncio import Redis

from shared.models.platform.realtime import WorkspaceEvent
from shared.schemas.realtime import EventFrame, WorkspaceEventEnvelope
from shared.services.realtime_topics import realtime_channel

__all__ = (
    "PATCH_RESOURCE_KEY",
    "event_to_envelope",
    "publish_envelope_to_redis",
    "publish_event_to_redis_url",
)

# Payload key naming the client-cache resource a PATCH event mutates: a generic
# frontend applier folds the typed delta into the matching cached query instead
# of refetching the read model. Unrelated to the invalidation vocabulary — that
# one names what went stale, this one names what a payload can be applied to.
PATCH_RESOURCE_KEY = "resource"


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
    closing = False
    try:
        await publish_envelope_to_redis(redis, topic=topic, envelope=envelope)
    except GeneratorExit:
        # The coroutine is being *closed*, not cancelled -- what happens when the
        # event loop tears down (or a task is reclaimed) with a publish still in
        # flight. A closing coroutine may not suspend again, so awaiting the
        # client's teardown here raises ``RuntimeError: coroutine ignored
        # GeneratorExit`` and buries the shutdown that actually caused it. The
        # socket dies with the loop anyway.
        closing = True
        raise
    finally:
        if not closing:
            await redis.aclose()
