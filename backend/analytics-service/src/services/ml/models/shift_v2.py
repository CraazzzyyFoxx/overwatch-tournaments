"""Shift v2 — Linear baseline + OpenSkill/ML residual correction.

The v1 ``Linear`` algorithm is the conservative player-shift baseline.
Shift v2 keeps that baseline and uses OpenSkill, Performance v2, local
residuals, and sample-size features to learn a supervised residual correction:

    final_shift = linear_stable_shift + residual_pred

where the supervised target is ``current_div - next_tournament_div`` from the
historical ``Player.rank`` evolution. Positive shift means moving upward to a
lower division number, matching the legacy analytics convention. Confidence is
derived from quantile spread and Linear evidence.

Newcomers (no prior tournament) bypass the residual and return the clipped
baseline shift with halved confidence — the residual model has no signal on
them.
"""

from __future__ import annotations

import logging
import math
import typing
from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..device import MLTrainDevice, lightgbm_devices, lightgbm_params
from .base import MLModel, align_features

__all__ = (
    "ShiftModelV2",
    "ShiftTrainingResult",
    "build_merit_target",
    "build_residual_target",
    "train_shift_v2",
)

logger = logging.getLogger(__name__)


SHIFT_FEATURE_ORDER: tuple[str, ...] = (
    "os_shift",
    "linear_stable_shift",
    "linear_trend_shift",
    "linear_confidence",
    "linear_effective_evidence",
    "linear_sample_tournaments",
    "linear_sample_matches",
    "prior_div",
    "tournaments_played",
    "tournaments_at_current_div",
    "confidence_v1",
    "log_coverage",
    "match_count",
    "team_avg_mu",
    "opp_avg_mu",
    "mu_gap",
    "performance_v2_raw",  # filled from Performance v2 if available, else 0
    "performance_v2_confidence",
    "performance_v2_local_residual",
    "performance_v2_local_zscore",
    "performance_v2_local_percentile",
    "performance_v2_local_reference_n",
)


# Shift output is bounded to ±3 divisions to match v1 linear stable clamp.
SHIFT_RANGE: float = 3.0
NEWCOMER_SHIFT_RANGE: float = 1.5

# Merit calibration: divisions of suggested shift per 1 std-dev of context-adjusted
# individual over/under-performance. Default +2σ ≈ +1 division. Tunable from config.
MERIT_SHIFT_SCALE: float = 0.5


def _baseline_shift(df: pd.DataFrame) -> pd.Series:
    """Return the conservative baseline used before applying ML residuals."""
    fallback = pd.to_numeric(
        df.get("os_shift", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0.0)
    if "linear_stable_shift" not in df.columns:
        return fallback
    stable = pd.to_numeric(df["linear_stable_shift"], errors="coerce")
    return stable.where(stable.notna(), fallback).fillna(0.0)


def _linear_confidence(df: pd.DataFrame) -> pd.Series:
    if "linear_confidence" not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df["linear_confidence"], errors="coerce").fillna(0.0).clip(0.0, 1.0)


def build_merit_target(df: pd.DataFrame, *, merit_scale: float = MERIT_SHIFT_SCALE) -> pd.Series:
    """Context-adjusted individual merit shift, in division units.

    Built from Performance v2 ``local_zscore`` — the player's contribution to
    winning ABOVE what their team's and opponents' strength predicted (the v2
    target is ``won − baseline_win_prob`` fit over ``team/opp mu``), z-scored
    against the same-role + nearby-division cohort. So team strength enters as
    *context*, not as the signal: carrying a weak roster scores high, coasting on
    a stacked one scores ~0. Positive z (overperformed for the division) →
    positive shift (move up to a lower division number).

    Unlike the old ``current_div − next_tournament_div`` target, this is *dense*
    (every player who played has a perf row), so the residual learner no longer
    regresses toward the sparse "nobody actually moves" base rate and flattens
    confident signals to nil.
    """
    if df.empty:
        return pd.Series(dtype=float)
    z = pd.to_numeric(
        df.get("performance_v2_local_zscore", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0.0)
    return (merit_scale * z).clip(-SHIFT_RANGE, SHIFT_RANGE).rename("merit_target")


def build_residual_target(df: pd.DataFrame, *, merit_scale: float = MERIT_SHIFT_SCALE) -> pd.Series:
    """Return ``merit_target − baseline_shift`` for the residual learner.

    The supervised signal is the context-adjusted individual *merit* (see
    :func:`build_merit_target`), NOT the realised next-tournament division move:
    we recommend what a player's individual performance *deserves*, not whether an
    admin will actually move them (almost always "no" → collapse). Rows without a
    Performance v2 row (no merit label) are dropped by the caller via
    ``has_perf_v2``.
    """
    if df.empty:
        return pd.Series(dtype=float)
    merit = build_merit_target(df, merit_scale=merit_scale)
    return (merit - _baseline_shift(df)).rename("residual_target")


@dataclass
class ShiftModelV2(MLModel):
    """Hybrid Shift estimator: OpenSkill + LGBM residual + quantile bands."""

    booster: lgb.LGBMRegressor
    booster_q10: lgb.LGBMRegressor
    booster_q90: lgb.LGBMRegressor
    feature_order: list[str] = field(default_factory=lambda: list(SHIFT_FEATURE_ORDER))
    shift_range: float = SHIFT_RANGE

    def predict(self, df: pd.DataFrame) -> pd.Series:
        """Return the final ``shift_v2`` series; respects the newcomer rule."""
        if df.empty:
            return pd.Series(dtype=float)
        X = align_features(df, self.feature_order)
        residual = self.booster.predict(X)
        baseline = _baseline_shift(X).to_numpy()
        shift = np.clip(
            baseline + residual,
            -self.shift_range,
            self.shift_range,
        )

        # Newcomer rule: tournaments_played == 1 or is_newcomer True → pure OS.
        newcomer = (
            df.get("is_newcomer", pd.Series(False, index=df.index)).fillna(False).astype(bool)
            | (df["tournaments_played"].fillna(0) <= 1)
        ).to_numpy()
        shift = np.where(
            newcomer,
            np.clip(baseline, -NEWCOMER_SHIFT_RANGE, NEWCOMER_SHIFT_RANGE),
            shift,
        )
        return pd.Series(shift, index=df.index, name="shift_v2")

    def predict_with_confidence(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return ``shift_v2``, ``confidence`` (and quantile bands) per row."""
        if df.empty:
            return pd.DataFrame(
                columns=["shift_v2", "confidence", "q10", "q90"], dtype=float
        )
        X = align_features(df, self.feature_order)
        residual = self.booster.predict(X)
        baseline = _baseline_shift(X).to_numpy()
        q10 = np.clip(
            baseline + self.booster_q10.predict(X),
            -self.shift_range,
            self.shift_range,
        )
        q90 = np.clip(
            baseline + self.booster_q90.predict(X),
            -self.shift_range,
            self.shift_range,
        )
        shift = np.clip(
            baseline + residual,
            -self.shift_range,
            self.shift_range,
        )

        newcomer = (
            df.get("is_newcomer", pd.Series(False, index=df.index)).fillna(False).astype(bool)
            | (df["tournaments_played"].fillna(0) <= 1)
        ).to_numpy()
        newcomer_shift = np.clip(baseline, -NEWCOMER_SHIFT_RANGE, NEWCOMER_SHIFT_RANGE)
        shift = np.where(newcomer, newcomer_shift, shift)

        spread = np.abs(q90 - q10)
        quantile_confidence = np.clip(1 - spread / (2 * self.shift_range), 0.0, 1.0)
        confidence = 0.55 * quantile_confidence + 0.45 * _linear_confidence(X).to_numpy()
        baseline_sign = np.sign(baseline)
        shift_sign = np.sign(shift)
        disagrees_with_baseline = (
            (np.abs(baseline) >= 0.5)
            & (np.abs(shift) >= 0.5)
            & (baseline_sign != shift_sign)
        )
        confidence = np.where(disagrees_with_baseline, confidence * 0.65, confidence)
        # Newcomers — halved confidence.
        confidence = np.where(newcomer, confidence * 0.5, confidence)
        return pd.DataFrame(
            {
                "shift_v2": shift,
                "confidence": confidence,
                "q10": q10,
                "q90": q90,
            },
            index=df.index,
        )


@dataclass
class ShiftTrainingResult:
    model: ShiftModelV2
    metrics: dict[str, float]
    feature_importance: dict[str, float]


def _params(
    *,
    objective: str,
    alpha: float | None = None,
    device: MLTrainDevice,
) -> dict[str, typing.Any]:
    params: dict[str, typing.Any] = {
        "objective": objective,
        "num_leaves": 31,
        "min_data_in_leaf": 20,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "n_estimators": 300,
        "verbose": -1,
        **lightgbm_params(device),
    }
    if alpha is not None:
        params["alpha"] = alpha
    return params


def _has_perf_v2(df: pd.DataFrame) -> pd.Series:
    """Boolean mask of rows that carry a real Performance v2 merit label."""
    if "has_perf_v2" in df.columns:
        return df["has_perf_v2"].fillna(False).astype(bool)
    # Fallback for frames built before the flag existed: treat a present (and
    # non-zero, i.e. not the fillna sentinel) local_zscore as a real row.
    if "performance_v2_local_zscore" in df.columns:
        z = pd.to_numeric(df["performance_v2_local_zscore"], errors="coerce")
        return z.notna() & (z != 0.0)
    return pd.Series(False, index=df.index)


def _train_shift_v2_with_device(
    df: pd.DataFrame,
    *,
    val_df: pd.DataFrame | None = None,
    device: MLTrainDevice,
    merit_scale: float = MERIT_SHIFT_SCALE,
) -> ShiftTrainingResult:
    """Train the residual booster against the context-adjusted merit target.

    ``df`` must carry Performance v2 merit inputs (``has_perf_v2`` /
    ``performance_v2_local_zscore``); rows without a perf row are skipped."""
    if df.empty:
        raise ValueError("training DataFrame is empty")

    labelled = df[_has_perf_v2(df)].copy()
    if labelled.empty:
        raise ValueError(
            "no labelled rows for shift v2 training "
            f"(rows with Performance v2: {int(_has_perf_v2(df).sum())})"
        )

    target = build_residual_target(labelled, merit_scale=merit_scale)
    X = align_features(labelled, SHIFT_FEATURE_ORDER)

    booster = lgb.LGBMRegressor(**_params(objective="regression_l1", device=device))
    fit_kwargs: dict[str, typing.Any] = {}
    val_X: pd.DataFrame | None = None
    val_target: pd.Series | None = None
    if val_df is not None and not val_df.empty:
        val = val_df[_has_perf_v2(val_df)]
        if not val.empty:
            val_target = build_residual_target(val, merit_scale=merit_scale)
            val_X = align_features(val, SHIFT_FEATURE_ORDER)
            fit_kwargs["eval_set"] = [(val_X, val_target)]
            fit_kwargs["callbacks"] = [lgb.early_stopping(stopping_rounds=20, verbose=False)]
    booster.fit(X, target, **fit_kwargs)

    booster_q10 = lgb.LGBMRegressor(
        **_params(objective="quantile", alpha=0.1, device=device)
    )
    booster_q90 = lgb.LGBMRegressor(
        **_params(objective="quantile", alpha=0.9, device=device)
    )
    booster_q10.fit(X, target)
    booster_q90.fit(X, target)

    yhat = booster.predict(X)
    residuals = target.to_numpy() - yhat
    mae = float(np.mean(np.abs(residuals)))
    var = float(np.var(target.to_numpy()))
    r2 = float(1 - np.sum(residuals ** 2) / (len(labelled) * var)) if var > 0 else 0.0
    if not math.isfinite(r2):
        r2 = 0.0
    metrics = {"mae_train": mae, "r2_train": r2, "n_rows": float(len(labelled))}

    # Held-out metrics on the validation tournament (when present).
    if val_X is not None and val_target is not None and not val_target.empty:
        val_pred = booster.predict(val_X)
        val_resid = val_target.to_numpy() - val_pred
        val_mae = float(np.mean(np.abs(val_resid)))
        val_var = float(np.var(val_target.to_numpy()))
        val_r2 = (
            float(1 - np.sum(val_resid**2) / (len(val_target) * val_var))
            if val_var > 0
            else 0.0
        )
        metrics["mae_val"] = val_mae
        metrics["r2_val"] = val_r2 if math.isfinite(val_r2) else 0.0
        metrics["n_rows_val"] = float(len(val_target))

    try:
        importances = booster.booster_.feature_importance(importance_type="gain")
    except Exception:  # pragma: no cover
        importances = [0.0] * len(SHIFT_FEATURE_ORDER)
    feature_importance = {
        col: float(v) for col, v in zip(SHIFT_FEATURE_ORDER, importances, strict=False)
    }

    model = ShiftModelV2(
        booster=booster, booster_q10=booster_q10, booster_q90=booster_q90
    )
    return ShiftTrainingResult(
        model=model, metrics=metrics, feature_importance=feature_importance
    )


def train_shift_v2(
    df: pd.DataFrame,
    *,
    val_df: pd.DataFrame | None = None,
    merit_scale: float = MERIT_SHIFT_SCALE,
) -> ShiftTrainingResult:
    """Train Shift v2 with optional LightGBM GPU fallback."""
    last_exc: Exception | None = None
    for device in lightgbm_devices():
        try:
            result = _train_shift_v2_with_device(
                df, val_df=val_df, device=device, merit_scale=merit_scale
            )
            logger.info("Shift v2 trained device=%s", device)
            return result
        except Exception as exc:
            last_exc = exc
            if device == "cpu":
                raise
            logger.warning(
                "Shift v2 training failed on LightGBM device=%s; trying fallback if available: %s",
                device,
                exc,
            )
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("no LightGBM training devices configured")
