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
from src.core.workspace import workspace_scope_filter
from src.services.analytics.canonical_division import (
    assign_canonical_division,
    load_source_grids,
)

from ..inference.runner import run_for_tournament
from .calibration import compute_calibration_report
from .orchestrator import (
    SHIFT_ALGORITHM_NAME,
    STANDINGS_ALGORITHM_NAME,
    train_all_models,
)
from .registry import load_active_artifacts
from .splits import tournament_ids_up_to

logger = logging.getLogger(__name__)

__all__ = ("run_rolling_backtest", "persist_backtest_summary")


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


async def _v2_shift_confidence_map(
    session: AsyncSession, tournament_id: int
) -> dict[int, float]:
    """Return ``{player_id: confidence}`` for v2 shift rows of one tournament."""
    algorithm_id = await session.scalar(
        sa.select(models.AnalyticsAlgorithm.id).where(
            models.AnalyticsAlgorithm.name == SHIFT_ALGORITHM_NAME
        )
    )
    if algorithm_id is None:
        return {}
    query = sa.select(
        models.AnalyticsShift.player_id, models.AnalyticsShift.confidence
    ).where(
        models.AnalyticsShift.tournament_id == tournament_id,
        models.AnalyticsShift.algorithm_id == algorithm_id,
    )
    result = await session.execute(query)
    return {int(pid): float(conf or 0.0) for pid, conf in result.all()}


async def _realised_shift_map(
    session: AsyncSession,
    tournament_id: int,
    *,
    history_through_tournament_id: int,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> dict[int, float]:
    """Return ``{player_id: realised_shift}`` for one fold tournament.

    ``realised_shift = current_div - next_tournament_div`` — the same sign
    convention as the shift signal (positive = moved up to a lower division
    number) and the label Shift v2 fits its blend weights against. The division
    is resolved on the canonical OW grid (per the tournament's source grid
    version) to match :func:`shift_features._player_rank_history`, so the label
    scale lines up with what the model was trained to predict.

    ``history_through_tournament_id`` must cover each player's *next* tournament;
    players whose next-division is unknown (e.g. the most recent tournament) are
    dropped because their realised move cannot be observed yet.
    """
    query = (
        sa.select(
            models.Player.id.label("player_id"),
            models.Player.user_id.label("user_id"),
            models.Player.role.label("role"),
            models.Player.tournament_id.label("tournament_id"),
            models.Player.rank.label("rank"),
            models.Tournament.division_grid_version_id.label("version_id"),
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Player.tournament_id <= history_through_tournament_id,
            models.Player.is_substitution.is_(False),
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(models.Player.user_id, models.Player.role, models.Tournament.id)
    )
    result = await session.execute(query)
    df = pd.DataFrame(result.mappings().all())
    if df.empty:
        return {}

    df["tournament_id"] = df["tournament_id"].astype(int)
    df = df.sort_values(["user_id", "role", "tournament_id"]).reset_index(drop=True)

    grids = await load_source_grids(session, df["version_id"].dropna().unique())
    assign_canonical_division(df, grids, rank_col="rank")
    df["next_tournament_div"] = df.groupby(["user_id", "role"], sort=False)["div"].shift(-1)

    fold = df[df["tournament_id"] == int(tournament_id)]
    out: dict[int, float] = {}
    for row in fold.itertuples(index=False):
        if pd.isna(row.next_tournament_div) or pd.isna(row.div):
            continue
        out[int(row.player_id)] = float(row.div) - float(row.next_tournament_div)
    return out


def _shift_scores(
    realised: dict[int, float],
    predicted: dict[int, float],
    *,
    move_threshold: float = 0.5,
) -> dict[str, typing.Any]:
    """Score predicted shifts against the realised division move.

    Returns ``shift_mae`` / ``shift_rmse`` over the common players and
    ``shift_sign_accuracy`` over the players that actually moved
    (``|realised| >= move_threshold``). All ``None`` when there is no overlap /
    nobody moved.
    """
    common = [
        key
        for key in (realised.keys() & predicted.keys())
        if realised[key] is not None and predicted[key] is not None
    ]
    if not common:
        return {"shift_mae": None, "shift_rmse": None, "shift_sign_accuracy": None, "n": 0}

    errors = np.array(
        [float(predicted[key]) - float(realised[key]) for key in common], dtype=float
    )
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors**2)))

    # Sign-accuracy is scored over players who actually moved. A hit needs the
    # prediction to both call a move of its own (|pred| >= move_threshold) *and*
    # match the direction — a near-zero "no move" prediction for a player who
    # moved is a miss, not a lucky sign match on noise.
    moved = [key for key in common if abs(float(realised[key])) >= move_threshold]
    if moved:
        correct = sum(
            1
            for key in moved
            if abs(float(predicted[key])) >= move_threshold
            and np.sign(float(predicted[key])) == np.sign(float(realised[key]))
        )
        sign_accuracy: float | None = float(correct / len(moved))
    else:
        sign_accuracy = None

    return {
        "shift_mae": mae,
        "shift_rmse": rmse,
        "shift_sign_accuracy": sign_accuracy,
        "n": len(common),
    }


def _position_mae(actual: dict[int, int], predicted: dict[int, float]) -> float | None:
    """Mean absolute error between predicted ``mean_position`` and final place."""
    keys = actual.keys() & predicted.keys()
    if not keys:
        return None
    return float(np.mean([abs(float(actual[k]) - float(predicted[k])) for k in keys]))


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


def _spearman_correlation(
    actual: dict[int, int], predicted: dict[int, float]
) -> float | None:
    """Spearman rank correlation over common teams.

    Returns ``None`` (not ``0.0``) when there is too little overlap or zero
    rank variance, so an undefined fold is *excluded* from the aggregate mean
    rather than dragging it toward zero.
    """
    keys = sorted(actual.keys() & predicted.keys())
    if len(keys) < 2:
        return None
    a = np.array([actual[k] for k in keys], dtype=float)
    p = np.array([predicted[k] for k in keys], dtype=float)
    # Rank both arrays manually to avoid an extra dependency.
    a_rank = pd.Series(a).rank().to_numpy()
    p_rank = pd.Series(p).rank().to_numpy()
    if np.std(a_rank) == 0 or np.std(p_rank) == 0:
        return None
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
    calibration_confidences: list[float] = []
    calibration_errors: list[float] = []
    last_tids = all_ids[-window:]
    history_horizon = all_ids[-1]
    for fold_tid in last_tids:
        logger.info("Backtest fold cutoff=%d", fold_tid)
        # Train on everything strictly before the fold.
        await train_all_models(
            session, fold_tid - 1, workspace_id=workspace_id
        )
        await session.commit()
        await run_for_tournament(session, fold_tid, workspace_id=workspace_id)

        v1 = await _v1_shift_map(session, fold_tid)
        v2 = await _v2_shift_map(session, fold_tid)

        # Ground-truth scoring: realised division move (drops the latest fold,
        # whose next-tournament div is not observed yet).
        realised = await _realised_shift_map(
            session,
            fold_tid,
            history_through_tournament_id=history_horizon,
            workspace_id=workspace_id,
        )
        v2_scores = _shift_scores(realised, v2)
        v1_scores = _shift_scores(realised, v1)

        # Accumulate (confidence, |error|) pairs for the calibration report.
        v2_conf = await _v2_shift_confidence_map(session, fold_tid)
        for player_id in realised.keys() & v2.keys() & v2_conf.keys():
            calibration_confidences.append(v2_conf[player_id])
            calibration_errors.append(abs(v2[player_id] - realised[player_id]))

        # Agreement with the v1 heuristic (kept as a reference, not accuracy).
        common = v1.keys() & v2.keys()
        shift_mae_v1_vs_v2 = (
            float(np.mean([abs(v1[k] - v2[k]) for k in common])) if common else None
        )

        actual = await _actual_standings(session, fold_tid)
        predicted = await _predicted_standings(session, fold_tid)
        spearman = _spearman_correlation(actual, predicted) if predicted else None
        position_mae = _position_mae(actual, predicted) if predicted else None
        standings_teams_scored = len(actual.keys() & predicted.keys())

        folds_meta[int(fold_tid)] = {
            # Accuracy against the realised division move (the real label).
            "shift_mae_v2_vs_realised": v2_scores["shift_mae"],
            "shift_sign_accuracy_v2": v2_scores["shift_sign_accuracy"],
            "shift_mae_v1_vs_realised": v1_scores["shift_mae"],
            "shift_sign_accuracy_v1": v1_scores["shift_sign_accuracy"],
            "realised_players": v2_scores["n"],
            # Reference: agreement between the two shift algorithms.
            "shift_mae_v1_vs_v2": shift_mae_v1_vs_v2,
            # Standings accuracy. ``standings_teams_scored`` exposes coverage so
            # a fold that scored only a couple of teams is not mistaken for a
            # full-field result.
            "standings_spearman": spearman,
            "standings_position_mae": position_mae,
            "standings_teams_scored": standings_teams_scored,
            "v1_players": len(v1),
            "v2_players": len(v2),
        }

    def _mean(metric: str) -> float | None:
        values = [
            m[metric] for m in folds_meta.values() if m.get(metric) is not None
        ]
        return float(np.mean(values)) if values else None

    aggregate = {
        "mean_shift_mae_v2_vs_realised": _mean("shift_mae_v2_vs_realised"),
        "mean_shift_sign_accuracy_v2": _mean("shift_sign_accuracy_v2"),
        "mean_shift_mae_v1_vs_realised": _mean("shift_mae_v1_vs_realised"),
        "mean_shift_sign_accuracy_v1": _mean("shift_sign_accuracy_v1"),
        "mean_shift_mae_v1_vs_v2": _mean("shift_mae_v1_vs_v2"),
        "mean_standings_spearman": _mean("standings_spearman"),
        "mean_standings_position_mae": _mean("standings_position_mae"),
    }
    # A prediction within half a division of the realised move counts as a hit.
    calibration = compute_calibration_report(
        calibration_confidences, calibration_errors, accuracy_tolerance=0.5
    )
    return {
        "folds": folds_meta,
        "summary": aggregate,
        "calibration": calibration,
        "n_tournaments": len(all_ids),
    }


async def _latest_tournament_id(session: AsyncSession) -> int:
    tid = await session.scalar(sa.select(sa.func.max(models.Tournament.id)))
    return int(tid or 0)


def _merge_backtest_metrics(
    existing: dict[str, typing.Any] | None, report: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """Return ``existing`` artifact metrics with a ``backtest`` block merged in.

    Reassigns a fresh dict (rather than mutating in place) so SQLAlchemy's
    change tracking picks up the JSON column update.
    """
    metrics = dict(existing or {})
    metrics["backtest"] = {
        "summary": report.get("summary"),
        "calibration": report.get("calibration"),
        "n_tournaments": report.get("n_tournaments"),
    }
    return metrics


async def persist_backtest_summary(
    session: AsyncSession,
    report: dict[str, typing.Any],
    *,
    model_kinds: typing.Sequence[str] = ("shift", "standings"),
) -> int:
    """Attach the walk-forward ``report`` to the active artifacts' ``metrics``.

    This surfaces the honest backtest aggregates (realised-shift MAE,
    sign-accuracy, standings Spearman, ECE) through ``routes/v2.py::list_artifacts``
    so the UI can show them next to the in-sample / val training metrics.
    Returns the number of artifact rows updated.
    """
    updated = 0
    for kind in model_kinds:
        for artifact in await load_active_artifacts(session, model_kind=kind):
            artifact.metrics = _merge_backtest_metrics(artifact.metrics, report)
            session.add(artifact)
            updated += 1
    if updated:
        await session.commit()
    return updated
