from __future__ import annotations

from typing import Any

from cashews import cache
from faststream.rabbit import RabbitMessage
from shared.messaging.config import TOURNAMENT_CHANGED_APP_QUEUE, TOURNAMENT_CHANGED_EXCHANGE
from shared.observability import observe_message_processing
from shared.schemas.events import TournamentChangedEvent

from src.core.caching import CACHE_PREFIXES


def _with_prefixes(*suffixes: str) -> tuple[str, ...]:
    """Expand each cache-key suffix to every configured backend prefix.

    cashews routes ``delete_match`` by key prefix and has no default backend, so
    a pattern that starts with no registered prefix raises ``NotConfiguredError``
    (and aborts the rest of the invalidation loop). Generating patterns from
    ``CACHE_PREFIXES`` keeps every pattern routable and in sync with the
    registered backends.
    """
    return tuple(f"{prefix}{suffix}" for suffix in suffixes for prefix in CACHE_PREFIXES)


def tournament_standings_cache_patterns(tournament_id: int) -> tuple[str, ...]:
    # ``*tournaments/{id}*`` already subsumes the ``/standings`` sub-path, so a
    # separate standings pattern is redundant.
    return (
        *_with_prefixes(f"*tournaments/{tournament_id}*"),
        # User-scoped flow caches aggregate across tournaments — we don't know
        # which users touched this tournament, so invalidate them broadly.
        # TTL is short (users_cache_ttl=60s) so the steady-state cost is low.
        "backend:user_profile:*",
        "backend:user_tournaments:*",
    )


async def invalidate_tournament_standings_cache(tournament_id: int) -> None:
    for pattern in tournament_standings_cache_patterns(tournament_id):
        await cache.delete_match(pattern)


async def handle_tournament_changed_event(data: dict[str, Any]) -> None:
    event = TournamentChangedEvent.model_validate(data)
    if event.reason == "bracket_changed":
        return
    await invalidate_tournament_standings_cache(event.tournament_id)


def register(broker: Any, logger: Any) -> None:
    """Register the cache-invalidation consumer on the headless worker's broker.

    Single owner of ``TOURNAMENT_CHANGED_APP_QUEUE`` (the app-worker). The HTTP
    service no longer hosts this — running it in two processes would round-robin
    invalidation messages between them.
    """

    @broker.subscriber(TOURNAMENT_CHANGED_APP_QUEUE, exchange=TOURNAMENT_CHANGED_EXCHANGE)
    async def process_tournament_changed(data: dict[str, Any], msg: RabbitMessage) -> None:
        async with observe_message_processing(
            queue=TOURNAMENT_CHANGED_APP_QUEUE,
            handler="process_tournament_changed",
            message=msg,
            logger=logger,
        ):
            await handle_tournament_changed_event(data)
