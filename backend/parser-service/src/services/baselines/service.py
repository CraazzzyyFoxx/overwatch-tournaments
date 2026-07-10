"""Cached read of the active :class:`impact.BaselineSet` (spec 2026-07-10).

Baselines are versioned by ``FORMULA_VERSION`` and replaced atomically by
:func:`src.services.baselines.flows.recompute`. Reads are cashews-cached (10m
TTL) behind a single literal key so `get_active` avoids re-scanning
``matches.stat_baselines`` on every scoring call.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.impact import FORMULA_VERSION
from src import models
from src.services.match_logs import impact

__all__ = ("get_active", "invalidate_cache")

logger = logging.getLogger(__name__)

# Full literal key (NOT a cashews key template — FORMULA_VERSION is a module
# constant, not a subscriber argument cashews could substitute). Must start
# with a prefix this process actually registers via ``configure_cache()``
# (parser-service only registers ``backend:``, see src/core/caching.py) or
# every get/set/delete raises NotConfiguredError (see
# lesson_cashews_prefixless_delete_match).
_CACHE_KEY = f"backend:parser:impact_baselines:{FORMULA_VERSION}"
_CACHE_TTL = "10m"


async def get_active(session: AsyncSession) -> impact.BaselineSet | None:
    """Return the active :class:`impact.BaselineSet`, cashews-cached for 10m."""
    if cache.is_setup():
        try:
            cached = await cache.get(_CACHE_KEY)
        except Exception:  # pragma: no cover - cache is best-effort
            logger.debug("impact baselines cache get failed", exc_info=True)
            cached = None
        if cached is not None:
            return cached

    rows = (
        (
            await session.execute(
                sa.select(models.StatBaseline).where(models.StatBaseline.formula_version == FORMULA_VERSION)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None

    bounds = tuple(rows[0].meta["bucket_bounds"]) if rows[0].meta else ()
    values = {(row.role.value.lower(), row.rank_bucket, row.stat.name): (row.mean, row.std) for row in rows}
    baseline_set = impact.BaselineSet(FORMULA_VERSION, bounds, values)

    if cache.is_setup():
        try:
            await cache.set(_CACHE_KEY, baseline_set, expire=_CACHE_TTL)
        except Exception:  # pragma: no cover - cache is best-effort
            logger.debug("impact baselines cache set failed", exc_info=True)

    return baseline_set


async def invalidate_cache() -> None:
    """Drop the cached active baseline set (call after :func:`recompute` commits)."""
    if not cache.is_setup():
        return
    try:
        await cache.delete(_CACHE_KEY)
    except Exception:  # pragma: no cover - cache is best-effort
        logger.debug("impact baselines cache invalidate failed", exc_info=True)
