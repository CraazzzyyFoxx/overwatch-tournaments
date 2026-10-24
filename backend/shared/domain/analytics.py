"""Neutral analytics types: model declarations, model protocols and training results every discipline shares.

Pure declaration: no pandas/numpy import happens at runtime (frames are forward references), so the registry stays
importable by services that never run analytics. What a discipline's analytics package exports is
``shared.disciplines.analytics.AnalyticsExports``.
"""

from __future__ import annotations

import typing
from collections.abc import Sequence
from dataclasses import dataclass

if typing.TYPE_CHECKING:
    import numpy as np
    import pandas as pd

__all__ = (
    "INFERENCE_KINDS",
    "MATCH_QUALITY_MODEL",
    "PERFORMANCE_MODEL",
    "SHIFT_MODEL",
    "STANDINGS_MODEL",
    "MLModel",
    "MLTrainDevice",
    "ModelDeclaration",
    "PerformanceModel",
    "PerformanceTrainingResult",
    "ShiftModel",
    "ShiftTrainingResult",
    "StandingsModel",
    "StandingsTrainingResult",
    "align_features",
)

MLTrainDevice = typing.Literal["cpu", "cuda", "gpu"]


@dataclass(frozen=True, slots=True)
class ModelDeclaration:
    """What a trained or computed model is registered as: ``analytics.algorithm.name`` and artifact kind/version."""

    algorithm_name: str
    model_kind: str
    model_version: str


PERFORMANCE_MODEL = ModelDeclaration("Performance ML v2", "performance", "2.0.0")
SHIFT_MODEL = ModelDeclaration("OpenSkill + ML", "shift", "2.0.0")
STANDINGS_MODEL = ModelDeclaration("Standings MC v2", "standings", "2.2.0")
#: Computed deterministically at inference time: nothing is serialized under this declaration.
MATCH_QUALITY_MODEL = ModelDeclaration("Match Quality v1", "match_quality", "1.0.0")

#: The inference kinds one run dispatches by default (``player_anomalies`` has no artifact of its own).
INFERENCE_KINDS: tuple[str, ...] = ("performance", "player_anomalies", "shift", "standings", "match_quality")


@typing.runtime_checkable
class MLModel(typing.Protocol):
    """Common surface every model exposes.

    ``feature_order`` is the list of column names the underlying estimator was fitted on; consumers pass frames through
    :func:`align_features` before predicting.
    """

    feature_order: list[str]

    def predict(self, df: pd.DataFrame) -> pd.Series: ...


def align_features(df: pd.DataFrame, feature_order: Sequence[str]) -> pd.DataFrame:
    """Reorder/fill ``df`` to match ``feature_order`` exactly.

    Missing columns are inserted as ``NaN`` (LightGBM and XGBoost handle this natively); extra columns are silently
    dropped. The index is preserved so the caller can re-align predictions to the original rows.
    """
    import pandas as pd

    out = pd.DataFrame(index=df.index)
    for col in feature_order:
        if col in df.columns:
            out[col] = df[col]
        else:
            out[col] = float("nan")
    return out


class PerformanceModel(MLModel, typing.Protocol):
    role: str
    booster: typing.Any

    def predict_match(self, df: pd.DataFrame) -> pd.DataFrame: ...


class ShiftModel(MLModel, typing.Protocol):
    def predict_with_uncertainty(self, df: pd.DataFrame) -> pd.DataFrame: ...


class StandingsModel(MLModel, typing.Protocol):
    def predict_proba(self, df: pd.DataFrame) -> np.ndarray: ...


class PerformanceTrainingResult(typing.Protocol):
    role: str
    model: PerformanceModel
    metrics: dict[str, float]
    feature_importance: dict[str, float]


class StandingsTrainingResult(typing.Protocol):
    model: StandingsModel
    metrics: dict[str, float]
    feature_importance: dict[str, float]


class ShiftTrainingResult(typing.Protocol):
    model: ShiftModel
    metrics: dict[str, float]
    feature_importance: dict[str, float]
