"""Resource -> this service's cashews key patterns.

Local on purpose: only the owner of a cache knows how its keys are shaped. The
shared part is the vocabulary (``shared/realtime/resources.json``), and
``tests/test_cache_resources.py`` asserts this table covers every
tournament-scoped resource — an explicitly empty tuple is how "this service
caches nothing of that" is said out loud.

Replaces ``tournament_cache_patterns(reason)``: the publisher used to say WHY
and every consumer re-derived WHAT from it, three times, differently.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from shared.services.realtime import Resource
from src.core.caching import CACHE_PREFIXES

__all__ = ("RESOURCE_CACHE_PATTERNS", "patterns_for")


def _with_prefixes(*suffixes: str) -> tuple[str, ...]:
    """Expand each key suffix to every configured backend prefix.

    cashews routes ``delete_match`` by key prefix and has no default backend, so
    a pattern starting with no registered prefix raises ``NotConfiguredError``
    and aborts the rest of the invalidation loop.
    """
    return tuple(f"{prefix}{suffix}" for suffix in suffixes for prefix in CACHE_PREFIXES)


def _detail(tournament_id: int) -> tuple[str, ...]:
    # `tournaments/{id}:` covers get_read and every sub-read keyed under it.
    # The trailing `:` is NOT cosmetic: a bare `*` after the id makes
    # tournament 7 also purge 70, 72 and 700, so the busiest (lowest-id)
    # tournaments would evict everyone else's reads on every write.
    return _with_prefixes(f"*tournaments/{tournament_id}:*")


def _encounters(tournament_id: int) -> tuple[str, ...]:
    # Cross-tournament encounter keys (`encounters:{workspace}:None:...`) are
    # left to TTL: a per-tournament write must not SCAN every workspace's
    # unscoped list.
    return _with_prefixes(f"*encounters*:{tournament_id}:*")


def _standings(tournament_id: int) -> tuple[str, ...]:
    return _with_prefixes(f"*standings*:{tournament_id}:*")


def _teams(tournament_id: int) -> tuple[str, ...]:
    return _with_prefixes(f"*teams*:{tournament_id}:*")


RESOURCE_CACHE_PATTERNS: dict[str, Callable[[int], Sequence[str]]] = {
    Resource.TOURNAMENT_DETAIL: _detail,
    # Stages are served inside the tournament read model, not under a key of
    # their own.
    Resource.TOURNAMENT_STAGES: _detail,
    Resource.TOURNAMENT_ENCOUNTERS: lambda tid: (*_encounters(tid), *_standings(tid)),
    Resource.TOURNAMENT_STANDINGS: _standings,
    Resource.TOURNAMENT_TEAMS: _teams,
    Resource.TOURNAMENT_STRUCTURE: lambda tid: (
        *_detail(tid),
        *_teams(tid),
        *_encounters(tid),
        *_standings(tid),
    ),
    # The public participants list is cached on the RPC builder
    # (`registration_list:{id}:`); the tournament read embeds the live
    # participants_count / registrations_count.
    Resource.TOURNAMENT_REGISTRATIONS: lambda tid: (
        *_with_prefixes(f"*registration_list:{tid}:*"),
        *_detail(tid),
    ),
    # Uncached BY DESIGN, and it must stay that way: the form has exactly one
    # reader (`_common_service.get_registration_form`) and a stale form is
    # either a false refusal or a false admission — see
    # services/registration/admission.py's module docstring.
    Resource.TOURNAMENT_REGISTRATION_FORM: lambda _tid: (),
    # Stream reads live in stream-service; nothing of them is cached here.
    Resource.TOURNAMENT_STREAMS: lambda _tid: (),
}


def patterns_for(resource: str, tournament_id: int) -> Sequence[str]:
    build = RESOURCE_CACHE_PATTERNS.get(resource)
    return () if build is None else build(tournament_id)
