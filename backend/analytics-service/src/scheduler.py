"""APScheduler jobs for the analytics worker.

Currently registers one job:

- ``nightly_drift_check`` — runs at 03:30 UTC, builds the latest training
  frame, computes per-feature Wasserstein drift against the recent 3-tournament
  window, and emits a Sentry breadcrumb when any feature exceeds the
  threshold.

Wired into :mod:`serve` via ``register_jobs(broker)``; the FastStream worker
keeps the scheduler alive for its lifetime.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import sentry_sdk
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core import db

from .services.ml.features.aggregations import build_match_features_with_strength
from .services.ml.training.drift import compute_drift_report
from .services.ml.training.splits import tournament_ids_up_to

logger = logging.getLogger(__name__)


async def _nightly_drift_check() -> None:
    """Compute feature drift and alert when over threshold."""
    async with db.async_session_maker() as session:
        latest = await session.scalar(
            __import__("sqlalchemy").select(
                __import__("sqlalchemy").func.max(
                    __import__("src").models.Tournament.id
                )
            )
        )
        if not latest:
            logger.info("No tournaments yet — skipping drift check")
            return
        tids = await tournament_ids_up_to(session, int(latest))
        # Build a feature frame across the last 10 tournaments only (fast path).
        recent_ids = tids[-10:] if len(tids) > 10 else tids
        frames = []
        for tid in recent_ids:
            df = await build_match_features_with_strength(session, tid)
            if not df.empty:
                frames.append(df)
        if not frames:
            return

        import pandas as pd

        combined = pd.concat(frames, ignore_index=True)
        report = compute_drift_report(combined)
        if report["flags"]:
            msg = (
                f"Feature drift detected ({len(report['flags'])} features above "
                f"threshold={report['threshold']}) at {datetime.now(UTC).isoformat()}"
            )
            logger.warning(msg)
            sentry_sdk.capture_message(msg, level="warning", extras=report)
        else:
            logger.info("Drift check passed: %d features measured", len(report["distances"]))


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
