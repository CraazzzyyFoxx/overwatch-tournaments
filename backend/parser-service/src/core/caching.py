from __future__ import annotations

from cashews import cache

from src.core import config

# Single source of truth for the cache-key prefixes this service registers.
#
# cashews has no default backend: it routes every operation (get/set/delete_match)
# to the backend whose registered prefix the key starts with, and raises
# ``NotConfiguredError`` for keys that match no prefix. Any invalidation pattern
# must therefore start with a registered prefix (see
# ``lesson_cashews_prefixless_delete_match``).
CACHE_PREFIXES: tuple[str, ...] = ("backend:",)


def configure_cache() -> None:
    """Configure the cashews cache backends for the current process.

    The cashews ``cache`` singleton is process-global, so every entrypoint that
    can read/write the cache -- or trigger cache invalidation -- must call this
    (both the HTTP ``main`` and the headless ``serve`` worker; see
    ``lesson_cashews_worker_not_configured``).
    """
    cache.setup(f"{config.settings.redis_url}/4", prefix="backend:")
