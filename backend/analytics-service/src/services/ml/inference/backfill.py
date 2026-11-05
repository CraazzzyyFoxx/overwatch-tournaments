"""Historical backfill — runs the inference runner over the tournaments started in a date range."""

from __future__ import annotations

import logging
import typing
from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.chrono import tournament_chrono_key
from shared.services.workspace_scope import workspace_filter
from src.core.analytics_exports import supports_analytics

from .runner import run_for_tournament

logger = logging.getLogger(__name__)

__all__ = ("backfill_range",)


async def backfill_range(
    session: AsyncSession,
    *,
    from_date: date,
    to_date: date,
    workspace_id: int | None = None,
    model_kinds: typing.Sequence[str] | None = None,
    discipline: str | None = None,
) -> dict[int, dict[str, int]]:
    """Run the inference pipeline for every analytics-supported tournament whose start falls in the range.

    The start is ``coalesce(start_date, created_at)`` and the range is whole UTC days ``[from_date, to_date]``;
    tournaments are visited in tournament chronology. Only tournaments that are not hidden containers, lie in
    ``workspace_id`` when given, belong to ``discipline`` when given and whose discipline declares an analytics
    module are visited; each one is served by its own discipline's module. Returns ``{tournament_id: {kind: rows}}``.
    Each tournament is committed independently — interrupting the run leaves the DB in a consistent state.
    """
    if from_date > to_date:
        return {}
    start, _, _ = tournament_chrono_key()
    tournaments = await session.execute(
        sa.select(models.Tournament.id, models.Tournament.discipline)
        .where(
            start >= datetime.combine(from_date, time.min, tzinfo=UTC),
            start < datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC),
            models.Tournament.is_hidden.is_(False),
            *workspace_filter(workspace_id),
        )
        .order_by(*tournament_chrono_key())
    )
    results: dict[int, dict[str, int]] = {}
    for tid, code in tournaments.all():
        if (discipline is not None and code != discipline) or not supports_analytics(code):
            continue
        logger.info("Backfilling tournament_id=%d", tid)
        results[int(tid)] = await run_for_tournament(
            session,
            int(tid),
            workspace_id=workspace_id,
            model_kinds=model_kinds,
        )
    return results
