"""Feature-distribution drift monitoring.

For each numeric feature column in the training frame, compare the last 3
tournaments' distribution against the rest of the training set using
:func:`scipy.stats.wasserstein_distance`, **normalised by the baseline's own
scale**. Distances larger than ``threshold`` are flagged via the returned report
(the APScheduler hook in :mod:`src.scheduler` forwards flagged drifts to Sentry).

The normalisation matters: raw Wasserstein distance is expressed in the feature's
own units, so a fixed threshold is meaningless across features measured in SR
(thousands), damage (tens of thousands), and win rate (0..1): with the raw
distance every wide-range feature clears the threshold permanently. Dividing by
the baseline standard deviation makes the score dimensionless ("shifted by a
quarter of a standard deviation") and comparable across features.
"""

from __future__ import annotations

import logging
import typing

import numpy as np
import pandas as pd
from scipy.stats import wasserstein_distance

logger = logging.getLogger(__name__)

__all__ = ("compute_drift_report",)

# Below this baseline standard deviation a feature is treated as constant and
# skipped: normalising by it would turn rounding noise into infinite drift.
_MIN_SCALE = 1e-9


def compute_drift_report(
    df: pd.DataFrame,
    tournament_ids: typing.Sequence[int],
    *,
    threshold: float = 0.25,
    recent_window: int = 3,
) -> dict[str, typing.Any]:
    """Return ``{feature: scale-normalised distance}`` plus a flagged list.

    ``df`` must contain a ``tournament_id`` column; ``tournament_ids`` orders its
    tournaments chronologically (oldest first, as :func:`tournament_ids_up_to`
    returns them) — ids are not chronological, so the recent window cannot come
    from sorting them. Features compared are all numeric columns excluding
    identifiers. Each distance is expressed in baseline standard deviations, so
    ``threshold`` is unit-free; features whose baseline is effectively constant
    are omitted entirely rather than flagged.
    """
    if df.empty or "tournament_id" not in df.columns:
        return {"flags": [], "distances": {}, "threshold": threshold}

    present = set(df["tournament_id"].unique())
    ordered_ids = [tid for tid in tournament_ids if tid in present]
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
        scale = float(np.std(b))
        if not np.isfinite(scale) or scale <= _MIN_SCALE:
            # A (near-)constant baseline has no meaningful spread to normalise
            # against; any movement would divide by ~0 and flag spuriously.
            continue
        d /= scale
        if not np.isfinite(d):
            continue
        distances[col] = d

    flags = [col for col, d in distances.items() if d > threshold]
    return {"flags": flags, "distances": distances, "threshold": threshold}
