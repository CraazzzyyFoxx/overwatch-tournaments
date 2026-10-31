"""Pure, DB-free ``impact_v2`` baseline aggregation (design §4).

``build_baseline_rows`` turns segment-0 hero stints of many matches into baseline row dicts plus the badge threshold.
No ``AsyncSession``, ``await`` or ``asyncio`` — see ``backend/ARCHITECTURE.md``'s "domain/ boundary". Loading the
stints from the DB and atomically replacing a formula version's rows is IO and lives in
``shared.disciplines.overwatch.baselines.BaselineService``.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from shared.core.impact import (
    BADGE_PERCENTILE,
    BASELINE_MIN_MINUTES,
    EVENT_STATS,
    HERO_BASELINE_MIN_ROWS,
    IMPACT_FEATURES,
    RANK_QUINTILES,
)
from shared.disciplines.overwatch import impact

__all__ = ("build_baseline_rows",)


def build_baseline_rows(
    stints: pd.DataFrame,
    quintiles: Mapping[tuple[int, int], int],
    weights: impact.Weights,
) -> tuple[list[dict], float | None]:
    """Baseline rows (``role, hero, rank_bucket, stat, mean, std, n``) and the badge threshold.

    ``stints``: :func:`impact.build_stints` rows of segment 0 for many matches, plus ``match_id`` and ``killfeed``
    (bool, the match has a kill feed). ``quintiles``: ``(match_id, player_id) -> rank quintile`` of the player's
    dominant role. Feature rows aggregate stints of at least ``BASELINE_MIN_MINUTES``; event features only from
    kill-feed matches; a hero gets its own row for a feature once it has ``HERO_BASELINE_MIN_ROWS`` of them. The role
    scale, expectation and badge threshold are then computed with the formula itself over the player-maps with at
    least ``BASELINE_MIN_MINUTES`` of classed playtime. Sample std (``ddof=1``); a single row has std 0.
    """
    stints = stints[stints["segment"] == 0]
    classed = stints[stints["role"].notna()]
    base = classed[classed["seconds"] >= BASELINE_MIN_MINUTES * 60.0]
    if base.empty:
        return [], None
    rates = base[list(IMPACT_FEATURES)].div(base["seconds"], axis=0) * 600.0
    killfeed = base["killfeed"].to_numpy(dtype=bool)

    rows: list[dict] = []
    for role, frame in base.groupby("role", sort=True):
        for feature in IMPACT_FEATURES:
            rows.append(_row(role, None, -1, feature, _feature_series(rates, frame.index, feature, base, killfeed)))
    for hero, frame in base.groupby("hero", sort=True):
        role = str(frame["role"].iat[0])
        for feature in IMPACT_FEATURES:
            series = _feature_series(rates, frame.index, feature, base, killfeed)
            if len(series) >= HERO_BASELINE_MIN_ROWS:
                rows.append(_row(role, int(hero), -1, feature, series))

    _, _, raw = impact.feature_terms(base, impact.baseline_set(rows, None), weights)
    raw_by_role = pd.Series(raw, index=base.index).groupby(base["role"])
    for role, series in raw_by_role:
        rows.append(_row(str(role), None, -1, "ImpactPoints", series))

    keys = ["match_id", "segment"]
    players = impact.score_players(stints, impact.baseline_set(rows, None), weights, keys=keys)
    players = players[players["seconds"] >= BASELINE_MIN_MINUTES * 60.0]
    roles = impact.dominant_roles(stints, keys)
    players = players.assign(
        role=[roles.get(key) for key in players[[*keys, "player_id"]].itertuples(index=False, name=None)],
        quintile=[
            quintiles.get((int(m), int(p))) for m, p in zip(players["match_id"], players["player_id"], strict=True)
        ],
    )
    for role, frame in players[players["role"].notna()].groupby("role", sort=True):
        ranked = frame[frame["quintile"].notna()]
        rows.append(_row(str(role), None, -1, "OverperformanceScore", ranked["quality"]))
        for quintile in range(RANK_QUINTILES):
            cell = ranked[ranked["quintile"] == quintile]["quality"]
            rows.append(_row(str(role), None, quintile, "OverperformanceScore", cell))

    rated = stints.assign(
        rank_role=[roles.get(key) for key in stints[[*keys, "player_id"]].itertuples(index=False, name=None)],
        quintile=[
            quintiles.get((int(m), int(p)), np.nan)
            for m, p in zip(stints["match_id"], stints["player_id"], strict=True)
        ],
    )
    scored = impact.score_players(rated, impact.baseline_set(rows, None), weights, keys=keys)
    over = scored[scored["seconds"] >= BASELINE_MIN_MINUTES * 60.0]["OverperformanceScore"].dropna()
    threshold = float(np.percentile(over.to_numpy(), BADGE_PERCENTILE)) if len(over) else None
    return rows, threshold


def _feature_series(
    rates: pd.DataFrame, index: pd.Index, feature: str, base: pd.DataFrame, killfeed: np.ndarray
) -> pd.Series:
    series = rates.loc[index, feature]
    if feature in EVENT_STATS:
        series = series[killfeed[base.index.get_indexer(index)]]
    return series


def _row(role: str, hero: int | None, rank_bucket: int, stat: str, series: pd.Series) -> dict:
    values = series.to_numpy(dtype=np.float64)
    mean = float(values.mean()) if len(values) else 0.0
    std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    return {
        "role": role,
        "hero": hero,
        "rank_bucket": rank_bucket,
        "stat": stat,
        "mean": mean,
        "std": std,
        "n": int(len(values)),
    }
