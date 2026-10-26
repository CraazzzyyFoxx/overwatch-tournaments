"""Inference runner — populates v2 ``analytics.*`` tables for one tournament.

Each writer follows the same pattern: load active artifact → build feature
frame → predict → upsert.
"""

from __future__ import annotations

import logging
import typing

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.division_grid import DEFAULT_GRID, canonical_division_number
from shared.domain.analytics import PerformanceModel, ShiftModel, StandingsModel
from shared.services.workspace_scope import get_division_grid, get_tournament_workspace_id
from src.core.analytics_exports import tournament_module
from src.core.config import settings

from ..features.aggregations import build_match_features_with_strength
from ..features.shift_features import build_shift_feature_frame
from ..features.standings_features import build_standings_forecast_frame
from ..models.base import load_artifact_or_none
from ..training.registry import registry_service
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
    return await session.scalar(sa.select(models.AnalyticsAlgorithm.id).where(models.AnalyticsAlgorithm.name == name))


def _count(value: typing.Any) -> float:
    """A row's evidence figure, 0 when the frame has none: a flex player without a rated role reads NaN, and NaN is
    truthy, so ``value or 0`` would pass it through."""
    return float(value) if pd.notna(value) else 0.0


def _shap_by_player(
    per_player: pd.DataFrame,
    feature_frame: pd.DataFrame,
    models_by_role: dict[str, PerformanceModel],
) -> dict[int, tuple[float, list[dict[str, typing.Any]]]]:
    """SHAP contributions per player. Lazy-imports shap."""
    if per_player.empty:
        return {}
    try:
        import shap  # type: ignore[import-untyped]
    except Exception:  # pragma: no cover — SHAP missing
        logger.warning("shap not available; skipping explanation rows")
        return {}

    out: dict[int, tuple[float, list[dict[str, typing.Any]]]] = {}
    # A row without a rated role (a flex tournament has none at all) has no role model to explain it. Grouping it in
    # would make an all-None role level float NaN, which the ``.str`` accessor below rejects.
    ranked = feature_frame[feature_frame["role"].notna()]
    agg = ranked.groupby(["player_id", "role"]).mean(numeric_only=True).reset_index()

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
            out[player_id] = (base_value, contributions)
    return out


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
    owned = await tournament_module(session, tournament_id)
    if owned is None:
        logger.info("Tournament %d has no analytics module; no Performance v2 to compute", tournament_id)
        return 0
    discipline, exports = owned
    declaration = exports.MODELS["performance"]
    algorithm_id = await _algorithm_id(session, declaration.algorithm_name)
    if algorithm_id is None:
        logger.warning("No %s algorithm row found; run training first", declaration.algorithm_name)
        return 0

    artifacts = await registry_service.load_active_artifacts(
        session, discipline=discipline, algorithm_id=algorithm_id, model_kind=declaration.model_kind
    )
    if not artifacts:
        logger.warning("No active Performance v2 artifacts; run training first")
        return 0

    # Role artifacts are keyed by the discipline's own rated role (native id -> catalog code); an all-role artifact
    # (null role id) carries no role to mask by and is not loaded here.
    role_codes = {
        row.id: code
        for code, row in (await registry_service.rated_roles(session, discipline=discipline, active_only=False)).items()
    }
    models_by_role: dict[str, PerformanceModel] = {}
    for art in artifacts:
        code = role_codes.get(art.role_id) if art.role_id is not None else None
        if code is None:
            continue
        loaded = load_artifact_or_none(art.storage_uri)
        if loaded is None:
            logger.warning("Missing artifact file for role=%s (uri=%s)", code, art.storage_uri)
        else:
            models_by_role[code] = loaded

    if not models_by_role:
        return 0

    feature_frame = await build_match_features_with_strength(
        session, tournament_id, discipline=discipline, workspace_id=workspace_id
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

    per_player = exports.aggregate_to_tournament(feature_frame, y_hat, y_q10, y_q90)
    if per_player.empty:
        return 0
    per_player["impact_score"] = exports.impact_score_within_role(per_player)
    # Canonical OW division per player so the local-performance cohort bands are
    # comparable across workspaces; an unranked player has none (role-wide cohort).
    source_grid = await get_division_grid(session, workspace_id, tournament_id=tournament_id)
    player_ranks = feature_frame.groupby("player_id", dropna=False)["rank"].first().to_dict()
    per_player["division"] = per_player["player_id"].map(
        lambda player_id: None
        if pd.isna(rank := player_ranks.get(player_id))
        else canonical_division_number(source_grid, int(rank), DEFAULT_GRID)
    )
    per_player = exports.attach_local_performance(per_player)
    # Small (tournament, role) cohorts get a smooth normal-CDF impact score
    # instead of a coarse, unstable empirical percentile.
    per_player = exports.stabilize_small_cohort_impact(per_player)

    shap_by_player = _shap_by_player(per_player, feature_frame, models_by_role) if include_shap else {}

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
            "local_residual": float(row["local_residual"]) if pd.notna(row["local_residual"]) else 0.0,
            "local_zscore": float(row["local_zscore"]) if pd.notna(row["local_zscore"]) else 0.0,
            "local_percentile": float(row["local_percentile"]) if pd.notna(row["local_percentile"]) else 50.0,
            "local_reference_n": int(row["local_reference_n"]) if pd.notna(row["local_reference_n"]) else 0,
            "local_band_min_div": int(row["local_band_min_div"]) if pd.notna(row["local_band_min_div"]) else None,
            "local_band_max_div": int(row["local_band_max_div"]) if pd.notna(row["local_band_max_div"]) else None,
            "contributions": None if (shap := shap_by_player.get(int(row["player_id"]))) is None else shap[1],
            "base_value": None if shap is None else shap[0],
        }
        for _, row in per_player.iterrows()
    ]
    if insert_rows:
        await session.execute(sa.insert(models.AnalyticsPerformance), insert_rows)

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
    owned = await tournament_module(session, tournament_id)
    if owned is None:
        logger.info("Tournament %d has no analytics module; no Shift v2 to compute", tournament_id)
        return 0
    discipline, exports = owned
    declaration = exports.MODELS["shift"]
    algorithm_id = await _algorithm_id(session, declaration.algorithm_name)
    if algorithm_id is None:
        logger.warning("No %s algorithm row; run training first", declaration.algorithm_name)
        return 0

    artifact = await registry_service.load_active_artifact(
        session,
        discipline=discipline,
        algorithm_id=algorithm_id,
        model_kind=declaration.model_kind,
        role_id=None,
    )
    if artifact is None:
        logger.warning("No active Shift v2 artifact; run training first")
        return 0

    model: ShiftModel | None = load_artifact_or_none(artifact.storage_uri)
    if model is None:
        logger.warning("Missing shift v2 artifact file at %s", artifact.storage_uri)
        return 0

    feature_frame = await build_shift_feature_frame(
        session, [tournament_id], discipline=discipline, workspace_id=workspace_id
    )
    if feature_frame.empty:
        return 0

    preds = model.predict_with_uncertainty(feature_frame)
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
            "shift_sd": float(row["shift_sd"]) if pd.notna(row["shift_sd"]) else None,
            "effective_evidence": _count(row.get("match_count")),
            "sample_tournaments": int(_count(row.get("tournaments_played"))),
            "sample_matches": int(_count(row.get("match_count"))),
            "log_coverage": _count(row.get("log_coverage")),
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

    Rows without both team ids are dropped — *after* aligning ``p_home``
    positionally so the surviving probabilities stay tied to their rows. pandas
    reads a NULL id as NaN, which turns the id column into ``float64`` and makes
    ``.astype(int)`` raise ``IntCastingNaNError``; such a row describes no
    matchup anyway.
    """
    paired = feature_frame.assign(p_home_wins=p_home).dropna(subset=["home_team_id", "away_team_id"])
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

    Writes only ``analytics.standings_distribution``; the read API derives the
    scalar ``predicted_place`` from ``round(mean_position)`` on demand.
    Returns the number of team rows persisted.

    The simulated schedule is a **virtual double round robin** over the
    registered teams, never the tournament's own encounters — see
    :func:`build_standings_forecast_frame` for why feeding the realised bracket
    back in makes ``predicted_place`` a restatement of the result rather than a
    forecast of it.

    ``prob_sharpening`` controls how decisively calibrated win-probabilities are
    pushed away from 0.5 before the simulation (see :func:`simulate_standings`);
    when ``None`` it falls back to ``settings.standings_prob_sharpening``.
    """
    if prob_sharpening is None:
        prob_sharpening = settings.standings_prob_sharpening
    owned = await tournament_module(session, tournament_id)
    if owned is None:
        logger.info("Tournament %d has no analytics module; no Standings v2 to compute", tournament_id)
        return 0
    discipline, exports = owned
    declaration = exports.MODELS["standings"]
    algorithm_id = await _algorithm_id(session, declaration.algorithm_name)
    if algorithm_id is None:
        logger.warning("No %s algorithm row; run training first", declaration.algorithm_name)
        return 0
    artifact = await registry_service.load_active_artifact(
        session,
        discipline=discipline,
        algorithm_id=algorithm_id,
        model_kind=declaration.model_kind,
        role_id=None,
    )
    if artifact is None:
        logger.warning("No active Standings v2 artifact; run training first")
        return 0
    model: StandingsModel | None = load_artifact_or_none(artifact.storage_uri)
    if model is None:
        logger.warning("Missing standings v2 artifact at %s", artifact.storage_uri)
        return 0

    forecast_frame = await build_standings_forecast_frame(
        session, tournament_id, discipline=discipline, workspace_id=workspace_id
    )
    if forecast_frame.empty:
        logger.info("Fewer than two rateable rosters for tournament_id=%d; nothing to simulate", tournament_id)
        return 0
    matchups = _build_matchups(forecast_frame, model.predict_proba(forecast_frame))
    if matchups.empty:
        return 0
    teams = sorted({int(t) for t in matchups["home_team_id"].tolist() + matchups["away_team_id"].tolist()})
    # CPU, quadratic in teams (about 26 s for 64 at n_iter=5000): no read transaction idles across it (pgBouncer, 60 s).
    await session.commit()
    distribution = exports.simulate_standings(matchups, teams, n_iter=n_iter, prob_sharpening=prob_sharpening)
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

    await session.commit()
    return len(rows)


async def run_for_tournament(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    model_kinds: typing.Sequence[str] | None = None,
) -> dict[str, int]:
    """Dispatch every available v2 model of the tournament's discipline.

    Returns ``{kind: rows_written}``. A tournament whose discipline declares no analytics module (or that does not
    exist) gets an empty summary and nothing is read, written or cleared.
    """
    owned = await tournament_module(session, tournament_id)
    if owned is None:
        logger.info("Tournament %d has no analytics module; nothing to infer", tournament_id)
        return {}
    kinds = set(model_kinds or owned[1].INFERENCE_KINDS)
    # Scope to the tournament's own workspace when not given one. The CLI
    # (``ml.cli infer/backfill``) defaults to ``None``; without this it would
    # build feature cohorts and pick the division grid globally (all
    # workspaces) and diverge from the RPC recalculate job, which always passes
    # ``job.workspace_id``. A tournament belongs to exactly one workspace.
    if workspace_id is None:
        workspace_id = await get_tournament_workspace_id(session, tournament_id)
    summary: dict[str, int] = {}
    if "performance" in kinds:
        summary["performance"] = await run_performance_for_tournament(session, tournament_id, workspace_id=workspace_id)
    if "player_anomalies" in kinds or "match_quality" in kinds:
        summary["player_anomalies"] = await run_player_anomalies_for_tournament(
            session,
            tournament_id,
            workspace_id=workspace_id,
        )
    if "shift" in kinds:
        summary["shift"] = await run_shift_for_tournament(session, tournament_id, workspace_id=workspace_id)
    if "standings" in kinds:
        summary["standings"] = await run_standings_for_tournament(session, tournament_id, workspace_id=workspace_id)
    if "match_quality" in kinds:
        # Lazy import to avoid pulling ruptures unless used.
        from .match_quality_runner import run_match_quality_for_tournament

        summary["match_quality"] = await run_match_quality_for_tournament(
            session, tournament_id, workspace_id=workspace_id
        )
    return summary
