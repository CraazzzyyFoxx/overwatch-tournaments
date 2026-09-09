"""Resource -> this service's cashews key patterns.

app-service caches user-facing aggregates (profiles, leaderboards, achievement
rarity) that a tournament write moves without naming a user, so several
resources here fan out deliberately broadly — bounded by ``users_cache_ttl``.

``tests/test_cache_resources.py`` asserts this table covers every
tournament-scoped resource; an explicitly empty tuple is how "this service
caches nothing of that" is said out loud, which matters because the previous
consumer expressed the same thing as ``if reason == "bracket_changed": return``
— an early return nothing pointed at.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from shared.schemas.events import CacheInvalidatedEvent
from shared.services.realtime import Resource, Scope
from shared.services.realtime.consumer import invalidate_from_event
from src.core.caching import CACHE_PREFIXES
from src.services import user_cache

__all__ = ("RESOURCE_CACHE_PATTERNS", "invalidate_local")


def _with_prefixes(*suffixes: str) -> tuple[str, ...]:
    return tuple(f"{prefix}{suffix}" for suffix in suffixes for prefix in CACHE_PREFIXES)


def _tournament_wide(tournament_id: int) -> tuple[str, ...]:
    return (
        # Subsumes the /standings sub-path as well.
        *_with_prefixes(f"*tournaments/{tournament_id}*"),
        # User-scoped flow caches (profile, tournaments, heroes, encounters,
        # maps, teammates, compare) aggregate ACROSS tournaments and we do not
        # know which users this one touched, so they all go. Single source of
        # truth: services.user_cache.
        *user_cache.tournament_user_cache_patterns(),
        # Cached Users-Overview id order: a tournament change can reorder the
        # tournaments_count / achievements_count / avg_placement leaderboard.
        "backend:user_overview_order:*",
        # Rarity = distinct earners / total players; both move with match data.
        # Workspace-scoped, and the event does not carry the workspace, so all
        # of them — bounded by achievements_cache_ttl.
        "backend:achievement_rarity_map:*",
    )


RESOURCE_CACHE_PATTERNS: dict[str, Callable[[int], Sequence[str]]] = {
    Resource.TOURNAMENT_STANDINGS: _tournament_wide,
    Resource.TOURNAMENT_TEAMS: _tournament_wide,
    Resource.TOURNAMENT_STRUCTURE: _tournament_wide,
    Resource.TOURNAMENT_DETAIL: _tournament_wide,
    Resource.TOURNAMENT_STAGES: _tournament_wide,
    # Deliberately nothing: a score report moves no aggregate this service
    # caches, and the old consumer skipped its `bracket_changed` equivalent for
    # exactly that reason. The expensive part here is the user-cache fan-out,
    # and paying it per encounter write would be a self-inflicted SCAN storm.
    Resource.TOURNAMENT_ENCOUNTERS: lambda _tid: (),
    # Registration writes move participants_count on the tournament read, which
    # this service does not serve, and no user aggregate.
    Resource.TOURNAMENT_REGISTRATIONS: lambda _tid: (),
    Resource.TOURNAMENT_REGISTRATION_FORM: lambda _tid: (),
    Resource.TOURNAMENT_STREAMS: lambda _tid: (),
}


async def invalidate_local(
    scope: Scope,
    resources: frozenset[Resource],
    entity_ids: Mapping[str, Sequence[int]],
) -> None:
    """``configure_realtime``'s hook for what THIS process emitted.

    Same table as the queue consumer, because a resource does not mean
    something different depending on which side of the broker it arrived from.
    """
    await invalidate_from_event(
        CacheInvalidatedEvent(
            scope_kind=str(scope.kind),
            scope_id=scope.id,
            resources=[str(r) for r in resources],
            entity_ids={key: [int(v) for v in values] for key, values in entity_ids.items()},
        ),
        RESOURCE_CACHE_PATTERNS,
    )
