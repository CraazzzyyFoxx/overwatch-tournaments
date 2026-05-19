"""Feature-distribution drift monitoring.

For each numeric feature column in the training frame, compute the
:func:`scipy.stats.wasserstein_distance` between the last 3 tournaments'
distribution and the rest of the training set. Distances larger than
``threshold`` are flagged via the returned report (the APScheduler hook in
:mod:`src.scheduler` forwards flagged drifts to Sentry).
"""

from __future__ import annotations

import logging
import typing

import numpy as np
import pandas as pd
from scipy.stats import wasserstein_distance

logger = logging.getLogger(__name__)

__all__ = ("compute_drift_report",)


def compute_drift_report(
    df: pd.DataFrame,
    *,
    threshold: float = 0.25,
    recent_window: int = 3,
) -> dict[str, typing.Any]:
    """Return ``{feature: wasserstein_distance}`` plus a flagged list.

    ``df`` must contain a ``tournament_id`` column. Features compared are all
    numeric columns excluding identifiers.
    """
    if df.empty or "tournament_id" not in df.columns:
        return {"flags": [], "distances": {}, "threshold": threshold}

    ordered_ids = sorted(df["tournament_id"].unique())
    if len(ordered_ids) <= recent_window:
        return {"flags": [], "distances": {}, "threshold": threshold}

    recent_ids = ordered_ids[-recent_window:]
    recent = df[df["tournament_id"].isin(recent_ids)]
    baseline = df[~df["tournament_id"].isin(recent_ids)]

    identifier_cols = {
        "tournament_id",
        "player_id",
        "user_id",
        "team_id",
        "encounter_id",
        "match_id",
        "home_team_id",
        "away_team_id",
        "opp_team_id",
        "hero_id",
        "map_id",
    }
    distances: dict[str, float] = {}
    for col in df.select_dtypes(include="number").columns:
        if col in identifier_cols:
            continue
        a = recent[col].dropna().to_numpy()
        b = baseline[col].dropna().to_numpy()
        if len(a) < 5 or len(b) < 5:
            continue
        try:
            d = float(wasserstein_distance(a, b))
        except Exception:  # pragma: no cover
            continue
        if not np.isfinite(d):
            continue
        distances[col] = d

    flags = [col for col, d in distances.items() if d > threshold]
    return {"flags": flags, "distances": distances, "threshold": threshold}
