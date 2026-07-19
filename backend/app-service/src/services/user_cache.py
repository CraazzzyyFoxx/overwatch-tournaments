"""Single source of truth for invalidating the workspace-scoped ``/users/*``
read caches.

Every ``@cache`` in ``services.user.flows`` / ``services.map.flows`` stores its
result under a ``backend:`` key whose prefix is listed in
:data:`USER_CACHE_KEY_PREFIXES` and whose **first** template component is the
subject user's id. That invariant lets us derive two invalidation shapes from
one list:

* :func:`tournament_user_cache_patterns` — a broad ``{prefix}:*`` wipe used when
  tournament/match data changes (we can't know which users a tournament touched).
* :func:`user_cache_patterns` — a precise ``{prefix}:{user_id}:*`` wipe used when
  a single user's profile/identity changes (name, avatar, socials, merge).

Keep :data:`USER_CACHE_KEY_PREFIXES` in sync with the cache-key prefixes those
flows register; ``tests/test_user_cache_invalidation.py`` enforces routability.
"""

from __future__ import annotations

from cashews import cache

# Per-user read caches: every key is ``{prefix}:{user_id}:...`` (user id first).
USER_CACHE_KEY_PREFIXES: tuple[str, ...] = (
    "user_profile",
    "user_tournaments",
    "user_tournament_stats",
    "user_heroes",
    "user_encounters",
    "user_maps",
    "user_teammates",
    "user_matches_summary",
)

# Compare caches depend on *other* users too (target-user / cohort baselines), so
# they can never be scoped to a single subject id — they always invalidate
# broadly. Kept separate from the per-user prefixes above for that reason.
USER_COMPARE_KEY_PREFIXES: tuple[str, ...] = (
    "user_compare:v2",
    "user_hero_compare:v2",
)


def tournament_user_cache_patterns() -> tuple[str, ...]:
    """Broad ``delete_match`` patterns for a tournament/match data change.

    A tournament change can move standings, ranks and aggregates for any of its
    participants, and the aggregate caches (tournaments, heroes, encounters,
    maps, teammates, ...) fan across tournaments — so we cannot target specific
    users. Wipe every user read cache; staleness is bounded by
    ``users_cache_ttl`` regardless.
    """
    return tuple(
        f"backend:{prefix}:*" for prefix in (*USER_CACHE_KEY_PREFIXES, *USER_COMPARE_KEY_PREFIXES)
    )


def user_cache_patterns(user_id: int) -> tuple[str, ...]:
    """Precise ``delete_match`` patterns for a single user's profile/identity
    mutation.

    Drops the subject's own read caches exactly (``{prefix}:{user_id}:*``) and
    the shared compare namespaces broadly (a global/cohort baseline can shift
    when any user changes). Cross-user cosmetic staleness — this user's name or
    avatar embedded in *other* users' cached teammate/opponent lists — is left to
    the TTL, matching the pre-existing merge behaviour.
    """
    return (
        *(f"backend:{prefix}:{user_id}:*" for prefix in USER_CACHE_KEY_PREFIXES),
        *(f"backend:{prefix}:*" for prefix in USER_COMPARE_KEY_PREFIXES),
    )


async def invalidate_user_caches(user_id: int) -> None:
    """Drop every read cache scoped to ``user_id`` after a profile/identity edit."""
    for pattern in user_cache_patterns(user_id):
        await cache.delete_match(pattern)
