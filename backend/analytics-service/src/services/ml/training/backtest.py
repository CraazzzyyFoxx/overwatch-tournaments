"""Rolling-window backtest harness for v2 models.

The CLI ``analytics.ml.cli backtest --window K`` calls
:meth:`BacktestService.run_rolling_backtest`. For each fold ``t`` in the window the harness:

1. trains every model on the tournaments that started before ``t``
2. infers on tournament ``t`` and recalculates its v1 Points / Linear / OpenSkill shifts
3. scores the v2 shift and its baselines (no move, Points, Linear, OpenSkill) by their agreement with the organizers'
   realised division moves — what the organizers did, not ground truth — and the standings forecast against the
   final places

The run is rolled back and its artifacts go to a throwaway directory: a backtest has no side effects.
Metrics are aggregated across folds and returned as a dict suitable for JSON.
"""

from __future__ import annotations

import logging
import math
import tempfile
import typing

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from shared import models
from shared.repository import MLModelArtifactRepository
from shared.services.workspace_scope import workspace_filter, workspace_scope_filter
from src.core.analytics_exports import analytics_exports, tournament_discipline
from src.domain.ratings import LINEAR, OPENSKILL, POINTS
from src.services.analytics.canonical_division import load_source_grids
from src.services.analytics.flows import flows_service

from ..inference.runner import run_for_tournament
from ..models.base import models_dir_override
from .calibration import compute_calibration_report
from .orchestrator import train_all_models
from .registry import registry_service
from .splits import tournament_ids_up_to

logger = logging.getLogger(__name__)

__all__ = ("BacktestService", "backtest_service")


async def _shift_map(session: AsyncSession, tournament_id: int, algorithm_name: str) -> dict[int, float]:
    """Return ``{player_id: shift}`` from one algorithm's ``AnalyticsShift`` rows of a tournament."""
    algorithm_id = await session.scalar(
        sa.select(models.AnalyticsAlgorithm.id).where(models.AnalyticsAlgorithm.name == algorithm_name)
    )
    if algorithm_id is None:
        return {}
    query = sa.select(models.AnalyticsShift.player_id, models.AnalyticsShift.shift).where(
        models.AnalyticsShift.tournament_id == tournament_id,
        models.AnalyticsShift.algorithm_id == algorithm_id,
    )
    result = await session.execute(query)
    return {int(pid): float(shift) for pid, shift in result.all()}


async def _v2_shift_hit_probability_map(
    session: AsyncSession, tournament_id: int, algorithm_name: str
) -> dict[int, float]:
    """Return ``{player_id: p_hit}`` for v2 shift rows of one tournament.

    ``p_hit = 2Φ(0.5 / shift_sd) − 1``: the probability, under the row's own ``N(shift, shift_sd²)``, that the move
    lands within half a division of the prediction. Rows without ``shift_sd`` (legacy) are skipped.
    """
    algorithm_id = await session.scalar(
        sa.select(models.AnalyticsAlgorithm.id).where(models.AnalyticsAlgorithm.name == algorithm_name)
    )
    if algorithm_id is None:
        return {}
    query = sa.select(models.AnalyticsShift.player_id, models.AnalyticsShift.shift_sd).where(
        models.AnalyticsShift.tournament_id == tournament_id,
        models.AnalyticsShift.algorithm_id == algorithm_id,
        models.AnalyticsShift.shift_sd.is_not(None),
    )
    result = await session.execute(query)
    # 2Φ(x) − 1 = erf(x / √2); a zero sd is a certain hit.
    return {int(pid): (math.erf(0.5 / (float(sd) * math.sqrt(2.0))) if sd > 0 else 1.0) for pid, sd in result.all()}


async def _realised_shift_map(
    session: AsyncSession,
    tournament_id: int,
    *,
    discipline: str,
    history_through_tournament_id: int,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> dict[int, float]:
    """Return ``{player_id: realised_shift}`` for one fold tournament.

    ``realised_shift = current_div - next_tournament_div`` — the same sign
    convention as the shift signal (positive = moved up to a lower division
    number) and the label Shift v2 fits its blend weights against. The division
    is resolved on the canonical grid of ``discipline``'s module (per the tournament's source grid
    version) to match the module's ``load_player_rank_history``, so the label
    scale lines up with what the model was trained to predict.

    Each player's chronology is tournament start order ``(coalesce(start_date, created_at), id)``: ids are not
    chronological. ``history_through_tournament_id`` must cover each player's *next* tournament;
    players whose next-division is unknown (e.g. the most recent tournament) are
    dropped because their realised move cannot be observed yet.
    """
    chrono = sa.func.coalesce(models.Tournament.start_date, models.Tournament.created_at)
    horizon = (
        sa.select(chrono.label("started_at"), models.Tournament.id.label("tournament_id"))
        .where(models.Tournament.id == history_through_tournament_id)
        .subquery("horizon")
    )
    query = (
        sa.select(
            models.Player.id.label("player_id"),
            models.WorkspaceMember.player_id.label("user_id"),
            models.Player.role.label("role"),
            models.Player.tournament_id.label("tournament_id"),
            chrono.label("started_at"),
            models.Player.rank.label("rank"),
            models.Tournament.division_grid_version_id.label("version_id"),
        )
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .join(
            horizon,
            sa.tuple_(chrono, models.Tournament.id) <= sa.tuple_(horizon.c.started_at, horizon.c.tournament_id),
        )
        .where(
            models.Player.is_substitution.is_(False),
            # Unranked rows have no division: the realised move is between consecutive ranked tournaments.
            models.Player.rank.is_not(None),
            models.Tournament.discipline == discipline,
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
    )
    result = await session.execute(query)
    df = pd.DataFrame(result.mappings().all())
    if df.empty:
        return {}

    df["tournament_id"] = df["tournament_id"].astype(int)
    df = df.sort_values(["user_id", "role", "started_at", "tournament_id"]).reset_index(drop=True)

    grids = await load_source_grids(session, df["version_id"].dropna().unique())
    analytics_exports(discipline).assign_canonical_division(df, grids, rank_col="rank")
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
        key for key in (realised.keys() & predicted.keys()) if realised[key] is not None and predicted[key] is not None
    ]
    if not common:
        return {"shift_mae": None, "shift_rmse": None, "shift_sign_accuracy": None, "n": 0}

    errors = np.array([float(predicted[key]) - float(realised[key]) for key in common], dtype=float)
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


async def _actual_standings(session: AsyncSession, tournament_id: int) -> dict[int, int]:
    query = sa.select(models.Standing.team_id, models.Standing.overall_position).where(
        models.Standing.tournament_id == tournament_id
    )
    result = await session.execute(query)
    return {int(tid): int(pos) for tid, pos in result.all() if pos is not None}


async def _predicted_standings(session: AsyncSession, tournament_id: int, algorithm_name: str) -> dict[int, float]:
    algorithm_id = await session.scalar(
        sa.select(models.AnalyticsAlgorithm.id).where(models.AnalyticsAlgorithm.name == algorithm_name)
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


def _spearman_correlation(actual: dict[int, int], predicted: dict[int, float]) -> float | None:
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


async def _latest_tournament_id(session: AsyncSession, *, discipline: str, workspace_id: int | None) -> int:
    # Latest by start date (``coalesce(start_date, created_at)``, id tie-break), the chronology of
    # ``tournament_ids_up_to``: ids are not chronological. Same exclusion too: the per-workspace scrim container is
    # hidden and carries no ranked roster data, so it must not end a timeline the backtest scores nothing against.
    chrono = sa.func.coalesce(models.Tournament.start_date, models.Tournament.created_at)
    tid = await session.scalar(
        sa.select(models.Tournament.id)
        .where(
            models.Tournament.is_hidden.is_(False),
            models.Tournament.discipline == discipline,
            *workspace_filter(workspace_id),
        )
        .order_by(chrono.desc(), models.Tournament.id.desc())
        .limit(1)
    )
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
        "calibration_vs_organizer_moves": report.get("calibration_vs_organizer_moves"),
        "n_tournaments": report.get("n_tournaments"),
    }
    return metrics


class BacktestService:
    def __init__(self, *, artifacts: MLModelArtifactRepository = MLModelArtifactRepository()) -> None:
        self.artifacts = artifacts

    async def run_rolling_backtest(
        self,
        connection: AsyncConnection,
        *,
        window: int,
        cutoff_tournament_id: int | None = None,
        workspace_id: int | None = None,
        discipline: str | None = None,
    ) -> dict[str, typing.Any]:
        """Train + infer + score for the latest ``window`` tournaments of one discipline, without side effects.

        Every fold trains, activates and infers for real inside a savepoint of ``connection`` that is rolled back at
        the end (the session's own commits only release nested savepoints), and writes its artifacts to a temporary
        directory removed afterwards: the registry, active artifacts, model files and analytics rows stay as they were.

        ``cutoff_tournament_id`` owns the run: its discipline is the one scored and an ``explicit`` ``discipline``
        naming another game is rejected. Without a cutoff the discipline must be named and its latest tournament by
        start date is the cutoff. Returns ``{fold_tournament_id: {metric: value}}`` plus an aggregate summary with mean
        MAE / sign accuracy per shift predictor and Spearman across folds.
        """
        # ponytail: the one transaction keeps the fold writes' row locks for the whole run, so production writers of
        # those rows wait for it. Fine for an offline CLI; point it at a replica if that ever bites.
        with (
            tempfile.TemporaryDirectory(prefix="backtest-artifacts-") as artifacts_dir,
            models_dir_override(artifacts_dir),
        ):
            savepoint = await connection.begin_nested()
            try:
                async with AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
                ) as session:
                    return await self._score_folds(
                        session,
                        window=window,
                        cutoff_tournament_id=cutoff_tournament_id,
                        workspace_id=workspace_id,
                        discipline=discipline,
                    )
            finally:
                await savepoint.rollback()

    async def _score_folds(
        self,
        session: AsyncSession,
        *,
        window: int,
        cutoff_tournament_id: int | None,
        workspace_id: int | None,
        discipline: str | None,
    ) -> dict[str, typing.Any]:
        if cutoff_tournament_id is not None:
            owner = await tournament_discipline(session, cutoff_tournament_id, explicit=discipline)
            if owner is None:
                raise LookupError(f"cutoff tournament {cutoff_tournament_id} not found")
            discipline = owner
        elif discipline is None:
            raise ValueError("a backtest without a cutoff tournament must name its discipline")
        exports = analytics_exports(discipline)
        shift_algorithm = exports.MODELS["shift"].algorithm_name
        standings_algorithm = exports.MODELS["standings"].algorithm_name
        if cutoff_tournament_id is None:
            cutoff_tournament_id = await _latest_tournament_id(
                session, discipline=discipline, workspace_id=workspace_id
            )
        all_ids = await tournament_ids_up_to(
            session,
            cutoff_tournament_id,
            discipline=discipline,
            workspace_id=workspace_id,
        )
        if len(all_ids) < window + 1:
            logger.warning("Not enough tournaments for backtest window=%d", window)
            return {"folds": {}, "summary": {}, "n_tournaments": len(all_ids), "discipline": discipline}

        folds_meta: dict[int, dict[str, typing.Any]] = {}
        calibration_confidences: list[float] = []
        calibration_errors: list[float] = []
        history_horizon = all_ids[-1]
        for position in range(len(all_ids) - window, len(all_ids)):
            fold_tid = all_ids[position]
            logger.info("Backtest fold cutoff=%d", fold_tid)
            # Train on everything strictly before the fold: the previous tournament by start date, never ``id - 1``.
            await train_all_models(session, all_ids[position - 1], workspace_id=workspace_id)
            await session.commit()
            await run_for_tournament(session, fold_tid, workspace_id=workspace_id)
            # The Points, Linear and OpenSkill baselines are the fold's own v1 recalculation.
            await flows_service.recalculate_analytics(session, fold_tid, workspace_id=workspace_id)

            # Scored against the organizers' realised division moves: what they did next, not ground truth. Drops the
            # latest fold, whose next-tournament division is not observed yet.
            realised = await _realised_shift_map(
                session,
                fold_tid,
                history_through_tournament_id=history_horizon,
                workspace_id=workspace_id,
                discipline=discipline,
            )
            v2 = await _shift_map(session, fold_tid, shift_algorithm)
            predictions = {
                "shift_v2": v2,
                "zero": dict.fromkeys(realised, 0.0),
                "points": await _shift_map(session, fold_tid, POINTS),
                "linear": await _shift_map(session, fold_tid, LINEAR),
                "openskill": await _shift_map(session, fold_tid, OPENSKILL),
            }

            # Accumulate (predicted hit probability, |error|) pairs for the calibration report.
            v2_hit = await _v2_shift_hit_probability_map(session, fold_tid, shift_algorithm)
            for player_id in realised.keys() & v2.keys() & v2_hit.keys():
                calibration_confidences.append(v2_hit[player_id])
                calibration_errors.append(abs(v2[player_id] - realised[player_id]))

            actual = await _actual_standings(session, fold_tid)
            predicted = await _predicted_standings(session, fold_tid, standings_algorithm)
            spearman = _spearman_correlation(actual, predicted) if predicted else None
            position_mae = _position_mae(actual, predicted) if predicted else None
            standings_teams_scored = len(actual.keys() & predicted.keys())

            folds_meta[int(fold_tid)] = {
                "organizer_moves": len(realised),
                "agreement_with_organizer_moves": {
                    name: _shift_scores(realised, shifts) for name, shifts in predictions.items()
                },
                # Standings accuracy. ``standings_teams_scored`` exposes coverage so
                # a fold that scored only a couple of teams is not mistaken for a
                # full-field result.
                "standings_spearman": spearman,
                "standings_position_mae": position_mae,
                "standings_teams_scored": standings_teams_scored,
            }

        def _mean(values: typing.Iterable[float | None]) -> float | None:
            present = [value for value in values if value is not None]
            return float(np.mean(present)) if present else None

        folds = list(folds_meta.values())
        agreement = [fold["agreement_with_organizer_moves"] for fold in folds]
        aggregate = {
            "agreement_with_organizer_moves": {
                name: {
                    "mean_shift_mae": _mean(scores[name]["shift_mae"] for scores in agreement),
                    "mean_shift_sign_accuracy": _mean(scores[name]["shift_sign_accuracy"] for scores in agreement),
                }
                for name in (agreement[0] if agreement else ())
            },
            "mean_standings_spearman": _mean(fold["standings_spearman"] for fold in folds),
            "mean_standings_position_mae": _mean(fold["standings_position_mae"] for fold in folds),
        }
        # A prediction within half a division of the organizers' move counts as a hit.
        calibration = compute_calibration_report(calibration_confidences, calibration_errors, accuracy_tolerance=0.5)
        return {
            "folds": folds_meta,
            "summary": aggregate,
            "calibration_vs_organizer_moves": calibration,
            "n_tournaments": len(all_ids),
            "discipline": discipline,
        }

    async def persist_backtest_summary(
        self,
        session: AsyncSession,
        report: dict[str, typing.Any],
        *,
        discipline: str,
        model_kinds: typing.Sequence[str] = ("shift", "standings"),
    ) -> int:
        """Attach the walk-forward ``report`` to the active artifacts' ``metrics``.

        This surfaces the backtest aggregates (agreement with organizer moves per
        shift predictor, standings Spearman, ECE) through ``rpc.analytics.artifacts`` so the UI can
        show them next to the in-sample / val training metrics.
        Returns the number of artifact rows updated.
        """
        exports = analytics_exports(discipline)
        updated = 0
        for kind in model_kinds:
            algorithm_id = await session.scalar(
                sa.select(models.AnalyticsAlgorithm.id).where(
                    models.AnalyticsAlgorithm.name == exports.MODELS[kind].algorithm_name
                )
            )
            if algorithm_id is None:
                continue
            for artifact in await registry_service.load_active_artifacts(
                session, discipline=discipline, algorithm_id=algorithm_id, model_kind=kind
            ):
                await self.artifacts.update_fields(
                    session,
                    artifact,
                    {"metrics": _merge_backtest_metrics(artifact.metrics, report)},
                )
                updated += 1
        if updated:
            await session.commit()
        return updated


backtest_service = BacktestService()
