from __future__ import annotations

from cashews import cache

from src.core import config

# Single source of truth for the cache-key prefixes this service registers.
#
# cashews has no default backend: it routes every operation (get/set/delete_match)
# to the backend whose registered prefix the key starts with, and raises
# ``NotConfiguredError`` for keys that match no prefix. Cache-invalidation
# patterns are generated from this tuple (see ``cache_invalidation``) so they
# always stay routable and in sync with ``configure_cache``.
CACHE_PREFIXES: tuple[str, ...] = ("fastapi:", "backend:")


def configure_cache() -> None:
    """Configure the cashews cache backends for the current process.

    The cashews ``cache`` singleton is process-global, so every entrypoint that
    can read/write the cache -- or trigger cache invalidation -- must call this.
    The API (``main``) and the worker (``serve``) run in separate processes, so
    each configures the cache independently. Skipping this in the worker made
    after-commit cache invalidation raise ``NotConfiguredError`` on every
    bracket/standings job.
    """
    urls = {
        "fastapi:": config.settings.api_cache_url,
        "backend:": config.settings.backend_cache_url,
    }
    for prefix in CACHE_PREFIXES:
        # KeyError here is intentional: adding a prefix to CACHE_PREFIXES without
        # a backend URL must fail loudly at startup, not silently at invalidation.
        cache.setup(urls[prefix], prefix=prefix)
