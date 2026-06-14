"""Inference runner — populates v2 ``analytics.*`` tables for one tournament.

Currently implements Performance v2 only (Phase 1). Shift v2, Standings v2 and
Match Quality writers are added in subsequent phases; each follows the same
pattern: load active artifact → build feature frame → predict → upsert.
"""

from __future__ import annotations

import logging
import typing

import pandas as pd
import sqlalchemy as sa
from shared.services.division_grid_resolution import resolve_tournament_division
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core.config import settings
from src.core.workspace import get_division_grid

from ..features.aggregations import build_match_features_with_strength
from ..features.local_performance import attach_local_performance
from ..features.shift_features import build_shift_feature_frame
from ..features.standings_features import build_standings_training_frame
from ..models.base import load_artifact
from ..models.performance_v2 import (
    PerformanceModelV2,
    aggregate_to_tournament,
    impact_score_within_role,
    stabilize_small_cohort_impact,
)
from ..models.shift_v2 import ShiftModelV2
from ..models.standings_v2 import WinProbabilityModel, simulate_standings
from ..training.orchestrator import (
    PERFORMANCE_ALGORITHM_NAME,
    PERFORMANCE_MODEL_KIND,
    SHIFT_ALGORITHM_NAME,
    SHIFT_MODEL_KIND,
    STANDINGS_ALGORITHM_NAME,
    STANDINGS_MODEL_KIND,
)
from ..training.registry import load_active_artifact, load_active_artifacts
from .player_anomaly_runner import run_player_anomalies_for_tournament

logger = logging.getLogger(__name__)

__all__ = (
    "run_performance_for_tournament",
    "run_player_anomalies_for_tournament",
    "run_shift_for_tournament",
    "run_standings_for_tournament",
    "run_for_tournament",
)


async def _algorithm_id(session: AsyncSession, name: str) -> int | None:
    return await session.scalar(
        sa.select(models.AnalyticsAlgorithm.id).where(
            models.AnalyticsAlgorithm.name == name
        )
    )


def _explanation_rows(
    per_player: pd.DataFrame,
    feature_frame: pd.DataFrame,
    models_by_role: dict[str, PerformanceModelV2],
    algorithm_id: int,
) -> tuple[list[dict[str, typing.Any]], dict[int, list[dict[str, typing.Any]]]]:
    """Compute SHAP top-5 contributions per player using TreeExplainer.

    Returns ``(explanation_rows, top_features_by_player)``. Lazy imports SHAP
    to keep import time light when only computing without SHAP.
    """
    if per_player.empty:
        return [], {}
    try:
        import shap  # type: ignore[import-untyped]
    except Exception:  # pragma: no cover — SHAP missing
        logger.warning("shap not available; skipping explanation rows")
        return [], {}

    rows: list[dict[str, typing.Any]] = []
    top_features_by_player: dict[int, list[dict[str, typing.Any]]] = {}

    # Aggregate per-(player, role) feature means so SHAP has a single sample.
    agg = (
        feature_frame.groupby(["player_id", "role"], dropna=False)
        .mean(numeric_only=True)
        .reset_index()
    )

    for role, model in models_by_role.items():
        role_rows = agg[agg["role"].str.lower() == role.lower()]
        if role_rows.empty:
            continue
        try:
            explainer = shap.TreeExplainer(model.booster)
            X = role_rows[model.feature_order].fillna(0.0)
            shap_values = explainer.shap_values(X)
            base_value = float(getattr(explainer, "expected_value", 0.0) or 0.0)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("SHAP failed for role=%s: %s", role, exc)
            continue

        for (_, src_row), values in zip(role_rows.iterrows(), shap_values, strict=False):
            player_id = int(src_row["player_id"])
            contributions = sorted(
                (
                    {
                        "feature": col,
                        "shap": float(val),
                        "value": float(src_row[col]) if pd.notna(src_row[col]) else None,
                    }
                    for col, val in zip(model.feature_order, values, strict=False)
                ),
                key=lambda c: abs(c["shap"]),
                reverse=True,
            )
            tournament_id = int(per_player.loc[per_player["player_id"] == player_id, "tournament_id"].iloc[0])
            rows.append(
                {
                    "algorithm_id": algorithm_id,
                    "entity_id": player_id,
                    "entity_kind": "player",
                    "tournament_id": tournament_id,
                    "base_value": base_value,
                    "contributions": contributions,
                }
            )
            top_features_by_player[player_id] = contributions[:5]
    return rows, top_features_by_player


async def run_performance_for_tournament(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    include_shap: bool = True,
) -> int:
    """Compute v2 Performance for one tournament and upsert into ``analytics.performance``.

    Returns the number of rows written. Idempotent: existing rows for
    ``(tournament_id, player_id, algorithm_id)`` are deleted before insert.
    """
    algorithm_id = await _algorithm_id(session, PERFORMANCE_ALGORITHM_NAME)
    if algorithm_id is None:
        logger.warning(
            "No %s algorithm row found; run training first", PERFORMANCE_ALGORITHM_NAME
        )
        return 0

    artifacts = await load_active_artifacts(session, model_kind=PERFORMANCE_MODEL_KIND)
    if not artifacts:
        logger.warning("No active Performance v2 artifacts; run training first")
        return 0

    models_by_role: dict[str, PerformanceModelV2] = {}
    for art in artifacts:
        if art.role is None:
            continue
        try:
            models_by_role[art.role.lower()] = load_artifact(art.storage_uri)
        except FileNotFoundError:
            logger.warning(
                "Missing artifact file for role=%s (uri=%s)", art.role, art.storage_uri
            )

    if not models_by_role:
        return 0

    feature_frame = await build_match_features_with_strength(
        session, tournament_id, workspace_id=workspace_id
    )
    if feature_frame.empty:
        logger.info("No matches for tournament_id=%d; nothing to write", tournament_id)
        return 0

    # Per-match predictions per role.
    y_hat = pd.Series(index=feature_frame.index, dtype=float)
    y_q10 = pd.Series(index=feature_frame.index, dtype=float)
    y_q90 = pd.Series(index=feature_frame.index, dtype=float)
    for role, model in models_by_role.items():
        mask = feature_frame["role"].str.lower() == role.lower()
        if not mask.any():
            continue
        sub = model.predict_match(feature_frame[mask])
        y_hat.loc[mask] = sub["y_hat"]
        y_q10.loc[mask] = sub["y_q10"]
        y_q90.loc[mask] = sub["y_q90"]

    per_player = aggregate_to_tournament(feature_frame, y_hat, y_q10, y_q90)
    if per_player.empty:
        return 0
    per_player["impact_score"] = impact_score_within_role(per_player)
    grid = await get_division_grid(session, workspace_id, tournament_id=tournament_id)
    player_ranks = (
        feature_frame.groupby("player_id", dropna=False)["rank"].first().to_dict()
    )
    per_player["division"] = per_player["player_id"].map(
        lambda player_id: resolve_tournament_division(
            int(player_ranks.get(player_id, 0) or 0),
            tournament_grid=grid,
        )
    )
    per_player = attach_local_performance(per_player)
    # Small (tournament, role) cohorts get a smooth normal-CDF impact score
    # instead of a coarse, unstable empirical percentile.
    per_player = stabilize_small_cohort_impact(per_player)

    # Optional: SHAP top-5 contributions denormalised into ``top_features``.
    if include_shap:
        rows, top_features_by_player = _explanation_rows(
            per_player, feature_frame, models_by_role, algorithm_id
        )
        per_player["top_features"] = per_player["player_id"].map(
            lambda pid: top_features_by_player.get(int(pid))
        )
    else:
        rows = []
        per_player["top_features"] = None

    # Idempotent upsert: delete existing rows for this tournament/algorithm, then insert.
    await session.execute(
        sa.delete(models.AnalyticsPerformance).where(
            models.AnalyticsPerformance.tournament_id == tournament_id,
            models.AnalyticsPerformance.algorithm_id == algorithm_id,
        )
    )
    insert_rows = [
        {
            "tournament_id": int(row["tournament_id"]),
            "player_id": int(row["player_id"]),
            "algorithm_id": algorithm_id,
            "impact_score": float(row["impact_score"]) if pd.notna(row["impact_score"]) else 0.0,
            "raw_value": float(row["raw_value"]) if pd.notna(row["raw_value"]) else 0.0,
            "confidence": float(row["confidence"]) if pd.notna(row["confidence"]) else 0.0,
            "log_coverage": float(row["log_coverage"]) if pd.notna(row["log_coverage"]) else 0.0,
            "local_mean": float(row["local_mean"]) if pd.notna(row["local_mean"]) else 0.0,
            "local_std": float(row["local_std"]) if pd.notna(row["local_std"]) else 1.0,
            "local_residual": float(row["local_residual"])
            if pd.notna(row["local_residual"])
            else 0.0,
            "local_zscore": float(row["local_zscore"])
            if pd.notna(row["local_zscore"])
            else 0.0,
            "local_percentile": float(row["local_percentile"])
            if pd.notna(row["local_percentile"])
            else 50.0,
            "local_reference_n": int(row["local_reference_n"])
            if pd.notna(row["local_reference_n"])
            else 0,
            "local_band_min_div": int(row["local_band_min_div"])
            if pd.notna(row["local_band_min_div"])
            else None,
            "local_band_max_div": int(row["local_band_max_div"])
            if pd.notna(row["local_band_max_div"])
            else None,
            "top_features": row["top_features"],
        }
        for _, row in per_player.iterrows()
    ]
    if insert_rows:
        await session.execute(sa.insert(models.AnalyticsPerformance), insert_rows)

    # Explanations table: archive full contribution list.
    if rows:
        await session.execute(
            sa.delete(models.AnalyticsExplanation).where(
                models.AnalyticsExplanation.algorithm_id == algorithm_id,
                models.AnalyticsExplanation.tournament_id == tournament_id,
                models.AnalyticsExplanation.entity_kind == "player",
            )
        )
        await session.execute(sa.insert(models.AnalyticsExplanation), rows)

    await session.commit()
    return len(insert_rows)


async def run_shift_for_tournament(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
) -> int:
    """Compute Shift v2 for one tournament and upsert into ``analytics.shifts``.

    Writes under the ``"OpenSkill + ML"`` algorithm row, leaving v1 shifts
    untouched. Returns the number of player rows written.
    """
    algorithm_id = await _algorithm_id(session, SHIFT_ALGORITHM_NAME)
    if algorithm_id is None:
        logger.warning("No %s algorithm row; run training first", SHIFT_ALGORITHM_NAME)
        return 0

    artifact = await load_active_artifact(
        session,
        algorithm_id=algorithm_id,
        model_kind=SHIFT_MODEL_KIND,
        role=None,
    )
    if artifact is None:
        logger.warning("No active Shift v2 artifact; run training first")
        return 0

    try:
        model: ShiftModelV2 = load_artifact(artifact.storage_uri)
    except FileNotFoundError:
        logger.warning("Missing shift v2 artifact file at %s", artifact.storage_uri)
        return 0

    feature_frame = await build_shift_feature_frame(
        session, [tournament_id], workspace_id=workspace_id
    )
    if feature_frame.empty:
        return 0

    preds = model.predict_with_confidence(feature_frame)
    feature_frame = feature_frame.assign(**preds)

    await session.execute(
        sa.delete(models.AnalyticsShift).where(
            models.AnalyticsShift.tournament_id == tournament_id,
            models.AnalyticsShift.algorithm_id == algorithm_id,
        )
    )
    insert_rows = [
        {
            "tournament_id": int(row["tournament_id"]),
            "algorithm_id": algorithm_id,
            "player_id": int(row["player_id"]),
            "shift": float(row["shift_v2"]) if pd.notna(row["shift_v2"]) else 0.0,
            "confidence": float(row["confidence"]) if pd.notna(row["confidence"]) else 0.0,
            "effective_evidence": float(row.get("match_count", 0) or 0),
            "sample_tournaments": int(row.get("tournaments_played", 0) or 0),
            "sample_matches": int(row.get("match_count", 0) or 0),
            "log_coverage": float(row.get("log_coverage", 0) or 0),
        }
        for _, row in feature_frame.iterrows()
        if pd.notna(row.get("player_id"))
    ]
    if insert_rows:
        await session.execute(sa.insert(models.AnalyticsShift), insert_rows)
    await session.commit()
    return len(insert_rows)


def _build_matchups(feature_frame: pd.DataFrame, p_home) -> pd.DataFrame:
    """Pair ``(home_team_id, away_team_id, p_home_wins)`` for the simulation.

    Bracket placeholder encounters (TBD semis/finals, byes) exist as
    ``Encounter`` rows with NULL team ids before their feeding matches finish.
    pandas reads those NULLs as NaN, turning the id column into ``float64``;
    casting it with ``.astype(int)`` then raises ``IntCastingNaNError``. Such
    rows can't form a real matchup anyway, so they are dropped here — *after*
    aligning ``p_home`` positionally so the surviving probabilities stay tied
    to their rows.
    """
    paired = feature_frame.assign(p_home_wins=p_home).dropna(
        subset=["home_team_id", "away_team_id"]
    )
    return pd.DataFrame(
        {
            "home_team_id": paired["home_team_id"].astype(int).to_numpy(),
            "away_team_id": paired["away_team_id"].astype(int).to_numpy(),
            "p_home_wins": paired["p_home_wins"].to_numpy(),
        }
    )


async def run_standings_for_tournament(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    n_iter: int = 5000,
    prob_sharpening: float | None = None,
) -> int:
    """Compute Monte Carlo standings distribution and upsert results.

    Also writes ``round(mean_position)`` into the legacy
    ``analytics.predictions`` table so v1 integer-place consumers stay live.
    Returns the number of team rows persisted.

    ``prob_sharpening`` controls how decisively calibrated win-probabilities are
    pushed away from 0.5 before the simulation (see :func:`simulate_standings`);
    when ``None`` it falls back to ``settings.standings_prob_sharpening``.
    """
    if prob_sharpening is None:
        prob_sharpening = settings.standings_prob_sharpening
    algorithm_id = await _algorithm_id(session, STANDINGS_ALGORITHM_NAME)
    if algorithm_id is None:
        logger.warning(
            "No %s algorithm row; run training first", STANDINGS_ALGORITHM_NAME
        )
        return 0
    artifact = await load_active_artifact(
        session,
        algorithm_id=algorithm_id,
        model_kind=STANDINGS_MODEL_KIND,
        role=None,
    )
    if artifact is None:
        logger.warning("No active Standings v2 artifact; run training first")
        return 0
    try:
        model: WinProbabilityModel = load_artifact(artifact.storage_uri)
    except FileNotFoundError:
        logger.warning("Missing standings v2 artifact at %s", artifact.storage_uri)
        return 0

    feature_frame = await build_standings_training_frame(
        session, [tournament_id], workspace_id=workspace_id
    )
    if feature_frame.empty:
        return 0

    p_home = model.predict_proba(feature_frame)
    matchups = _build_matchups(feature_frame, p_home)
    if matchups.empty:
        logger.info(
            "No fully-assigned matchups for tournament_id=%d; nothing to simulate",
            tournament_id,
        )
        return 0
    teams = sorted(
        {int(t) for t in matchups["home_team_id"].tolist() + matchups["away_team_id"].tolist()}
    )
    distribution = simulate_standings(
        matchups, teams, n_iter=n_iter, prob_sharpening=prob_sharpening
    )
    if distribution.empty:
        return 0

    # Idempotent upsert: distribution table.
    await session.execute(
        sa.delete(models.AnalyticsStandingsDistribution).where(
            models.AnalyticsStandingsDistribution.tournament_id == tournament_id,
            models.AnalyticsStandingsDistribution.algorithm_id == algorithm_id,
        )
    )
    rows = [
        {
            "tournament_id": tournament_id,
            "team_id": int(r["team_id"]),
            "algorithm_id": algorithm_id,
            "mean_position": float(r["mean_position"]),
            "median_position": float(r["median_position"]),
            "p10_position": float(r["p10_position"]),
            "p90_position": float(r["p90_position"]),
            "prob_top1": float(r["prob_top1"]),
            "prob_top3": float(r["prob_top3"]),
            "prob_top8": float(r["prob_top8"]),
            "position_histogram": r["position_histogram"],
        }
        for _, r in distribution.iterrows()
    ]
    await session.execute(sa.insert(models.AnalyticsStandingsDistribution), rows)

    # Legacy ``AnalyticsPredictions.predicted_place`` mirror.
    await session.execute(
        sa.delete(models.AnalyticsPredictions).where(
            models.AnalyticsPredictions.tournament_id == tournament_id,
            models.AnalyticsPredictions.algorithm_id == algorithm_id,
        )
    )
    legacy_rows = [
        {
            "tournament_id": tournament_id,
            "team_id": int(r["team_id"]),
            "algorithm_id": algorithm_id,
            "predicted_place": int(round(float(r["mean_position"]))),
        }
        for _, r in distribution.iterrows()
    ]
    await session.execute(sa.insert(models.AnalyticsPredictions), legacy_rows)

    await session.commit()
    return len(rows)


async def run_for_tournament(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    model_kinds: typing.Sequence[str] | None = None,
) -> dict[str, int]:
    """Dispatch every available v2 model for one tournament.

    Returns ``{kind: rows_written}``.
    """
    kinds = set(
        model_kinds
        or ("performance", "player_anomalies", "shift", "standings", "match_quality")
    )
    summary: dict[str, int] = {}
    if "performance" in kinds:
        summary["performance"] = await run_performance_for_tournament(
            session, tournament_id, workspace_id=workspace_id
        )
    if "player_anomalies" in kinds or "match_quality" in kinds:
        summary["player_anomalies"] = await run_player_anomalies_for_tournament(
            session,
            tournament_id,
            workspace_id=workspace_id,
        )
    if "shift" in kinds:
        summary["shift"] = await run_shift_for_tournament(
            session, tournament_id, workspace_id=workspace_id
        )
    if "standings" in kinds:
        summary["standings"] = await run_standings_for_tournament(
            session, tournament_id, workspace_id=workspace_id
        )
    if "match_quality" in kinds:
        # Lazy import to avoid pulling ruptures unless used.
        from .match_quality_runner import run_match_quality_for_tournament

        summary["match_quality"] = await run_match_quality_for_tournament(
            session, tournament_id, workspace_id=workspace_id
        )
    return summary
