"""Historical backfill — runs the inference runner over a tournament range."""

from __future__ import annotations

import logging
import typing

from sqlalchemy.ext.asyncio import AsyncSession

from .runner import run_for_tournament

logger = logging.getLogger(__name__)

__all__ = ("backfill_range",)


async def backfill_range(
    session: AsyncSession,
    *,
    from_tournament_id: int,
    to_tournament_id: int,
    workspace_id: int | None = None,
    model_kinds: typing.Sequence[str] | None = None,
) -> dict[int, dict[str, int]]:
    """Run the inference pipeline for every tournament in ``[from, to]``.

    Returns ``{tournament_id: {kind: rows}}``. Each tournament is committed
    independently — interrupting the run leaves the DB in a consistent state.
    """
    if from_tournament_id > to_tournament_id:
        return {}
    results: dict[int, dict[str, int]] = {}
    for tid in range(int(from_tournament_id), int(to_tournament_id) + 1):
        logger.info("Backfilling tournament_id=%d", tid)
        results[tid] = await run_for_tournament(
            session,
            tid,
            workspace_id=workspace_id,
            model_kinds=model_kinds,
        )
    return results
