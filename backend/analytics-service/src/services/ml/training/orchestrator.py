"""High-level training entry point.

Builds the feature frames once (native observation queries and OpenSkill
replays), then dispatches per-model trainers.
Each artifact is serialised under ``ANALYTICS_MODELS_DIR`` and registered in
``analytics.ml_model_artifact`` with ``is_active=True``.
"""

from __future__ import annotations

import logging
import typing
from dataclasses import dataclass

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from shared.disciplines.analytics import AnalyticsExports
from shared.domain.analytics import (
    PerformanceTrainingResult,
    ShiftTrainingResult,
    StandingsTrainingResult,
)
from src.core.analytics_exports import analytics_exports, tournament_discipline
from src.core.config import settings

from .. import FEATURE_VERSION
from ..device import lightgbm_devices, xgboost_devices
from ..features.aggregations import build_match_features_with_strength
from ..features.shift_features import build_shift_feature_frame
from ..features.standings_features import build_standings_training_frame
from ..models.base import artifact_path, save_artifact
from .registry import registry_service
from .splits import TimeSeriesSplit, tournament_ids_up_to

logger = logging.getLogger(__name__)

__all__ = (
    "PerformanceTrainingOutcome",
    "ShiftTrainingOutcome",
    "train_performance_v2_for_cutoff",
    "train_shift_v2_for_cutoff",
    "train_all_models",
)


# Shift v2 supervises its blend weights on the realised division move.
SHIFT_LABEL_COLUMNS = ("current_div", "next_tournament_div")


async def _scope(session: AsyncSession, cutoff_tournament_id: int) -> tuple[str, AnalyticsExports]:
    """The cutoff tournament's discipline and that discipline's analytics module.

    The tournament owns the request: its discipline picks the module, an unknown cutoff is an error, and a discipline
    that declares no module raises ``UnsupportedAnalytics`` before anything is read, written or charged.
    """
    discipline = await tournament_discipline(session, cutoff_tournament_id)
    if discipline is None:
        raise LookupError(f"cutoff tournament {cutoff_tournament_id} not found")
    return discipline, analytics_exports(discipline)


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
        "Shift v2 validation holdout contains the only labelled rows; reusing it for training without validation"
    )
    return val_df, pd.DataFrame()


async def _build_training_frame(
    session: AsyncSession,
    tournament_ids: typing.Iterable[int],
    *,
    discipline: str,
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
            discipline=discipline,
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
    """Train Performance v2 for every rated role of the cutoff's discipline using all its tournaments up to cutoff.

    Side effects:

    - inserts one ``MLModelArtifact`` row per role with ``is_active=True``
      and deactivates older versions of the same role,
    - writes the booster pickles to ``ANALYTICS_MODELS_DIR``,
    - commits the session before each role's fit, so every earlier registration is committed by then (the pickle is
      overwritten in place as soon as it is saved, so a rollback after it never restored the old model anyway).
    """
    discipline, exports = await _scope(session, cutoff_tournament_id)
    declaration = exports.MODELS["performance"]
    # The rated roles the module declares, validated against the module's own feature selector before any frame is built:
    # a catalog role the module cannot train is a declaration error, not a quietly skipped role.
    roles = await registry_service.rated_roles(session, discipline=discipline)
    for code in roles:
        exports.features_for_role(code)
    algorithm = await registry_service.ensure_algorithm(session, declaration.algorithm_name)

    all_ids = await tournament_ids_up_to(
        session,
        cutoff_tournament_id,
        discipline=discipline,
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
        discipline=discipline,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    val_df = (
        await _build_training_frame(
            session,
            val_ids,
            discipline=discipline,
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
    for code, role_row in roles.items():
        # A fit can run for minutes: end the transaction (the frame reads, or the previous role's registration) first,
        # or pgBouncer's idle-in-transaction timeout kills the connection under it.
        await session.commit()
        try:
            result: PerformanceTrainingResult = exports.train_performance_v2(
                train_df,
                role=code,
                val_df=val_df if not val_df.empty else None,
                devices=lightgbm_devices(),
            )
        except ValueError as exc:
            logger.warning("Skipping role=%s: %s", code, exc)
            continue

        path = artifact_path(algorithm.id, declaration.model_version, f"performance_{code}.joblib")
        storage_uri = save_artifact(result.model, path)

        artifact = await registry_service.register_artifact(
            session,
            discipline=discipline,
            algorithm_id=algorithm.id,
            model_kind=declaration.model_kind,
            role_id=role_row.id,
            version=declaration.model_version,
            storage_uri=storage_uri,
            feature_version=FEATURE_VERSION,
            training_cutoff_tournament_id=cutoff_tournament_id,
            metrics=result.metrics,
            feature_importance=result.feature_importance,
            activate=True,
        )
        outcomes.append(
            PerformanceTrainingOutcome(
                role=code,
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

    The cutoff's discipline chooses the module; one that declares none raises ``UnsupportedAnalytics`` before any
    read or write. ``model_kinds`` defaults to every kind.
    Returns a summary dict ``{kind: <outcomes>}`` for the CLI to render. The session is committed before every fit, so
    the artifacts registered before a failure stay committed.
    """
    await _scope(session, cutoff_tournament_id)
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
    discipline, exports = await _scope(session, cutoff_tournament_id)
    declaration = exports.MODELS["standings"]
    algorithm = await registry_service.ensure_algorithm(session, declaration.algorithm_name)
    all_ids = await tournament_ids_up_to(
        session,
        cutoff_tournament_id,
        discipline=discipline,
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
        discipline=discipline,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    val_df = (
        await build_standings_training_frame(
            session,
            val_ids,
            discipline=discipline,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        if val_ids
        else pd.DataFrame()
    )
    if train_df.empty:
        logger.warning("Empty standings training frame")
        return None

    await session.commit()  # no transaction held across the fit (see train_performance_v2_for_cutoff)
    try:
        result: StandingsTrainingResult = exports.train_standings_v2(
            train_df,
            val_df=val_df if not val_df.empty else None,
            devices=xgboost_devices(),
        )
    except ValueError as exc:
        logger.warning("Standings v2 training skipped: %s", exc)
        return None

    path = artifact_path(algorithm.id, declaration.model_version, "standings.joblib")
    storage_uri = save_artifact(result.model, path)
    artifact = await registry_service.register_artifact(
        session,
        discipline=discipline,
        algorithm_id=algorithm.id,
        model_kind=declaration.model_kind,
        role_id=None,
        version=declaration.model_version,
        storage_uri=storage_uri,
        feature_version=FEATURE_VERSION,
        training_cutoff_tournament_id=cutoff_tournament_id,
        metrics=result.metrics,
        feature_importance=result.feature_importance,
        activate=True,
    )
    return StandingsTrainingOutcome(algorithm_id=algorithm.id, artifact_id=artifact.id, metrics=result.metrics)


async def train_shift_v2_for_cutoff(
    session: AsyncSession,
    cutoff_tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> ShiftTrainingOutcome | None:
    """Train Shift v2 residual model using all tournaments up to cutoff."""
    discipline, exports = await _scope(session, cutoff_tournament_id)
    declaration = exports.MODELS["shift"]
    algorithm = await registry_service.ensure_algorithm(session, declaration.algorithm_name)
    all_ids = await tournament_ids_up_to(
        session,
        cutoff_tournament_id,
        discipline=discipline,
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
        discipline=discipline,
        history_through_tournament_id=cutoff_tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    val_df = (
        await build_shift_feature_frame(
            session,
            val_ids,
            discipline=discipline,
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

    await session.commit()  # no transaction held across the fit (see train_performance_v2_for_cutoff)
    try:
        result: ShiftTrainingResult = exports.train_shift_v2(
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

    path = artifact_path(algorithm.id, declaration.model_version, "shift.joblib")
    storage_uri = save_artifact(result.model, path)
    artifact = await registry_service.register_artifact(
        session,
        discipline=discipline,
        algorithm_id=algorithm.id,
        model_kind=declaration.model_kind,
        role_id=None,
        version=declaration.model_version,
        storage_uri=storage_uri,
        feature_version=FEATURE_VERSION,
        training_cutoff_tournament_id=cutoff_tournament_id,
        metrics=result.metrics,
        feature_importance=result.feature_importance,
        activate=True,
    )
    return ShiftTrainingOutcome(algorithm_id=algorithm.id, artifact_id=artifact.id, metrics=result.metrics)
