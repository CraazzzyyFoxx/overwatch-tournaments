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


def build_residual_target(df: pd.DataFrame) -> pd.Series:
    """Return ``realised_shift - baseline_shift`` for rows with future div labels.

    ``realised_shift`` follows the legacy sign convention:
    ``current_div - next_tournament_div``. Rows lacking the label are dropped
    by the caller before training.
    """
    if df.empty:
        return pd.Series(dtype=float)
    realised = (df["current_div"] - df["next_tournament_div"]).astype(float)
    return (realised - _baseline_shift(df)).rename("residual_target")


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


def _train_shift_v2_with_device(
    df: pd.DataFrame,
    *,
    val_df: pd.DataFrame | None = None,
    device: MLTrainDevice,
) -> ShiftTrainingResult:
    """Train the residual booster. ``df`` must contain a
    ``next_tournament_div`` column for supervised rows."""
    if df.empty:
        raise ValueError("training DataFrame is empty")

    labelled = df.dropna(subset=["next_tournament_div", "current_div", "os_shift"]).copy()
    if labelled.empty:
        non_null_counts = {
            column: int(df[column].notna().sum()) if column in df.columns else 0
            for column in ("next_tournament_div", "current_div", "os_shift")
        }
        raise ValueError(
            "no labelled rows for shift v2 training "
            f"(non-null counts: {non_null_counts})"
        )

    target = build_residual_target(labelled)
    X = align_features(labelled, SHIFT_FEATURE_ORDER)

    booster = lgb.LGBMRegressor(**_params(objective="regression_l1", device=device))
    fit_kwargs: dict[str, typing.Any] = {}
    val_X: pd.DataFrame | None = None
    val_target: pd.Series | None = None
    if val_df is not None and not val_df.empty:
        val = val_df.dropna(subset=["next_tournament_div", "current_div", "os_shift"])
        if not val.empty:
            val_target = build_residual_target(val)
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


def train_shift_v2(df: pd.DataFrame, *, val_df: pd.DataFrame | None = None) -> ShiftTrainingResult:
    """Train Shift v2 with optional LightGBM GPU fallback."""
    last_exc: Exception | None = None
    for device in lightgbm_devices():
        try:
            result = _train_shift_v2_with_device(df, val_df=val_df, device=device)
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
