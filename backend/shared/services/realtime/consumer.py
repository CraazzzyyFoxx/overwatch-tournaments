"""Cross-service invalidation consumer.

``emit`` bumps the shared cache generations at the writer's commit; a service
registers this once to re-bump them from the durable outbox row, so a bump lost
there is retried instead of leaving cached reads stale until their TTL. A
generation already bumped after the event is left alone (every consuming
service gets the event; re-bumping would only orphan entries cached since).
WHICH cached reads a resource moves is said where each read is cached
(``shared.services.cache_generations.versioned``), not here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from faststream.rabbit import RabbitMessage

from shared.schemas.events import CacheInvalidatedEvent
from shared.services.cache_generations import bump_unless_bumped_since
from shared.services.realtime.resources import Resource, resource_generation

__all__ = ("invalidate_from_event", "register_invalidation_consumer")

ExtraHandler = Callable[[CacheInvalidatedEvent], Awaitable[None]]


async def invalidate_from_event(
    event: CacheInvalidatedEvent,
    *,
    unknown_resources: Callable[[Iterable[str]], None] | None = None,
) -> int:
    """Re-bump the generations of every resource the event names whose commit-time bump was lost.

    Returns how many resources the event named in this build's vocabulary.

    A resource outside this build's vocabulary (a newer publisher) is skipped: nothing here can be keyed by it.
    """
    unknown: list[str] = []
    generations: list[str] = []
    for name in event.resources:
        try:
            resource = Resource(name)
        except ValueError:
            unknown.append(name)
            continue
        generations += (resource_generation(resource, event.scope_id), resource_generation(resource))
    await bump_unless_bumped_since(int(event.timestamp * 1000), *generations)
    if unknown and unknown_resources is not None:
        unknown_resources(unknown)
    return len(generations) // 2


def register_invalidation_consumer(
    broker: Any,
    logger: Any,
    *,
    queue: Any,
    exchange: Any,
    channel: Any = None,
    on_event: ExtraHandler | None = None,
) -> None:
    """Subscribe this service to ``cache.invalidation``.

    ``on_event`` is for work a service wants to hang off an invalidation beyond
    the generations (app-service debounces its hero-stats materialized-view
    refresh there). It runs after they are bumped.
    """
    from shared.observability import observe_message_processing

    subscriber_kwargs: dict[str, Any] = {"exchange": exchange}
    if channel is not None:
        subscriber_kwargs["channel"] = channel

    # `msg` MUST be annotated RabbitMessage: with a loose annotation FastStream
    # treats it as another payload field, every message fails validation and is
    # rejected straight into the DLQ.
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
                unknown_resources=lambda names: logger.debug(
                    f"Unknown resources {sorted(names)} (scope {event.scope_kind}:{event.scope_id})"
                ),
            )
            if on_event is not None:
                await on_event(event)
