"""Performance Rating v2 — per-role LGBMRegressor with quantile confidence.

Replaces the v1 primitive
``avg(MatchStatistics.value WHERE name = PerformancePoints AND round = 0)``.

**Target construction**

1. A tiny baseline :class:`sklearn.linear_model.LogisticRegression` is fit on
   ``[team_avg_mu, opp_avg_mu, mu_gap]`` predicting ``team won this map``.
2. The supervised target for each ``(player, match)`` row becomes:
   ``y = won (0/1) - baseline_win_prob`` — the Glicko-style residual
   contribution above what pre-match ratings alone predicted.

**Model**

One :class:`lightgbm.LGBMRegressor` per role, ``objective='regression_l1'``
(MAE — robust against blowout maps), with two extra quantile boosters at
``q=0.1`` and ``q=0.9`` for confidence bands.

**Inference output**

For a given tournament the model emits one row per ``(player, tournament)``
with ``impact_score`` (0-100 percentile within the role cohort),
``raw_value`` (weighted mean of per-match ``y_hat`` weighted by
``hero_time_played``), ``confidence`` and ``log_coverage``.
"""

from __future__ import annotations

import logging
import math
import typing
from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..device import MLTrainDevice, lightgbm_devices, lightgbm_params
from ..features.role_kpis import COARSE_FEATURES, features_for_role
from .base import MLModel, align_features

__all__ = (
    "PerformanceModelV2",
    "PerformanceTrainingResult",
    "train_performance_v2",
    "build_target",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Target construction
# ---------------------------------------------------------------------------


_BASELINE_FEATURES: tuple[str, ...] = ("team_avg_mu", "opp_avg_mu", "mu_gap")


def _safe_baseline_features(df: pd.DataFrame) -> pd.DataFrame:
    """Slice baseline columns; fill NaN with column medians (NaN-tolerant baseline)."""
    out = pd.DataFrame(index=df.index)
    for col in _BASELINE_FEATURES:
        if col in df.columns:
            out[col] = df[col]
        else:
            out[col] = float("nan")
    return out.fillna(out.median(numeric_only=True)).fillna(0.0)


def _make_logistic_baseline() -> typing.Any:
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, C=1.0))


def build_target(df: pd.DataFrame) -> tuple[pd.Series, typing.Any]:
    """Fit the baseline and return ``(y_perf, baseline)``.

    ``y_perf`` ∈ [-1, 1] = observed map-win - baseline P(team wins | mu features).
    The baseline is returned so it can be saved alongside the LGBM booster.
    """
    if df.empty:
        return pd.Series(dtype=float), _make_logistic_baseline()

    X = _safe_baseline_features(df).to_numpy()
    y_win = df["won"].astype(int).to_numpy()

    baseline = _make_logistic_baseline()
    # When all labels are identical the LR fit is degenerate; fall back to a
    # constant predictor.
    if len(set(y_win)) < 2:
        baseline = _ConstantClassifier(prior=float(np.mean(y_win) if len(y_win) else 0.5))
    else:
        baseline.fit(X, y_win)

    baseline_p = baseline.predict_proba(X)[:, 1]
    y_perf = pd.Series(y_win - baseline_p, index=df.index, name="y_perf")
    return y_perf, baseline


class _ConstantClassifier:
    """Drop-in stand-in for LogisticRegression when only one class is observed."""

    classes_ = np.array([0, 1])

    def __init__(self, prior: float = 0.5) -> None:
        self.prior = float(np.clip(prior, 1e-6, 1 - 1e-6))

    def fit(self, X: np.ndarray, y: np.ndarray) -> _ConstantClassifier:  # pragma: no cover
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        p = np.full(len(X), self.prior, dtype=float)
        return np.column_stack([1 - p, p])


# ---------------------------------------------------------------------------
# Model wrapper
# ---------------------------------------------------------------------------


@dataclass
class PerformanceModelV2(MLModel):
    """Per-role Performance v2 estimator.

    Held by :class:`MLModelArtifact` rows with ``model_kind = 'performance'``.
    ``role`` is the role string used to look up features; coarse fallback is
    used when ``hero_time_played`` is zero (no logs).
    """

    role: str
    booster: lgb.LGBMRegressor
    booster_q10: lgb.LGBMRegressor
    booster_q90: lgb.LGBMRegressor
    feature_order: list[str]
    coarse_booster: lgb.LGBMRegressor | None = None
    coarse_feature_order: list[str] = field(default_factory=list)
    baseline: typing.Any = None  # LogisticRegression or _ConstantClassifier
    shift_range: float = 2.0  # divisor for the confidence band scaling

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def predict_match(self, df: pd.DataFrame) -> pd.DataFrame:
        """Predict per-(player, match) y_hat plus quantile bands.

        Returns a DataFrame with columns ``y_hat``, ``y_q10``, ``y_q90``,
        ``confidence`` indexed identically to ``df``.
        """
        out = pd.DataFrame(index=df.index)
        if df.empty:
            for col in ("y_hat", "y_q10", "y_q90", "confidence"):
                out[col] = []
            return out

        has_logs = (df.get("hero_time_played", pd.Series(0, index=df.index)).fillna(0) > 0)
        out["y_hat"] = float("nan")
        out["y_q10"] = float("nan")
        out["y_q90"] = float("nan")

        # Rows with logs → main booster + quantile pair.
        if has_logs.any():
            X = align_features(df[has_logs], self.feature_order)
            out.loc[has_logs, "y_hat"] = self.booster.predict(X)
            out.loc[has_logs, "y_q10"] = self.booster_q10.predict(X)
            out.loc[has_logs, "y_q90"] = self.booster_q90.predict(X)

        # Rows without logs → coarse fallback if available, else NaN.
        if (~has_logs).any() and self.coarse_booster is not None and self.coarse_feature_order:
            X_coarse = align_features(df[~has_logs], self.coarse_feature_order)
            out.loc[~has_logs, "y_hat"] = self.coarse_booster.predict(X_coarse)
            # No quantile bands trained for the coarse fallback → use main range.
            out.loc[~has_logs, "y_q10"] = out.loc[~has_logs, "y_hat"] - 0.25
            out.loc[~has_logs, "y_q90"] = out.loc[~has_logs, "y_hat"] + 0.25

        spread = (out["y_q90"] - out["y_q10"]).abs()
        out["confidence"] = (1 - (spread / (2 * self.shift_range)).clip(0, 1)).fillna(0.0)
        return out

    def predict(self, df: pd.DataFrame) -> pd.Series:
        """Protocol entry point — returns just the central ``y_hat`` series."""
        return self.predict_match(df)["y_hat"]


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


@dataclass
class PerformanceTrainingResult:
    """Container returned by :func:`train_performance_v2`."""

    role: str
    model: PerformanceModelV2
    metrics: dict[str, float]
    feature_importance: dict[str, float]


def _booster_params(
    *,
    objective: str,
    alpha: float | None = None,
    device: MLTrainDevice,
) -> dict[str, typing.Any]:
    params: dict[str, typing.Any] = {
        "objective": objective,
        "num_leaves": 63,
        "min_data_in_leaf": 50,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "n_estimators": 400,
        "verbose": -1,
        **lightgbm_params(device),
    }
    if alpha is not None:
        params["alpha"] = alpha
    return params


def _feature_importance(booster: lgb.LGBMRegressor, columns: typing.Sequence[str]) -> dict[str, float]:
    try:
        importances = booster.booster_.feature_importance(importance_type="gain")
    except Exception:  # pragma: no cover — defensive
        return dict.fromkeys(columns, 0.0)
    return {col: float(v) for col, v in zip(columns, importances, strict=False)}


def _train_performance_v2_with_device(
    df: pd.DataFrame,
    *,
    role: str,
    val_df: pd.DataFrame | None = None,
    device: MLTrainDevice,
) -> PerformanceTrainingResult:
    """Train Performance v2 for one role.

    ``df`` must contain at least ``role``, ``won``, ``hero_time_played``, the
    feature columns from :func:`features_for_role`, plus the baseline columns
    ``team_avg_mu``, ``opp_avg_mu``, ``mu_gap``.
    """
    if df.empty:
        raise ValueError("training DataFrame is empty")

    role_df = df[df["role"].str.lower() == role.lower()].copy()
    if role_df.empty:
        raise ValueError(f"no rows for role={role!r}")

    feature_order = list(features_for_role(role))

    # 1. baseline + residual target
    y, baseline = build_target(role_df)
    role_df["_y"] = y.values

    # 2. main booster (L1 regression on the residual)
    X = align_features(role_df, feature_order)
    main_params = _booster_params(objective="regression_l1", device=device)
    booster = lgb.LGBMRegressor(**main_params)
    fit_kwargs: dict[str, typing.Any] = {}
    if val_df is not None and not val_df.empty:
        val_role = val_df[val_df["role"].str.lower() == role.lower()].copy()
        if not val_role.empty:
            v_y, _ = build_target(val_role)
            val_role["_y"] = v_y.values
            X_val = align_features(val_role, feature_order)
            fit_kwargs["eval_set"] = [(X_val, val_role["_y"])]
            fit_kwargs["callbacks"] = [lgb.early_stopping(stopping_rounds=20, verbose=False)]
    booster.fit(X, role_df["_y"], **fit_kwargs)

    # 3. quantile boosters for confidence bands
    booster_q10 = lgb.LGBMRegressor(
        **_booster_params(objective="quantile", alpha=0.1, device=device)
    )
    booster_q90 = lgb.LGBMRegressor(
        **_booster_params(objective="quantile", alpha=0.9, device=device)
    )
    booster_q10.fit(X, role_df["_y"])
    booster_q90.fit(X, role_df["_y"])

    # 4. coarse fallback booster (no per-stat columns, just standings/mu)
    coarse_order = list(COARSE_FEATURES)
    coarse_booster: lgb.LGBMRegressor | None = None
    if all(col in role_df.columns for col in coarse_order):
        Xc = align_features(role_df, coarse_order)
        coarse_booster = lgb.LGBMRegressor(
            **_booster_params(objective="regression_l1", device=device)
        )
        coarse_booster.fit(Xc, role_df["_y"])

    # 5. metrics on training set (full backtest comes via training/backtest.py)
    yhat = booster.predict(X)
    residuals = role_df["_y"].to_numpy() - yhat
    mae = float(np.mean(np.abs(residuals)))
    ss_res = float(np.sum(residuals ** 2))
    var = float(np.var(role_df["_y"].to_numpy()))
    r2 = float(1 - ss_res / (len(role_df) * var)) if var > 0 else 0.0
    metrics = {"mae_train": mae, "r2_train": r2, "n_rows": float(len(role_df))}
    if not math.isfinite(metrics["r2_train"]):
        metrics["r2_train"] = 0.0

    importance = _feature_importance(booster, feature_order)

    model = PerformanceModelV2(
        role=role,
        booster=booster,
        booster_q10=booster_q10,
        booster_q90=booster_q90,
        feature_order=feature_order,
        coarse_booster=coarse_booster,
        coarse_feature_order=coarse_order if coarse_booster is not None else [],
        baseline=baseline,
    )
    return PerformanceTrainingResult(
        role=role, model=model, metrics=metrics, feature_importance=importance
    )


def train_performance_v2(
    df: pd.DataFrame,
    *,
    role: str,
    val_df: pd.DataFrame | None = None,
) -> PerformanceTrainingResult:
    """Train Performance v2 for one role with optional GPU fallback."""
    last_exc: Exception | None = None
    for device in lightgbm_devices():
        try:
            result = _train_performance_v2_with_device(
                df,
                role=role,
                val_df=val_df,
                device=device,
            )
            logger.info("Performance v2 trained role=%s device=%s", role, device)
            return result
        except Exception as exc:
            last_exc = exc
            if device == "cpu":
                raise
            logger.warning(
                "Performance v2 training failed on LightGBM device=%s; trying fallback if available: %s",
                device,
                exc,
            )
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("no LightGBM training devices configured")


# ---------------------------------------------------------------------------
# Match → Tournament aggregation (inference time)
# ---------------------------------------------------------------------------


def aggregate_to_tournament(
    match_df: pd.DataFrame, y_hat: pd.Series, y_q10: pd.Series, y_q90: pd.Series
) -> pd.DataFrame:
    """Weighted-mean roll-up of per-match predictions to per-(player, tournament).

    Returns DataFrame with columns:
    ``tournament_id``, ``player_id``, ``role``, ``raw_value``, ``confidence``,
    ``log_coverage``, ``match_count``. ``impact_score`` (0-100 percentile) is
    computed downstream after the role cohort is known.
    """
    if match_df.empty:
        return pd.DataFrame(
            columns=[
                "tournament_id",
                "player_id",
                "role",
                "raw_value",
                "confidence",
                "log_coverage",
                "match_count",
            ]
        )

    df = match_df.copy()
    df["_y_hat"] = y_hat.values
    df["_y_q10"] = y_q10.values
    df["_y_q90"] = y_q90.values
    df["_w"] = df["hero_time_played"].astype(float).fillna(0.0)

    rows: list[dict[str, typing.Any]] = []
    grouped = df.groupby(["tournament_id", "player_id"], dropna=False, sort=False)
    for (tournament_id, player_id), grp in grouped:
        weights = grp["_w"].to_numpy()
        weight_sum = float(weights.sum())
        values = grp["_y_hat"].to_numpy()
        mask = ~np.isnan(values)
        if mask.any() and weight_sum > 0:
            raw_value = float(
                np.average(values[mask], weights=np.where(weights[mask] > 0, weights[mask], 1.0))
            )
        elif mask.any():
            raw_value = float(np.nanmean(values))
        else:
            raw_value = 0.0
        q10 = float(np.nanmean(grp["_y_q10"]))
        q90 = float(np.nanmean(grp["_y_q90"]))
        spread = abs(q90 - q10)
        confidence = float(np.clip(1 - spread / 4.0, 0.0, 1.0))
        log_coverage = float((grp["hero_time_played"].fillna(0) > 0).mean())
        rows.append(
            {
                "tournament_id": int(tournament_id),
                "player_id": int(player_id),
                "role": grp["role"].iloc[0],
                "raw_value": raw_value,
                "confidence": confidence,
                "log_coverage": log_coverage,
                "match_count": int(len(grp)),
            }
        )
    return pd.DataFrame(rows)


def impact_score_within_role(per_player: pd.DataFrame) -> pd.Series:
    """Convert ``raw_value`` to ``impact_score`` 0-100 via per-(tournament, role) percentile."""
    if per_player.empty:
        return pd.Series(dtype=float)
    out = per_player.groupby(
        ["tournament_id", "role"], dropna=False
    )["raw_value"].rank(pct=True) * 100.0
    out.name = "impact_score"
    return out
