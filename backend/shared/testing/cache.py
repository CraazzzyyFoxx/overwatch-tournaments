"""Unified cashews cache setup for tests.

The cashews ``cache`` singleton is process-global with no default backend --
every entrypoint (each service's ``serve*.py``) calls its own
``configure_cache()`` before any subscriber runs, or a cache read/write/
invalidation raises ``NotConfiguredError``. Tests that import cache-touching
code must configure the same singleton in-process.

Routes every known prefix to an in-memory (``mem://``) backend rather than a
service's real ``configure_cache()`` (which points at Redis via
``settings.*_cache_url``): tests get the exact same "every prefix is routable"
guarantee without depending on a reachable Redis, matching the rest of the
suite (CI runs with no external services -- see ``test-backend.yml``).
"""

from __future__ import annotations

from typing import Any

from cashews import cache

_REDIS_SCHEMES = frozenset({"redis", "rediss", "unix"})

#: Union of every prefix any service's ``configure_cache()`` registers --
#: see ``CACHE_PREFIXES``/``CACHE_LOCK_PREFIX``/``CACHE_PING_PREFIXES`` in
#: app-service/balancer-service/stats-service/tournament-service's
#: ``src/core/caching.py`` -- plus the cache generations ``configure_realtime``
#: routes (``shared.services.cache_generations``). Configuring the full union up
#: front means a test importing any service's cache-decorated code never hits an
#: unrouted prefix, regardless of which subset that particular service registers.
_TEST_CACHE_PREFIXES: tuple[str, ...] = ("fastapi:", "backend:", "lock:", "LOCK", "PING", "cachegen:")


def configure_test_cache(*extra_prefixes: str) -> None:
    """Route every known cashews prefix to an in-memory backend for tests."""
    for prefix in (*_TEST_CACHE_PREFIXES, *extra_prefixes):
        cache.setup("mem://", prefix=prefix)


def pin_cache_in_memory() -> None:
    """Make the cashews singleton unable to hold a Redis backend.

    Importing a service entrypoint (``serve.py``, ``lifecycle``) calls the service's real ``configure_cache()`` /
    ``configure_realtime()``, which ``cache.setup`` a Redis URL over the in-memory routes and makes every later cache
    op dial the dead port -- whichever test imports it first decides, so it was also order-dependent. Every Redis URL
    handed to ``cache.setup`` becomes ``mem://``; the prefix and options still apply.
    """
    if getattr(cache.setup, "_pinned_in_memory", False):
        return
    real_setup = cache.setup

    def setup(settings_url: str, *args: Any, **kwargs: Any) -> Any:
        if settings_url.partition(":")[0] in _REDIS_SCHEMES:
            settings_url = "mem://"
        return real_setup(settings_url, *args, **kwargs)

    setup._pinned_in_memory = True  # type: ignore[attr-defined]
    cache.setup = setup  # type: ignore[method-assign,assignment]
