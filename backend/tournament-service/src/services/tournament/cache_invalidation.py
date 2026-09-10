"""The local half of an invalidation: drop this service's own cashews keys.

Wired into ``configure_realtime(cache_invalidator=...)`` at the entrypoint, so
``emit`` runs it after the caller's commit and BEFORE anything is published —
without that ordering a client reacting to the event could repopulate a gateway
entry from a value we were a millisecond away from clearing.

WHICH keys a resource maps to is ``cache_resources.py``'s business; this module
is only the loop that applies them. It replaced the old
reason-keyed pattern table, which asked the caller for a WHY and re-derived the
WHAT from it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from cashews import cache

from shared.services.realtime import Resource, Scope, ScopeKind
from src.services.tournament.cache_resources import patterns_for

__all__ = ("invalidate_tournament_resources",)


async def invalidate_tournament_resources(
    scope: Scope,
    resources: frozenset[Resource],
    _entity_ids: Mapping[str, Sequence[int]] | None = None,
) -> None:
    """Drop every cashews key the scope's stale resources map to.

    ``entity_ids`` is ignored: cashews matches by key glob, and none of this
    service's keys carry the entity id a publisher could narrow by, so honouring
    it would mean pretending to a precision the key shape does not have.
    """
    if scope.kind is not ScopeKind.TOURNAMENT:
        # Workspace/user resources are somebody else's cache; the shared
        # invalidator hands us every scope this process emits.
        return

    # Resource sets overlap by design (``structure`` subsumes ``detail``), and a
    # Redis SCAN per pattern is the whole cost of an invalidation — deduplicate
    # before spending it rather than after.
    seen: set[str] = set()
    for resource in sorted(resources):
        for pattern in patterns_for(str(resource), scope.id):
            if pattern in seen:
                continue
            seen.add(pattern)
            await cache.delete_match(pattern)
