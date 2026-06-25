"""Shift v2 ("OpenSkill + ML") — team-result backbone + additive individual skill.

Prod analysis showed the **team result** (W/L vs the balanced seeding) is by far
the strongest predictor of realised division moves. So the backbone is a
team-dominant convex mix of the v1 team-result Linear shift and the OpenSkill mu
shift. On top of it an **additive individual skill term** lifts players whose
Performance v2 ``local_zscore`` (skill vs same role + nearby division) is far
from their cohort — so a clear individual outlier moves even when the team result
doesn't capture it, instead of being averaged away:

    shift_v2 = clamp( w_team·team_result + w_os·os_shift
                      + clip(indiv_scale·local_zscore, ±indiv_clamp) , ±3 )

There is no learned regression toward the (mostly-zero) realised move — that
collapsed the signal. Weights/scales are fixed (config-tunable) and snapshotted
into the artifact at train time. Newcomers (no prior tournament) get the clipped
team backbone only (no individual term — one tournament is too noisy).
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

# Output bounds (match the v1 linear stable clamp).
SHIFT_RANGE: float = 3.0
NEWCOMER_SHIFT_RANGE: float = 1.5

# Blend defaults (team-dominant backbone; additive individual skill term).
BLEND_W_TEAM: float = 0.7
BLEND_W_OS: float = 0.3
INDIV_MOD_SCALE: float = 0.5   # divisions per std-dev of individual skill
INDIV_MOD_CLAMP: float = 1.5   # max |individual skill modifier| in divisions

# Columns the blend reads (for MLModel/feature introspection).
SHIFT_BLEND_COLUMNS: tuple[str, ...] = (
    "linear_stable_shift",
    "os_shift",
    "performance_v2_local_zscore",
)


def _team_result(df: pd.DataFrame) -> pd.Series:
    """Team-result backbone component: v1 Linear ``stable_shift`` (fallback os_shift)."""
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


def _indiv_mod(df: pd.DataFrame, *, scale: float, clamp: float) -> pd.Series:
    """Additive individual-skill modifier from Performance v2 local z-score.

    ``local_zscore`` is the player's skill vs the same role + nearby division
    cohort (not all players). Scaled to divisions and clamped to ±``clamp`` so a
    strong outlier moves meaningfully but cannot run away. Zero where Performance
    v2 is absent.
    """
    z = pd.to_numeric(
        df.get("performance_v2_local_zscore", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0.0)
    return (scale * z).clip(-clamp, clamp)


def _linear_confidence(df: pd.DataFrame) -> pd.Series:
    if "linear_confidence" not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df["linear_confidence"], errors="coerce").fillna(0.0).clip(0.0, 1.0)


def _newcomer_mask(df: pd.DataFrame) -> np.ndarray:
    is_newcomer = df.get("is_newcomer", pd.Series(False, index=df.index))
    played = pd.to_numeric(
        df.get("tournaments_played", pd.Series(0, index=df.index)), errors="coerce"
    ).fillna(0)
    return (is_newcomer.fillna(False).astype(bool) | (played <= 1)).to_numpy()


@dataclass
class ShiftModelV2(MLModel):
    """Team-result backbone + additive individual-skill modifier (no regression)."""

    w_team: float = BLEND_W_TEAM
    w_os: float = BLEND_W_OS
    indiv_scale: float = INDIV_MOD_SCALE
    indiv_clamp: float = INDIV_MOD_CLAMP
    shift_range: float = SHIFT_RANGE
    feature_order: list[str] = field(default_factory=lambda: list(SHIFT_BLEND_COLUMNS))

    def _shift_array(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        backbone = (
            self.w_team * _team_result(df).to_numpy()
            + self.w_os * _os_shift(df).to_numpy()
        )
        indiv = _indiv_mod(df, scale=self.indiv_scale, clamp=self.indiv_clamp).to_numpy()
        shift = np.clip(backbone + indiv, -self.shift_range, self.shift_range)
        # Newcomers: team backbone only (one tournament of individual signal is
        # too noisy), clipped to the conservative newcomer range.
        newcomer = _newcomer_mask(df)
        shift = np.where(
            newcomer,
            np.clip(backbone, -NEWCOMER_SHIFT_RANGE, NEWCOMER_SHIFT_RANGE),
            shift,
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


def train_shift_v2(
    df: pd.DataFrame,
    *,
    val_df: pd.DataFrame | None = None,
    w_team: float = BLEND_W_TEAM,
    w_os: float = BLEND_W_OS,
    indiv_scale: float = INDIV_MOD_SCALE,
    indiv_clamp: float = INDIV_MOD_CLAMP,
) -> ShiftTrainingResult:
    """Snapshot the (config-tunable) blend weights into a model artifact.

    There is no learned fit — the data showed regressing the sparse realised move
    collapses the signal and an NNLS fit drifted to an unstable os-heavy solution.
    Weights/scales come from config; this just builds the model and reports a
    diagnostic MAE of the blend vs the realised move on any labelled rows.
    """
    if df.empty:
        raise ValueError("training DataFrame is empty")
    model = ShiftModelV2(
        w_team=w_team, w_os=w_os, indiv_scale=indiv_scale, indiv_clamp=indiv_clamp
    )

    metrics: dict[str, float] = {
        "n_rows": float(len(df)),
        "w_team": w_team,
        "w_os": w_os,
        "indiv_scale": indiv_scale,
        "indiv_clamp": indiv_clamp,
    }

    def _mae_vs_realised(frame: pd.DataFrame) -> tuple[float, int] | None:
        if any(c not in frame.columns for c in ("current_div", "next_tournament_div")):
            return None
        labelled = frame.dropna(subset=["current_div", "next_tournament_div"])
        if labelled.empty:
            return None
        realised = (
            labelled["current_div"].astype(float)
            - labelled["next_tournament_div"].astype(float)
        ).to_numpy()
        pred = model.predict(labelled).to_numpy()
        return float(np.mean(np.abs(pred - realised))), int(len(labelled))

    train_mae = _mae_vs_realised(df)
    if train_mae is not None:
        metrics["mae_vs_realised"], metrics["n_labelled"] = train_mae[0], float(train_mae[1])
    if val_df is not None and not val_df.empty:
        val_mae = _mae_vs_realised(val_df)
        if val_mae is not None:
            metrics["mae_vs_realised_val"], metrics["n_rows_val"] = (
                val_mae[0],
                float(val_mae[1]),
            )

    return ShiftTrainingResult(
        model=model,
        metrics=metrics,
        feature_importance={"team": w_team, "os": w_os, "indiv": indiv_scale},
    )
