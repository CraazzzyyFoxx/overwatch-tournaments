"""APScheduler jobs for the analytics worker.

Registers one job:

- ``nightly_drift_check`` — runs at 03:30 UTC, builds each analytics-enabled discipline's latest training
  frame, computes per-feature Wasserstein drift against the recent 3-tournament
  window, and emits a Sentry breadcrumb when any feature exceeds the
  threshold.

Wired into :mod:`serve` via ``register_jobs(broker)``; the FastStream worker
keeps the scheduler alive for its lifetime.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pandas as pd
import sentry_sdk
import sqlalchemy as sa
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.disciplines import DISCIPLINES
from shared.observability import observe_scheduled_job
from src.core import db

from .services.ml.features.aggregations import build_match_features_with_strength
from .services.ml.training.drift import compute_drift_report
from .services.ml.training.splits import tournament_ids_up_to

logger = logging.getLogger(__name__)


async def _drift_check(session: AsyncSession, code: str) -> None:
    """Feature drift of one discipline's recent tournaments; alert when over threshold."""
    # The chronologically latest tournament, not ``max(id)``: ids are not chronological.
    latest = await session.scalar(
        sa.select(models.Tournament.id)
        .where(models.Tournament.discipline == code, models.Tournament.is_hidden.is_(False))
        .order_by(
            sa.func.coalesce(models.Tournament.start_date, models.Tournament.created_at).desc(),
            models.Tournament.id.desc(),
        )
        .limit(1)
    )
    if not latest:
        logger.info("No %s tournaments yet — skipping drift check", code)
        return
    tids = await tournament_ids_up_to(session, int(latest), discipline=code)
    # Build a feature frame across the last 10 tournaments only (fast path).
    recent_ids = tids[-10:] if len(tids) > 10 else tids
    frames = []
    for tid in recent_ids:
        df = await build_match_features_with_strength(session, tid, discipline=code)
        if not df.empty:
            frames.append(df)
    if not frames:
        return

    report = compute_drift_report(pd.concat(frames, ignore_index=True), recent_ids)
    if report["flags"]:
        msg = (
            f"Feature drift detected for {code} ({len(report['flags'])} features above "
            f"threshold={report['threshold']}) at {datetime.now(UTC).isoformat()}"
        )
        logger.warning(msg)
        sentry_sdk.add_breadcrumb(category="ml", message=msg, level="warning", data=report)
    else:
        logger.info("Drift check passed for %s: %d features measured", code, len(report["distances"]))


async def _nightly_drift_check() -> None:
    """Drift-check every discipline that declares an analytics module; others have no features to drift."""
    async with observe_scheduled_job("nightly_drift_check"), db.async_session_maker() as session:
        for code, spec in DISCIPLINES.items():
            if spec.analytics is not None:
                await _drift_check(session, code)


def register_jobs() -> AsyncIOScheduler:
    """Create and start an :class:`AsyncIOScheduler` with the analytics jobs."""
    scheduler = AsyncIOScheduler(timezone=UTC)
    scheduler.add_job(
        _nightly_drift_check,
        CronTrigger(hour=3, minute=30),
        id="nightly_drift_check",
        replace_existing=True,
    )
    return scheduler
