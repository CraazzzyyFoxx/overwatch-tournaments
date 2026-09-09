"""Cross-service invalidation consumer.

A service that caches reads registers this once, with its own
``resources -> cache-key patterns`` table. The table is local on purpose: only
the owning service knows how its keys are shaped, and the manifest
(``shared/realtime/resources.json``) is what keeps the vocabulary itself
shared. A parity test per service asserts the table covers exactly the
resources that service caches.

Replaces the ``tournament.changed`` consumers, which received a "reason" and
re-derived which of their own keys it implied — three copies of that derivation
existed and drifted apart (see the design doc's §1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any

from cashews import cache
from faststream.rabbit import RabbitMessage

from shared.schemas.events import CacheInvalidatedEvent

__all__ = ("ResourcePatterns", "invalidate_from_event", "register_invalidation_consumer")

#: ``resource -> callable(scope_id) -> cache-key patterns``. A callable, not a
#: format string: some resources fan out to patterns that do not mention the
#: scope id at all (cross-user aggregates), and hiding that behind ``%s``
#: substitution made the app-service table unreadable.
ResourcePatterns = Mapping[str, Callable[[int], Sequence[str]]]

ExtraHandler = Callable[[CacheInvalidatedEvent], Awaitable[None]]


async def invalidate_from_event(
    event: CacheInvalidatedEvent,
    patterns: ResourcePatterns,
    *,
    unknown_resources: Callable[[Iterable[str]], None] | None = None,
) -> int:
    """Drop every cache key the event's resources map to. Returns pattern count.

    A resource this service has no rule for is skipped, NOT treated as
    "invalidate everything": unlike the gateway (whose fail-safe is a cache
    miss), a broad ``delete_match`` here is a full SCAN over the keyspace on
    every unrelated event. The manifest parity test is what guarantees a
    resource this service does cache always has a rule.
    """
    unknown: list[str] = []
    applied = 0
    for resource in event.resources:
        build = patterns.get(resource)
        if build is None:
            unknown.append(resource)
            continue
        for pattern in build(event.scope_id):
            await cache.delete_match(pattern)
            applied += 1
    if unknown and unknown_resources is not None:
        unknown_resources(unknown)
    return applied


def register_invalidation_consumer(
    broker: Any,
    logger: Any,
    *,
    queue: Any,
    exchange: Any,
    patterns: ResourcePatterns,
    channel: Any = None,
    on_event: ExtraHandler | None = None,
) -> None:
    """Subscribe this service to ``cache.invalidation``.

    ``on_event`` is for work a service wants to hang off an invalidation beyond
    dropping keys (app-service debounces its hero-stats materialized-view
    refresh there). It runs after the keys are dropped.
    """
    from shared.observability import observe_message_processing

    subscriber_kwargs: dict[str, Any] = {"exchange": exchange}
    if channel is not None:
        subscriber_kwargs["channel"] = channel

    # `msg` MUST be annotated RabbitMessage: with a loose annotation FastStream
    # treats it as another payload field, every message fails validation and is
    # rejected straight into the DLQ (observed on the dev stand, 5/5 messages).
    @broker.subscriber(queue, **subscriber_kwargs)
    async def process_cache_invalidated(data: dict[str, Any], msg: RabbitMessage) -> None:
        async with observe_message_processing(
            queue=queue,
            handler="process_cache_invalidated",
            message=msg,
            logger=logger,
        ):
            event = CacheInvalidatedEvent.model_validate(data)
            await invalidate_from_event(
                event,
                patterns,
                unknown_resources=lambda names: logger.debug(
                    f"No local cache rule for resources {sorted(names)} (scope {event.scope_kind}:{event.scope_id})"
                ),
            )
            if on_event is not None:
                await on_event(event)
