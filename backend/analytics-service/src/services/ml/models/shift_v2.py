"""Shift v2 ("OpenSkill + ML") — transparent team-result × individual blend.

Prod analysis showed the **team result** (W/L overperformance vs the balanced
seeding) is by far the strongest predictor of realised division moves, while
individual impact adds ~0 on top of it. So Shift v2 is no longer a residual
regressor toward the (mostly-zero) realised move — that collapsed confident
signals to nil. Instead it is a convex blend of three division-unit shift
components:

    shift_v2 = clamp( w_team·team_result + w_os·os_shift + w_imp·indiv_mod , ±3 )

- ``team_result`` — the v1 team-result Linear ``stable_shift`` (backbone).
- ``os_shift``    — OpenSkill mu-implied shift (rating context, the "OpenSkill").
- ``indiv_mod``   — Performance v2 ``local_zscore`` scaled small and hard-clamped
  to ±0.5 div (the "ML" part): differentiates carry vs passenger WITHIN a team
  but cannot flip or cancel the team signal.

Weights are fit from data (NNLS vs realised move, normalised to sum 1 so the
blend keeps ``team_result``'s calibration and never collapses). Newcomers
(no prior tournament) return the clipped team baseline with halved confidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .base import MLModel

__all__ = (
    "ShiftModelV2",
    "ShiftTrainingResult",
    "train_shift_v2",
)

logger = logging.getLogger(__name__)

# Output bounds (match the v1 linear stable clamp) and individual-modulation
# calibration: divisions of nudge per 1 std-dev of individual impact, hard-capped
# so it can only tilt the team signal, never override it.
SHIFT_RANGE: float = 3.0
NEWCOMER_SHIFT_RANGE: float = 1.5
INDIV_MOD_SCALE: float = 0.25
INDIV_MOD_CLAMP: float = 0.5

# Fallback blend weights (team-dominant) when the fit is degenerate / data-poor.
DEFAULT_BLEND: dict[str, float] = {"team": 0.6, "os": 0.3, "impact": 0.1}

# Columns the blend reads (for MLModel/feature introspection).
SHIFT_BLEND_COLUMNS: tuple[str, ...] = (
    "linear_stable_shift",
    "os_shift",
    "performance_v2_local_zscore",
)


def _clip(arr: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.clip(arr, lo, hi)


def _team_result(df: pd.DataFrame) -> pd.Series:
    """Team-result backbone: v1 Linear ``stable_shift``, falling back to os_shift."""
    fallback = pd.to_numeric(
        df.get("os_shift", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)
    if "linear_stable_shift" not in df.columns:
        return fallback
    stable = pd.to_numeric(df["linear_stable_shift"], errors="coerce")
    return stable.where(stable.notna(), fallback).fillna(0.0)


def _os_shift(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(
        df.get("os_shift", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)


def _indiv_mod(df: pd.DataFrame) -> pd.Series:
    """Individual carry/passenger nudge from Performance v2 local z-score.

    Scaled small and hard-clamped to ±``INDIV_MOD_CLAMP`` divisions so it can only
    tilt the team-result backbone, not override it. Zero where Performance v2 is
    absent.
    """
    z = pd.to_numeric(
        df.get("performance_v2_local_zscore", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0.0)
    return (INDIV_MOD_SCALE * z).clip(-INDIV_MOD_CLAMP, INDIV_MOD_CLAMP)


def _linear_confidence(df: pd.DataFrame) -> pd.Series:
    if "linear_confidence" not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df["linear_confidence"], errors="coerce").fillna(0.0).clip(0.0, 1.0)


def _newcomer_mask(df: pd.DataFrame) -> np.ndarray:
    return (
        df.get("is_newcomer", pd.Series(False, index=df.index)).fillna(False).astype(bool)
        | (pd.to_numeric(df.get("tournaments_played", 0), errors="coerce").fillna(0) <= 1)
    ).to_numpy()


@dataclass
class ShiftModelV2(MLModel):
    """Transparent convex blend of team-result, OpenSkill and individual impact."""

    w_team: float = DEFAULT_BLEND["team"]
    w_os: float = DEFAULT_BLEND["os"]
    w_impact: float = DEFAULT_BLEND["impact"]
    shift_range: float = SHIFT_RANGE
    feature_order: list[str] = field(default_factory=lambda: list(SHIFT_BLEND_COLUMNS))

    def _shift_array(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        team = _team_result(df).to_numpy()
        blend = (
            self.w_team * team
            + self.w_os * _os_shift(df).to_numpy()
            + self.w_impact * _indiv_mod(df).to_numpy()
        )
        shift = _clip(blend, -self.shift_range, self.shift_range)
        # Newcomers: pure team baseline (the blend's individual/os terms are noisy
        # with no history), clipped to the conservative newcomer range.
        newcomer = _newcomer_mask(df)
        shift = np.where(
            newcomer, _clip(team, -NEWCOMER_SHIFT_RANGE, NEWCOMER_SHIFT_RANGE), shift
        )
        return shift, newcomer

    def predict(self, df: pd.DataFrame) -> pd.Series:
        if df.empty:
            return pd.Series(dtype=float)
        shift, _ = self._shift_array(df)
        return pd.Series(shift, index=df.index, name="shift_v2")

    def predict_with_confidence(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=["shift_v2", "confidence"], dtype=float)
        shift, newcomer = self._shift_array(df)
        confidence = _linear_confidence(df).to_numpy()
        confidence = np.where(newcomer, confidence * 0.5, confidence)
        return pd.DataFrame(
            {"shift_v2": shift, "confidence": np.clip(confidence, 0.0, 1.0)},
            index=df.index,
        )


@dataclass
class ShiftTrainingResult:
    model: ShiftModelV2
    metrics: dict[str, float]
    feature_importance: dict[str, float]


def _fit_blend_weights(
    components: np.ndarray, realised: np.ndarray, *, min_samples: int = 30
) -> tuple[float, float, float]:
    """Fit convex blend weights via NNLS against realised division moves.

    Non-negative least squares finds the relative importance of
    ``[team_result, os_shift, indiv_mod]``; the coefficients are normalised to
    sum to 1 so the blend keeps ``team_result``'s scale (this is what prevents the
    collapse the old residual-toward-realised regression suffered). Falls back to
    :data:`DEFAULT_BLEND` on too little data or a degenerate fit.
    """
    from scipy.optimize import nnls

    X = np.asarray(components, dtype=float)
    y = np.asarray(realised, dtype=float)
    default = (DEFAULT_BLEND["team"], DEFAULT_BLEND["os"], DEFAULT_BLEND["impact"])
    if X.ndim != 2 or X.shape[1] != 3 or len(y) < min_samples:
        return default
    coef, _ = nnls(X, y)
    total = float(coef.sum())
    if not np.isfinite(total) or total <= 1e-9:
        return default
    w = coef / total
    return (float(w[0]), float(w[1]), float(w[2]))


def train_shift_v2(
    df: pd.DataFrame, *, val_df: pd.DataFrame | None = None
) -> ShiftTrainingResult:
    """Fit the blend weights from realised division moves.

    ``df`` must carry ``current_div`` and ``next_tournament_div`` (the realised
    move label) plus the blend component columns. Rows without the future label
    are dropped for the fit; the resulting model still scores everyone.
    """
    if df.empty:
        raise ValueError("training DataFrame is empty")
    label_cols = ("current_div", "next_tournament_div")
    if any(c not in df.columns for c in label_cols):
        raise ValueError(
            "no labelled rows for shift v2 (need current_div + next_tournament_div)"
        )
    labelled = df.dropna(subset=list(label_cols)).copy()
    if labelled.empty:
        raise ValueError(
            "no labelled rows for shift v2 (need current_div + next_tournament_div)"
        )

    realised = (
        labelled["current_div"].astype(float) - labelled["next_tournament_div"].astype(float)
    ).to_numpy()
    team = _team_result(labelled).to_numpy()
    os_ = _os_shift(labelled).to_numpy()
    indiv = _indiv_mod(labelled).to_numpy()
    components = np.column_stack([team, os_, indiv])

    w_team, w_os, w_impact = _fit_blend_weights(components, realised)
    model = ShiftModelV2(w_team=w_team, w_os=w_os, w_impact=w_impact)

    blend = components @ np.array([w_team, w_os, w_impact])
    blend = np.clip(blend, -SHIFT_RANGE, SHIFT_RANGE)
    mae = float(np.mean(np.abs(blend - realised)))
    metrics = {
        "n_rows": float(len(labelled)),
        "w_team": w_team,
        "w_os": w_os,
        "w_impact": w_impact,
        "mae_vs_realised": mae,
    }
    if val_df is not None and not val_df.empty:
        v = val_df.dropna(subset=["current_div", "next_tournament_div"])
        if not v.empty:
            vr = (v["current_div"].astype(float) - v["next_tournament_div"].astype(float)).to_numpy()
            vb = np.clip(
                np.column_stack([_team_result(v).to_numpy(), _os_shift(v).to_numpy(), _indiv_mod(v).to_numpy()])
                @ np.array([w_team, w_os, w_impact]),
                -SHIFT_RANGE,
                SHIFT_RANGE,
            )
            metrics["mae_vs_realised_val"] = float(np.mean(np.abs(vb - vr)))
            metrics["n_rows_val"] = float(len(v))

    return ShiftTrainingResult(
        model=model,
        metrics=metrics,
        feature_importance={"team": w_team, "os": w_os, "impact": w_impact},
    )
