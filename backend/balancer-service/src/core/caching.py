"""Cashews cache configuration shared by the HTTP app and the headless worker.

The cashews singleton is process-global and has no default backend; ``@cache``
flows raise ``NotConfiguredError`` until ``cache.setup`` runs. ``main.py`` (HTTP)
configures it at import; the worker (``serve.py``) must call ``configure_cache``
explicitly before any RPC subscriber runs, or read paths that hit the cache fail.
See lesson: cashews-worker-not-configured.
"""

from __future__ import annotations

from cashews import cache

from src.core.config import config

_configured = False


def configure_cache() -> None:
    global _configured
    if _configured:
        return
    cache.setup(f"{config.redis_url}/4", prefix="backend:")
    _configured = True
