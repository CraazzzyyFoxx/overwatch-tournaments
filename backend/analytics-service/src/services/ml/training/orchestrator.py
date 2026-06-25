"""High-level training entry point.

Builds the feature frames once (expensive — joins MatchStatistics, KillFeed,
event tables and runs OpenSkill replays), then dispatches per-model trainers.
Each artifact is serialised under ``ANALYTICS_MODELS_DIR`` and registered in
``analytics.ml_model_artifact`` with ``is_active=True``.
"""

from __future__ import annotations

import logging
import typing
from dataclasses import dataclass

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings

from .. import FEATURE_VERSION
from ..features.aggregations import build_match_features_with_strength
from ..features.shift_features import build_shift_feature_frame
from ..features.standings_features import build_standings_training_frame
from ..models.base import artifact_path, save_artifact
from ..models.performance_v2 import (
    PerformanceTrainingResult,
    train_performance_v2,
)
from ..models.shift_v2 import ShiftTrainingResult, train_shift_v2
from ..models.standings_v2 import StandingsTrainingResult, train_standings_v2
from .registry import ensure_algorithm, register_artifact
from .splits import TimeSeriesSplit, tournament_ids_up_to

logger = logging.getLogger(__name__)

__all__ = (
    "PERFORMANCE_ALGORITHM_NAME",
    "SHIFT_ALGORITHM_NAME",
    "PerformanceTrainingOutcome",
    "ShiftTrainingOutcome",
    "train_performance_v2_for_cutoff",
    "train_shift_v2_for_cutoff",
    "train_all_models",
)


PERFORMANCE_ALGORITHM_NAME = "Performance ML v2"
PERFORMANCE_MODEL_KIND = "performance"
PERFORMANCE_MODEL_VERSION = "2.0.0"

SHIFT_ALGORITHM_NAME = "OpenSkill + ML"
SHIFT_MODEL_KIND = "shift"
SHIFT_MODEL_VERSION = "2.0.0"

STANDINGS_ALGORITHM_NAME = "Standings MC v2"
STANDINGS_MODEL_KIND = "standings"
STANDINGS_MODEL_VERSION = "2.0.0"

MATCH_QUALITY_ALGORITHM_NAME = "Match Quality v1"
MATCH_QUALITY_MODEL_KIND = "match_quality"
MATCH_QUALITY_MODEL_VERSION = "1.0.0"

ROLES = ("tank", "damage", "support")
# Shift v2 supervises its blend weights on the realised division move.
SHIFT_LABEL_COLUMNS = ("current_div", "next_tournament_div")


@dataclass
class PerformanceTrainingOutcome:
    role: str
    algorithm_id: int
    artifact_id: int
    metrics: dict[str, float]


@dataclass
class ShiftTrainingOutcome:
    algorithm_id: int
    artifact_id: int
    metrics: dict[str, float]


@dataclass
class StandingsTrainingOutcome:
    algorithm_id: int
    artifact_id: int
    metrics: dict[str, float]


def _count_labelled_shift_rows(df: pd.DataFrame) -> int:
    """Return the number of shift rows that can supervise the blend weights.

    The blend is fit against the realised division move, so a labelled row needs
    both ``current_div`` and ``next_tournament_div`` — see ``shift_v2.train_shift_v2``.
    """
    if df.empty or any(c not in df.columns for c in SHIFT_LABEL_COLUMNS):
        return 0
    return int(df.dropna(subset=list(SHIFT_LABEL_COLUMNS)).shape[0])


def _prepare_shift_training_frames(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Avoid spending the only labelled shift rows on validation.

    Realised-move labels need a known next tournament, so shallow histories often
    make the latest pre-cutoff tournament the only supervised one. Validation is
    optional; training data is not.
    """
    if _count_labelled_shift_rows(train_df) > 0:
        return train_df, val_df
    if _count_labelled_shift_rows(val_df) == 0:
        return train_df, val_df

    logger.info(
        "Shift v2 validation holdout contains the only labelled rows; "
        "reusing it for training without validation"
    )
    return val_df, pd.DataFrame()


async def _build_training_frame(
    session: AsyncSession,
    tournament_ids: typing.Iterable[int],
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Concatenate per-tournament match feature frames into a single DataFrame.

    Each tournament is processed in isolation so the opponent-strength
    snapshot can replay only the prior 10 tournaments per call.
    """
    frames: list[pd.DataFrame] = []
    for tid in tournament_ids:
        df = await build_match_features_with_strength(
            session,
            tid,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


async def train_performance_v2_for_cutoff(
    session: AsyncSession,
    cutoff_tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> list[PerformanceTrainingOutcome]:
    """Train Performance v2 for every role using all tournaments up to cutoff.

    Side effects:

    - inserts one ``MLModelArtifact`` row per role with ``is_active=True``
      and deactivates older versions of the same role,
    - writes the booster pickles to ``ANALYTICS_MODELS_DIR``.
    """
    algorithm = await ensure_algorithm(session, PERFORMANCE_ALGORITHM_NAME)

    all_ids = await tournament_ids_up_to(
        session,
        cutoff_tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if not all_ids:
        logger.warning(
            "No tournaments to train on (cutoff=%d, workspace_id=%s)",
            cutoff_tournament_id,
            workspace_ids if workspace_ids is not None else workspace_id,
        )
        return []

    split = TimeSeriesSplit.from_ids(all_ids, test_id=cutoff_tournament_id)
    train_ids = split.train_ids or tuple(all_ids[:-1])
    val_ids = (split.val_id,) if split.val_id is not None else ()

    logger.info(
        "Performance v2 training: cutoff=%d, train=%d tournaments, val=%s",
        cutoff_tournament_id,
        len(train_ids),
        val_ids,
    )

    train_df = await _build_training_frame(
        session,
        train_ids,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    val_df = (
        await _build_training_frame(
            session,
            val_ids,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        if val_ids
        else pd.DataFrame()
    )
    if train_df.empty:
        logger.warning("Empty training frame; skipping Performance v2")
        return []

    outcomes: list[PerformanceTrainingOutcome] = []
    for role in ROLES:
        try:
            result: PerformanceTrainingResult = train_performance_v2(
                train_df, role=role, val_df=val_df if not val_df.empty else None
            )
        except ValueError as exc:
            logger.warning("Skipping role=%s: %s", role, exc)
            continue

        path = artifact_path(
            algorithm.id, PERFORMANCE_MODEL_VERSION, f"performance_{role}.joblib"
        )
        storage_uri = save_artifact(result.model, path)

        artifact = await register_artifact(
            session,
            algorithm_id=algorithm.id,
            model_kind=PERFORMANCE_MODEL_KIND,
            role=role,
            version=PERFORMANCE_MODEL_VERSION,
            storage_uri=storage_uri,
            feature_version=FEATURE_VERSION,
            training_cutoff_tournament_id=cutoff_tournament_id,
            metrics=result.metrics,
            feature_importance=result.feature_importance,
            activate=True,
        )
        outcomes.append(
            PerformanceTrainingOutcome(
                role=role,
                algorithm_id=algorithm.id,
                artifact_id=artifact.id,
                metrics=result.metrics,
            )
        )
    return outcomes


async def train_all_models(
    session: AsyncSession,
    cutoff_tournament_id: int,
    *,
    model_kinds: typing.Sequence[str] | None = None,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> dict[str, typing.Any]:
    """Train every configured model kind for ``cutoff_tournament_id``.

    ``model_kinds`` defaults to all kinds available at the current phase.
    Returns a summary dict ``{kind: <outcomes>}`` for the CLI to render.
    """
    # Train every available kind by default; the UI / CLI can still narrow via
    # ``model_kinds=[...]`` to skip the slower stages (shift residual,
    # Standings classifier).
    kinds = set(model_kinds or ("performance", "shift", "standings"))
    summary: dict[str, typing.Any] = {}

    if "performance" in kinds:
        summary["performance"] = [
            outcome.__dict__
            for outcome in await train_performance_v2_for_cutoff(
                session,
                cutoff_tournament_id,
                workspace_id=workspace_id,
                workspace_ids=workspace_ids,
            )
        ]
    if "shift" in kinds:
        outcome = await train_shift_v2_for_cutoff(
            session,
            cutoff_tournament_id,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        summary["shift"] = [outcome.__dict__] if outcome else []
    if "standings" in kinds:
        outcome_s = await train_standings_v2_for_cutoff(
            session,
            cutoff_tournament_id,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        summary["standings"] = [outcome_s.__dict__] if outcome_s else []
    return summary


async def train_standings_v2_for_cutoff(
    session: AsyncSession,
    cutoff_tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> StandingsTrainingOutcome | None:
    """Train Standings v2 win-probability classifier."""
    algorithm = await ensure_algorithm(session, STANDINGS_ALGORITHM_NAME)
    all_ids = await tournament_ids_up_to(
        session,
        cutoff_tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if not all_ids:
        return None

    split = TimeSeriesSplit.from_ids(all_ids, test_id=cutoff_tournament_id)
    train_ids = split.train_ids or tuple(all_ids[:-1])
    val_ids = (split.val_id,) if split.val_id is not None else ()

    train_df = await build_standings_training_frame(
        session,
        train_ids,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    val_df = (
        await build_standings_training_frame(
            session,
            val_ids,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        if val_ids
        else pd.DataFrame()
    )
    if train_df.empty:
        logger.warning("Empty standings training frame")
        return None

    try:
        result: StandingsTrainingResult = train_standings_v2(
            train_df, val_df=val_df if not val_df.empty else None
        )
    except ValueError as exc:
        logger.warning("Standings v2 training skipped: %s", exc)
        return None

    path = artifact_path(algorithm.id, STANDINGS_MODEL_VERSION, "standings.joblib")
    storage_uri = save_artifact(result.model, path)
    artifact = await register_artifact(
        session,
        algorithm_id=algorithm.id,
        model_kind=STANDINGS_MODEL_KIND,
        role=None,
        version=STANDINGS_MODEL_VERSION,
        storage_uri=storage_uri,
        feature_version=FEATURE_VERSION,
        training_cutoff_tournament_id=cutoff_tournament_id,
        metrics=result.metrics,
        feature_importance=result.feature_importance,
        activate=True,
    )
    return StandingsTrainingOutcome(
        algorithm_id=algorithm.id, artifact_id=artifact.id, metrics=result.metrics
    )


async def train_shift_v2_for_cutoff(
    session: AsyncSession,
    cutoff_tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> ShiftTrainingOutcome | None:
    """Train Shift v2 residual model using all tournaments up to cutoff."""
    algorithm = await ensure_algorithm(session, SHIFT_ALGORITHM_NAME)
    all_ids = await tournament_ids_up_to(
        session,
        cutoff_tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if not all_ids:
        return None

    split = TimeSeriesSplit.from_ids(all_ids, test_id=cutoff_tournament_id)
    train_ids = split.train_ids or tuple(all_ids[:-1])
    val_ids = (split.val_id,) if split.val_id is not None else ()

    logger.info(
        "Shift v2 training: cutoff=%d, train=%d tournaments",
        cutoff_tournament_id,
        len(train_ids),
    )

    train_df = await build_shift_feature_frame(
        session,
        train_ids,
        history_through_tournament_id=cutoff_tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    val_df = (
        await build_shift_feature_frame(
            session,
            val_ids,
            history_through_tournament_id=cutoff_tournament_id,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        if val_ids
        else pd.DataFrame()
    )
    train_df, val_df = _prepare_shift_training_frames(train_df, val_df)
    if train_df.empty:
        logger.warning("Empty shift training frame")
        return None

    try:
        result: ShiftTrainingResult = train_shift_v2(
            train_df,
            val_df=val_df if not val_df.empty else None,
            w_team=settings.shift_w_team,
            w_os=settings.shift_w_os,
            indiv_scale_top=settings.shift_indiv_scale_top,
            indiv_scale_bottom=settings.shift_indiv_scale_bottom,
            indiv_clamp_top=settings.shift_indiv_clamp_top,
            indiv_clamp_bottom=settings.shift_indiv_clamp_bottom,
            dominance_gain=settings.shift_dominance_gain,
            dominance_cap=settings.shift_dominance_cap,
            placement_floor=settings.shift_placement_floor,
            clamp_top_grid_ref=settings.shift_clamp_top_grid_ref,
        )
    except ValueError as exc:
        logger.warning("Shift v2 training skipped: %s", exc)
        return None

    path = artifact_path(algorithm.id, SHIFT_MODEL_VERSION, "shift.joblib")
    storage_uri = save_artifact(result.model, path)
    artifact = await register_artifact(
        session,
        algorithm_id=algorithm.id,
        model_kind=SHIFT_MODEL_KIND,
        role=None,
        version=SHIFT_MODEL_VERSION,
        storage_uri=storage_uri,
        feature_version=FEATURE_VERSION,
        training_cutoff_tournament_id=cutoff_tournament_id,
        metrics=result.metrics,
        feature_importance=result.feature_importance,
        activate=True,
    )
    return ShiftTrainingOutcome(
        algorithm_id=algorithm.id, artifact_id=artifact.id, metrics=result.metrics
    )
