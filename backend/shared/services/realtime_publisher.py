"""Wire-level helpers behind ``shared.services.realtime.emit``.

The Redis leg only: turning a persisted ``WorkspaceEvent`` into the envelope
clients receive, and putting a frame on the channel. The publication POLICY —
when, in what order, on whose session — belongs to ``emit``. The one other
caller is stats-service's catalog sync, whose progress belongs to no transaction
and goes straight to ``publish_envelope_to_redis``.
"""

from __future__ import annotations

import asyncio

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


#: The emit path's publisher: one pooled client per event loop and URL, made by the loop's first publish. A client
#: is bound to the loop that opened its connections, and a service runs one loop for its life, so in practice this
#: is one client per process.
_pooled: tuple[asyncio.AbstractEventLoop, str, Redis] | None = None


def _pooled_client(redis_url: str) -> Redis:
    global _pooled
    loop = asyncio.get_running_loop()
    if _pooled is None or _pooled[0] is not loop or _pooled[1] != redis_url:
        _pooled = (loop, redis_url, Redis.from_url(redis_url, decode_responses=True))
    return _pooled[2]


async def publish_event_to_redis_url(
    redis_url: str,
    *,
    topic: str,
    envelope: WorkspaceEventEnvelope,
) -> None:
    """Publish on the loop's pooled client: a pick publishes two or three events and a chat message one, and each
    used to pay a fresh connection."""
    await publish_envelope_to_redis(_pooled_client(redis_url), topic=topic, envelope=envelope)
