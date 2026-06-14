from __future__ import annotations

from cashews import cache

from src.core import config


def configure_cache() -> None:
    """Configure the cashews cache backends for the current process.

    The cashews ``cache`` singleton is process-global, so every entrypoint that
    can read/write the cache -- or trigger cache invalidation -- must call this.
    The API (``main``) and the worker (``serve``) run in separate processes, so
    each configures the cache independently. Skipping this in the worker made
    after-commit cache invalidation raise ``NotConfiguredError`` on every
    bracket/standings job.
    """
    cache.setup(config.settings.api_cache_url, prefix="fastapi:")
    cache.setup(config.settings.backend_cache_url, prefix="backend:")
