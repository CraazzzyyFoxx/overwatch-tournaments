"""Out-of-band refresh of the ``matches.mv_hero_global_stats`` materialized view.

The global per-(hero, stat) comparison on ``GET /users/{id}/heroes`` is
precomputed into a materialized view (see migration ``herostatmv01``). The heavy
aggregation that used to run inside the web request (and blew past
``statement_timeout`` on a cache miss) now happens here, off the request path.

Trigger model — debounced, event-driven:
  * app-worker startup fires a best-effort initial populate;
  * every ``TOURNAMENT_CHANGED`` event requests a refresh, throttled to at most
    one per cooldown window so a burst of events coalesces into a single refresh.

The refresh is scheduled as a background task (never blocks the event consumer),
runs with ``statement_timeout`` disabled for its transaction, and is guarded by a
Postgres advisory lock so two refreshers never collide.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import sqlalchemy as sa

_MV_QUALNAME = "matches.mv_hero_global_stats"
# Arbitrary constant advisory-lock key, unique to this refresh.
_ADVISORY_LOCK_KEY = 0x6865726F5F6756
# Debounce window: collapse a burst of change events into a single refresh.
_REFRESH_COOLDOWN_SECONDS = 600.0

_last_refresh_monotonic: float | None = None
# Keep references to in-flight refresh tasks so they aren't garbage-collected.
_background_tasks: set[asyncio.Task[Any]] = set()


async def refresh_hero_global_stats(session: Any) -> bool:
    """Run ``REFRESH MATERIALIZED VIEW`` for the hero global-stats view.

    Returns ``True`` if this call performed the refresh, ``False`` if another
    refresh already held the advisory lock. Uses ``CONCURRENTLY`` once the view
    is populated (no read lock); the very first refresh is a plain ``REFRESH``
    because the view is created ``WITH NO DATA`` and ``CONCURRENTLY`` requires an
    already-populated view.
    """
    # Heavy offline aggregation — lift the per-statement timeout for this txn.
    # All values interpolated below are module constants (never user input);
    # they are inlined rather than bound because ``:name::cast`` confuses the
    # text() bind-parser and ``to_regclass`` returns NULL (not an error) when the
    # view has not been created yet.
    await session.execute(sa.text("SET LOCAL statement_timeout = 0"))
    got_lock = (
        await session.execute(sa.text(f"SELECT pg_try_advisory_xact_lock({_ADVISORY_LOCK_KEY})"))
    ).scalar()
    if not got_lock:
        return False
    populated = (
        await session.execute(
            sa.text(f"SELECT relispopulated FROM pg_class WHERE oid = to_regclass('{_MV_QUALNAME}')")
        )
    ).scalar()
    concurrently = "CONCURRENTLY " if populated else ""
    await session.execute(sa.text(f"REFRESH MATERIALIZED VIEW {concurrently}{_MV_QUALNAME}"))
    await session.commit()
    return True


async def _run_refresh(session_maker: Any, logger: Any) -> None:
    try:
        async with session_maker() as session:
            await refresh_hero_global_stats(session)
    except Exception:
        logger.exception("hero global-stats materialized view refresh failed")


def request_refresh(session_maker: Any, logger: Any) -> None:
    """Debounced, non-blocking refresh request (call on data-change events / startup).

    Throttled to at most one refresh per cooldown window; the timestamp is set
    before scheduling so a burst of events doesn't launch several refreshes. The
    refresh runs as a background task so it never blocks the caller (the event
    consumer). The advisory lock in :func:`refresh_hero_global_stats` is the
    final guard against overlapping refreshes.
    """
    global _last_refresh_monotonic
    now = time.monotonic()
    if _last_refresh_monotonic is not None and (now - _last_refresh_monotonic) < _REFRESH_COOLDOWN_SECONDS:
        return
    _last_refresh_monotonic = now
    task = asyncio.create_task(_run_refresh(session_maker, logger))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
