from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Coroutine, Hashable, Iterable
from typing import Any, TypeVar

from cashews import cache

from src.core import config

T = TypeVar("T")

# Single source of truth for the cache-key prefixes this service registers.
#
# cashews has no default backend: it routes every operation (get/set)
# to the backend whose registered prefix the key starts with, and raises
# ``NotConfiguredError`` for keys that match no prefix.
CACHE_PREFIXES: tuple[str, ...] = ("fastapi:", "backend:")


def configure_cache() -> None:
    """Configure the cashews cache backends for the current process.

    The cashews ``cache`` singleton is process-global, so every entrypoint that
    can read/write the cache -- or trigger cache invalidation -- must call this;
    otherwise after-commit cache invalidation raises ``NotConfiguredError``.
    """
    urls = {
        "fastapi:": config.settings.api_cache_url,
        "backend:": config.settings.backend_cache_url,
    }
    for prefix in CACHE_PREFIXES:
        # KeyError here is intentional: adding a prefix to CACHE_PREFIXES without
        # a backend URL must fail loudly at startup, not silently at invalidation.
        cache.setup(urls[prefix], prefix=prefix)


def canonical_entities(entities: Iterable[str] | None, allowed: Collection[str]) -> list[str]:
    """``entities`` as a cached read's key should carry them: only those whose root (the part before the first
    ``.``) the read honours, de-duplicated and sorted. The client's raw list would make one cache entry per spelling
    and order of the same request."""
    return sorted({entity for entity in entities or () if entity.partition(".")[0] in allowed})


# One build per burst: an invalidation makes every connected viewer refetch the same read at once, and N identical
# builds would queue behind the rpc channel's prefetch. Followers await the leader's task.
_inflight: dict[Hashable, asyncio.Task[Any]] = {}


async def single_flight(key: Hashable, build: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run ``build`` once for every concurrent caller passing an equal ``key``.

    ``key`` names everything the result depends on, the read's cache generations included: a request arriving after
    a write starts its own build instead of joining one that read before it. The result is shared, so ``build`` runs
    on a session of its own, never on one caller's -- and the callers run their viewer-dependent gates before this.
    """
    task = _inflight.get(key)
    if task is None:
        task = asyncio.create_task(build())
        _inflight[key] = task

        def _cleanup(done: asyncio.Task[Any]) -> None:
            if _inflight.get(key) is done:
                del _inflight[key]

        task.add_done_callback(_cleanup)
    # Shielded: a follower's own cancellation (its caller disconnected or hit its deadline) must not cancel the
    # shared build out from under every other follower -- ``Task.cancel()`` does propagate into the future a task
    # is awaiting.
    return await asyncio.shield(task)
