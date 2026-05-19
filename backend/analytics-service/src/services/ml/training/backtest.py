"""Rolling-window backtest harness for v2 models.

The CLI ``analytics.ml.cli backtest --window K`` calls
:func:`run_rolling_backtest`. For each fold ``t`` in the window the harness:

1. trains every model on tournaments ``[1..t-1]``
2. infers on tournament ``t``
3. computes metrics by comparing the inferred values to v1 / actual results

Metrics are aggregated across folds and returned as a dict suitable for JSON.
"""

from __future__ import annotations

import logging
import typing

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..inference.runner import run_for_tournament
from .orchestrator import (
    PERFORMANCE_ALGORITHM_NAME,
    SHIFT_ALGORITHM_NAME,
    STANDINGS_ALGORITHM_NAME,
    train_all_models,
)
from .splits import tournament_ids_up_to

logger = logging.getLogger(__name__)

__all__ = ("run_rolling_backtest",)


async def _v1_shift_map(
    session: AsyncSession, tournament_id: int
) -> dict[int, float]:
    """Return ``{player_id: shift}`` from the v1 ``AnalyticsPlayer`` table."""
    query = sa.select(
        models.AnalyticsPlayer.player_id, models.AnalyticsPlayer.shift
    ).where(models.AnalyticsPlayer.tournament_id == tournament_id)
    result = await session.execute(query)
    return {int(pid): float(shift or 0) for pid, shift in result.all()}


async def _v2_shift_map(
    session: AsyncSession, tournament_id: int
) -> dict[int, float]:
    algorithm_id = await session.scalar(
        sa.select(models.AnalyticsAlgorithm.id).where(
            models.AnalyticsAlgorithm.name == SHIFT_ALGORITHM_NAME
        )
    )
    if algorithm_id is None:
        return {}
    query = sa.select(
        models.AnalyticsShift.player_id, models.AnalyticsShift.shift
    ).where(
        models.AnalyticsShift.tournament_id == tournament_id,
        models.AnalyticsShift.algorithm_id == algorithm_id,
    )
    result = await session.execute(query)
    return {int(pid): float(shift) for pid, shift in result.all()}


async def _actual_standings(
    session: AsyncSession, tournament_id: int
) -> dict[int, int]:
    query = sa.select(
        models.Standing.team_id, models.Standing.overall_position
    ).where(models.Standing.tournament_id == tournament_id)
    result = await session.execute(query)
    return {int(tid): int(pos) for tid, pos in result.all() if pos is not None}


async def _predicted_standings(
    session: AsyncSession, tournament_id: int
) -> dict[int, float]:
    algorithm_id = await session.scalar(
        sa.select(models.AnalyticsAlgorithm.id).where(
            models.AnalyticsAlgorithm.name == STANDINGS_ALGORITHM_NAME
        )
    )
    if algorithm_id is None:
        return {}
    query = sa.select(
        models.AnalyticsStandingsDistribution.team_id,
        models.AnalyticsStandingsDistribution.mean_position,
    ).where(
        models.AnalyticsStandingsDistribution.tournament_id == tournament_id,
        models.AnalyticsStandingsDistribution.algorithm_id == algorithm_id,
    )
    result = await session.execute(query)
    return {int(tid): float(pos) for tid, pos in result.all()}


def _spearman_correlation(actual: dict[int, int], predicted: dict[int, float]) -> float:
    keys = sorted(actual.keys() & predicted.keys())
    if len(keys) < 2:
        return 0.0
    a = np.array([actual[k] for k in keys], dtype=float)
    p = np.array([predicted[k] for k in keys], dtype=float)
    # Rank both arrays manually to avoid an extra dependency.
    a_rank = pd.Series(a).rank().to_numpy()
    p_rank = pd.Series(p).rank().to_numpy()
    if np.std(a_rank) == 0 or np.std(p_rank) == 0:
        return 0.0
    return float(np.corrcoef(a_rank, p_rank)[0, 1])


async def run_rolling_backtest(
    session: AsyncSession,
    *,
    window: int,
    cutoff_tournament_id: int | None = None,
    workspace_id: int | None = None,
) -> dict[str, typing.Any]:
    """Train + infer + score for the latest ``window`` tournaments.

    Returns ``{fold_tournament_id: {metric: value}}`` plus an aggregate
    summary with mean MAE / Spearman / Brier across folds.
    """
    all_ids = await tournament_ids_up_to(
        session,
        cutoff_tournament_id
        if cutoff_tournament_id is not None
        else (await _latest_tournament_id(session)),
        workspace_id=workspace_id,
    )
    if len(all_ids) < window + 1:
        logger.warning("Not enough tournaments for backtest window=%d", window)
        return {"folds": {}, "summary": {}, "n_tournaments": len(all_ids)}

    folds_meta: dict[int, dict[str, typing.Any]] = {}
    last_tids = all_ids[-window:]
    for fold_tid in last_tids:
        logger.info("Backtest fold cutoff=%d", fold_tid)
        # Train on everything strictly before the fold.
        await train_all_models(
            session, fold_tid - 1, workspace_id=workspace_id
        )
        await session.commit()
        await run_for_tournament(session, fold_tid, workspace_id=workspace_id)

        # Compare v2 shift vs v1 shift (v1 is taken as the historical baseline).
        v1 = await _v1_shift_map(session, fold_tid)
        v2 = await _v2_shift_map(session, fold_tid)
        common = v1.keys() & v2.keys()
        shift_mae = (
            float(np.mean([abs(v1[k] - v2[k]) for k in common])) if common else None
        )

        actual = await _actual_standings(session, fold_tid)
        predicted = await _predicted_standings(session, fold_tid)
        spearman = _spearman_correlation(actual, predicted) if predicted else None

        folds_meta[int(fold_tid)] = {
            "shift_mae_v1_vs_v2": shift_mae,
            "standings_spearman": spearman,
            "v1_players": len(v1),
            "v2_players": len(v2),
        }

    aggregate = {
        "mean_shift_mae_v1_vs_v2": float(
            np.nanmean(
                [m["shift_mae_v1_vs_v2"] for m in folds_meta.values() if m["shift_mae_v1_vs_v2"] is not None]
            )
        )
        if any(m["shift_mae_v1_vs_v2"] is not None for m in folds_meta.values())
        else None,
        "mean_standings_spearman": float(
            np.nanmean(
                [m["standings_spearman"] for m in folds_meta.values() if m["standings_spearman"] is not None]
            )
        )
        if any(m["standings_spearman"] is not None for m in folds_meta.values())
        else None,
    }
    return {"folds": folds_meta, "summary": aggregate, "n_tournaments": len(all_ids)}


async def _latest_tournament_id(session: AsyncSession) -> int:
    tid = await session.scalar(sa.select(sa.func.max(models.Tournament.id)))
    return int(tid or 0)
