"""Out-of-band refresh of the ``matches.mv_hero_global_stats`` materialized view.

The global per-(hero, stat) comparison on ``GET /users/{id}/heroes`` is
precomputed into a materialized view (see migration ``herostatmv01``). The heavy
aggregation that used to run inside the web request (and blew past
``statement_timeout`` on a cache miss) now happens here, off the request path.

Trigger model — debounced, event-driven:
  * app-worker startup fires a best-effort initial populate;
  * every ``tournament.standings`` invalidation requests a refresh, throttled to at most
    one per cooldown window so a burst of events coalesces into a single refresh.

The refresh is scheduled as a background task (never blocks the event consumer),
runs with ``statement_timeout`` disabled and ``work_mem`` raised for its
transaction, and is guarded by a Postgres advisory lock so two refreshers never
collide. The debounce window lives in Redis (via cashews) so it holds across
scaled-out replicas, not just inside one process.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import sqlalchemy as sa
from cashews import cache

__all__ = ("HeroStatsRefresher", "hero_stats_refresh_service")

_MV_QUALNAME = "matches.mv_hero_global_stats"
# Arbitrary constant advisory-lock key, unique to this refresh.
_ADVISORY_LOCK_KEY = 0x6865726F5F6756
# Debounce window: collapse a burst of change events into a single refresh.
# Global per-hero stats do not need minute-level freshness.
_REFRESH_COOLDOWN_SECONDS = 3600
# Cooldown marker. The ``backend:`` prefix routes to Redis (see ``core.caching``),
# so the window is shared by every app-svc replica (``make prod-scale``) — a
# module-level timestamp would debounce inside one process only.
_COOLDOWN_KEY = "backend:hero_global_stats:refresh_cooldown"

# Keep references to in-flight refresh tasks so they aren't garbage-collected.
# Process-wide on purpose: the anchor must outlive any single refresher instance.
_background_tasks: set[asyncio.Task[Any]] = set()


class HeroStatsRefresher:
    async def refresh(self, session: Any) -> bool:
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
        # Two plan nodes over the ~4.3M-row ``eligible`` CTE spilled at the server-wide
        # 64 MB ``work_mem``: its sort (245 MB temp file) and its materialization
        # (216 MB). ``work_mem`` caps each node separately and measured in-memory need
        # is well above the on-disk size — EXPLAIN ANALYZE on prod: 403 MB quicksort +
        # 321 MB tuplestore. 768 MB keeps both resident with room to grow; only one
        # such transaction runs at a time (advisory lock below), so it cannot multiply
        # across sessions the way a global bump would.
        await session.execute(sa.text("SET LOCAL work_mem = '768MB'"))
        # The view's ``eligible`` CTE joins ``matches.statistics`` against its own
        # (match, user, hero) qualification, and the planner answers it with a
        # nested loop: 188,995 inner index scans on
        # ``ix_match_statistics_match_user_round``, each fetching ``name``/``value``
        # from the heap and discarding ~116 rows per 24 kept. That is 2.5M buffer
        # touches for a 4.5M-row result — enough to evict the entire working set of
        # a 2 GB ``shared_buffers`` once an hour, every hour. Forbidding the nested
        # loop for this transaction turns it into a hash join over two scans:
        # measured on a production restore (27.3M rows) 5055 ms -> 2538 ms and
        # 2.53M -> 695k buffers. The small joins downstream (``best`` hydrates one
        # metadata row per (hero, stat)) are unaffected at those cardinalities, and
        # a covering index on the inner side — the only way to keep the nested loop
        # and lose the heap fetches — would cost 336 MB of write-amplified index for
        # one hourly job.
        await session.execute(sa.text("SET LOCAL enable_nestloop = off"))
        got_lock = (await session.execute(sa.text(f"SELECT pg_try_advisory_xact_lock({_ADVISORY_LOCK_KEY})"))).scalar()
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

    async def _run_refresh(self, session_maker: Any, logger: Any) -> None:
        try:
            # Cross-replica debounce: atomic SET NX EX, first claimant in the window wins.
            if not await cache.set(_COOLDOWN_KEY, 1, expire=_REFRESH_COOLDOWN_SECONDS, exist=False):
                return
            async with session_maker() as session:
                await self.refresh(session)
        except Exception:
            logger.exception("hero global-stats materialized view refresh failed")
            # Release the window so a transient failure retries on the next event
            # instead of leaving the view stale for a full cooldown.
            with suppress(Exception):
                await cache.delete(_COOLDOWN_KEY)

    def request_refresh(self, session_maker: Any, logger: Any) -> None:
        """Debounced, non-blocking refresh request (call on data-change events / startup).

        Runs as a background task so it never blocks the caller (the event consumer).
        The task claims the cooldown window in Redis first, so a burst of events —
        across every replica — coalesces into a single refresh; the advisory lock in
        :meth:`refresh` is the final guard against overlap.
        """
        task = asyncio.create_task(self._run_refresh(session_maker, logger))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


hero_stats_refresh_service = HeroStatsRefresher()
