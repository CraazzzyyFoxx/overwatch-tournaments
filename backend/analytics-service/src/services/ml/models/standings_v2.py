"""Standings v2 — pairwise win-probability + Monte Carlo bracket simulation.

Two stages:

**Stage A — Win-probability classifier.**

Trained on every historical encounter ``(home_team, away_team, won)`` with
features that capture pre-match team strength: avg/std rank gap, OpenSkill mu
gap, head-to-head winrate, days-since-last-meeting. Champion is XGBoost +
isotonic calibration; a Logistic Regression baseline is fitted alongside for
sanity.

**Stage B — Monte Carlo simulator.**

Given the upcoming encounters for a tournament, runs ``n_iter`` simulations
sampling each result from the calibrated ``P(home wins)`` distribution and
tallies the resulting final standings. Aggregates ``mean_position``,
``p10_position``, ``p90_position`` and ``prob_top{1,3,8}`` per team plus a
16-bin position histogram for the UI.

Outputs land in ``analytics.standings_distribution`` (Phase 3 runner) and
``AnalyticsPredictions.predicted_place`` is filled from ``round(mean_position)``
to keep v1 integer-place consumers working.
"""

from __future__ import annotations

import logging
import math
import typing
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..device import MLTrainDevice, xgboost_devices, xgboost_params
from .base import MLModel, align_features

__all__ = (
    "STANDINGS_FEATURE_ORDER",
    "WinProbabilityModel",
    "StandingsTrainingResult",
    "train_standings_v2",
    "simulate_standings",
)

logger = logging.getLogger(__name__)


# Feature order for the win-probability classifier.
#
# We INTENTIONALLY exclude ``home_avg_perf`` / ``away_avg_perf`` / ``perf_gap``
# from the model inputs: those are derived from Performance v2 of the SAME
# tournament being predicted (post-hoc residual from MatchStatistics) and
# therefore leak the very outcome we're trying to forecast. All remaining
# features are strictly pre-encounter (player ranks at registration time +
# OpenSkill mu snapshotted before each encounter).
STANDINGS_FEATURE_ORDER: tuple[str, ...] = (
    "home_avg_rank",
    "away_avg_rank",
    "rank_gap",
    "home_std_rank",
    "away_std_rank",
    "home_avg_mu",
    "away_avg_mu",
    "mu_gap",
    "h2h_winrate",
    "days_since_last_meet",
)


@dataclass
class WinProbabilityModel(MLModel):
    """Calibrated XGB classifier + LogisticRegression baseline for sanity checks."""

    booster: CalibratedClassifierCV
    baseline: typing.Any
    feature_order: list[str] = field(default_factory=lambda: list(STANDINGS_FEATURE_ORDER))

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if df.empty:
            return np.zeros(0, dtype=float)
        X = align_features(df, self.feature_order).fillna(0.0)
        # XGBoost refuses ``object`` dtype columns; ensure everything is float.
        X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0).astype(float)
        return self.booster.predict_proba(X)[:, 1]

    def predict(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(self.predict_proba(df), index=df.index, name="p_home_wins")


@dataclass
class StandingsTrainingResult:
    model: WinProbabilityModel
    metrics: dict[str, float]
    feature_importance: dict[str, float]


def _train_standings_v2_with_device(
    df: pd.DataFrame,
    *,
    val_df: pd.DataFrame | None = None,
    device: MLTrainDevice,
) -> StandingsTrainingResult:
    """Train the Stage-A win-probability classifier.

    ``df`` rows must contain feature columns from :data:`STANDINGS_FEATURE_ORDER`
    plus a ``home_won`` label (1 home wins, 0 home loses, 0.5 draws are dropped).
    """
    if df.empty:
        raise ValueError("training DataFrame is empty")

    labelled = df.dropna(subset=["home_won"]).copy()
    labelled = labelled[labelled["home_won"].isin([0.0, 1.0])]
    if labelled.empty:
        raise ValueError("no labelled encounters for standings v2")

    X = align_features(labelled, STANDINGS_FEATURE_ORDER).fillna(0.0)
    # Coerce any ``object``-dtype columns (e.g. ``Decimal`` from PG ``AVG``)
    # to float — XGBoost otherwise raises ``ValueError: DataFrame.dtypes
    # for data must be int, float, bool or category``.
    X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0).astype(float)
    y = labelled["home_won"].astype(int).to_numpy()

    base_xgb = xgb.XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        max_depth=5,
        n_estimators=400,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        verbosity=0,
        **xgboost_params(device),
    )
    # Limit CV folds to avoid failing on small validation sets.
    cv = min(5, max(2, len(set(y))))
    calibrated = CalibratedClassifierCV(estimator=base_xgb, method="isotonic", cv=cv)
    calibrated.fit(X, y)

    baseline = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=1000, C=1.0),
    )
    baseline.fit(X, y)

    yhat = calibrated.predict_proba(X)[:, 1]
    logloss = -float(
        np.mean(y * np.log(np.clip(yhat, 1e-9, 1 - 1e-9)) + (1 - y) * np.log(np.clip(1 - yhat, 1e-9, 1 - 1e-9)))
    )
    brier = float(np.mean((y - yhat) ** 2))
    metrics: dict[str, float] = {
        "logloss_train": logloss,
        "brier_train": brier,
        "n_rows": float(len(labelled)),
    }
    if val_df is not None and not val_df.empty:
        v = val_df.dropna(subset=["home_won"])
        v = v[v["home_won"].isin([0.0, 1.0])]
        if not v.empty:
            X_val = align_features(v, STANDINGS_FEATURE_ORDER).fillna(0.0)
            X_val = X_val.apply(pd.to_numeric, errors="coerce").fillna(0.0).astype(float)
            y_val = v["home_won"].astype(int).to_numpy()
            p_val = calibrated.predict_proba(X_val)[:, 1]
            metrics["logloss_val"] = -float(
                np.mean(
                    y_val * np.log(np.clip(p_val, 1e-9, 1 - 1e-9))
                    + (1 - y_val) * np.log(np.clip(1 - p_val, 1e-9, 1 - 1e-9))
                )
            )
            metrics["brier_val"] = float(np.mean((y_val - p_val) ** 2))
    for k, v in list(metrics.items()):
        if isinstance(v, float) and not math.isfinite(v):
            metrics[k] = 0.0

    # Feature importance from the underlying XGB (use first calibrator's booster).
    try:
        first_est = calibrated.calibrated_classifiers_[0].estimator
        importances = first_est.feature_importances_
    except Exception:  # pragma: no cover
        importances = [0.0] * len(STANDINGS_FEATURE_ORDER)
    feature_importance = {
        col: float(v) for col, v in zip(STANDINGS_FEATURE_ORDER, importances, strict=False)
    }

    model = WinProbabilityModel(booster=calibrated, baseline=baseline)
    return StandingsTrainingResult(
        model=model, metrics=metrics, feature_importance=feature_importance
    )


def train_standings_v2(
    df: pd.DataFrame,
    *,
    val_df: pd.DataFrame | None = None,
) -> StandingsTrainingResult:
    """Train Standings v2 with optional XGBoost CUDA fallback."""
    last_exc: Exception | None = None
    for device in xgboost_devices():
        try:
            result = _train_standings_v2_with_device(df, val_df=val_df, device=device)
            logger.info("Standings v2 trained device=%s", device)
            return result
        except Exception as exc:
            last_exc = exc
            if device == "cpu":
                raise
            logger.warning(
                "Standings v2 training failed on XGBoost device=%s; trying fallback if available: %s",
                device,
                exc,
            )
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("no XGBoost training devices configured")


# ---------------------------------------------------------------------------
# Stage B — Monte Carlo bracket simulation
# ---------------------------------------------------------------------------


def _round_robin_standings(
    team_ids: typing.Sequence[int],
    matches: typing.Sequence[tuple[int, int, float]],
    rng: np.random.Generator,
) -> dict[int, int]:
    """Return ``{team_id: position}`` from a list of ``(home, away, p_home)`` matchups.

    Sampling: each match is decided by ``rng.random() < p_home``. Standings
    are ranked by descending wins, ties broken randomly (stable per-call).
    """
    wins = dict.fromkeys(team_ids, 0)
    for home, away, p_home in matches:
        if home not in wins or away not in wins:
            continue
        if rng.random() < p_home:
            wins[home] = wins[home] + 1
        else:
            wins[away] = wins[away] + 1
    # Sort: more wins → better position; tie-break by deterministic shuffle.
    keys = list(wins.keys())
    rng.shuffle(keys)
    sorted_teams = sorted(keys, key=lambda tid: -wins[tid])
    return {tid: idx + 1 for idx, tid in enumerate(sorted_teams)}


def simulate_standings(
    matchups: pd.DataFrame,
    team_ids: typing.Sequence[int],
    *,
    n_iter: int = 5000,
    rng: np.random.Generator | None = None,
) -> pd.DataFrame:
    """Run the Monte Carlo simulator.

    ``matchups`` columns: ``home_team_id``, ``away_team_id``, ``p_home_wins``.
    Returns one row per team with ``mean_position``, ``median_position``,
    ``p10_position``, ``p90_position``, ``prob_top1``, ``prob_top3``,
    ``prob_top8``, and ``position_histogram`` (dict ``{position: count}``).
    """
    rng = rng or np.random.default_rng()
    team_ids = list({int(t) for t in team_ids})
    if not team_ids:
        return pd.DataFrame()
    if matchups.empty:
        # No matchups to simulate — all teams tied at position 1.
        return pd.DataFrame(
            {
                "team_id": team_ids,
                "mean_position": [1.0] * len(team_ids),
                "median_position": [1.0] * len(team_ids),
                "p10_position": [1.0] * len(team_ids),
                "p90_position": [1.0] * len(team_ids),
                "prob_top1": [1 / len(team_ids)] * len(team_ids),
                "prob_top3": [1 / len(team_ids)] * len(team_ids),
                "prob_top8": [1 / len(team_ids)] * len(team_ids),
                "position_histogram": [{str(1): n_iter}] * len(team_ids),
            }
        )

    triples = [
        (int(row.home_team_id), int(row.away_team_id), float(row.p_home_wins))
        for row in matchups.itertuples()
    ]

    n_teams = len(team_ids)
    positions = np.zeros((n_iter, n_teams), dtype=np.int16)
    team_index = {tid: idx for idx, tid in enumerate(team_ids)}

    for i in range(n_iter):
        standing = _round_robin_standings(team_ids, triples, rng)
        for tid, pos in standing.items():
            positions[i, team_index[tid]] = pos

    rows: list[dict[str, typing.Any]] = []
    for tid in team_ids:
        col = positions[:, team_index[tid]]
        hist: dict[str, int] = {}
        for pos, count in zip(*np.unique(col, return_counts=True), strict=False):
            hist[str(int(pos))] = int(count)
        rows.append(
            {
                "team_id": tid,
                "mean_position": float(col.mean()),
                "median_position": float(np.median(col)),
                "p10_position": float(np.percentile(col, 10)),
                "p90_position": float(np.percentile(col, 90)),
                "prob_top1": float((col <= 1).mean()),
                "prob_top3": float((col <= 3).mean()),
                "prob_top8": float((col <= 8).mean()),
                "position_histogram": hist,
            }
        )
    return pd.DataFrame(rows)
