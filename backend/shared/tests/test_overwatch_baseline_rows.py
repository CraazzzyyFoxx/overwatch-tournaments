from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shared.core.impact import (
    BASELINE_MIN_MINUTES,
    EVENT_STATS,
    HERO_BASELINE_MIN_ROWS,
    IMPACT_FEATURES,
    RANK_QUINTILES,
)
from shared.disciplines.overwatch.baseline_rows import build_baseline_rows
from shared.disciplines.overwatch.impact_weights import IMPACT_WEIGHTS


def _stints(n: int = 90, *, hero=lambda i: 1, killfeed=lambda i: True, seconds: float = 900.0) -> pd.DataFrame:
    """One damage stint per match (match i, player i), raw counts ~ N(10, 3) per ten minutes."""
    rng = np.random.default_rng(42)
    frame = pd.DataFrame(
        {
            "match_id": range(n),
            "player_id": range(n),
            "segment": 0,
            "hero": [hero(i) for i in range(n)],
            "role": "damage",
            "seconds": seconds,
            "killfeed": [killfeed(i) for i in range(n)],
        }
    )
    for feature in IMPACT_FEATURES:
        frame[feature] = rng.normal(10.0, 3.0, n).clip(min=0.0) * seconds / 600.0
    return frame


def _row(rows, stat, *, role="damage", hero=None, bucket=-1):
    return next(
        (r for r in rows if (r["role"], r["hero"], r["rank_bucket"], r["stat"]) == (role, hero, bucket, stat)), None
    )


def test_a_hero_gets_its_own_row_only_from_the_minimum_row_count():
    stints = _stints(2 * HERO_BASELINE_MIN_ROWS, hero=lambda i: 1 if i < HERO_BASELINE_MIN_ROWS else 2)
    rows, _ = build_baseline_rows(stints, {}, IMPACT_WEIGHTS)
    assert _row(rows, "Eliminations", hero=1)["n"] == HERO_BASELINE_MIN_ROWS
    assert _row(rows, "Eliminations", hero=2)["n"] == HERO_BASELINE_MIN_ROWS

    stints = _stints(2 * HERO_BASELINE_MIN_ROWS - 1, hero=lambda i: 1 if i < HERO_BASELINE_MIN_ROWS else 2)
    rows, _ = build_baseline_rows(stints, {}, IMPACT_WEIGHTS)
    assert _row(rows, "Eliminations", hero=1) is not None
    assert _row(rows, "Eliminations", hero=2) is None
    assert _row(rows, "Eliminations")["n"] == 2 * HERO_BASELINE_MIN_ROWS - 1  # the role row sees every stint


def test_event_features_use_only_killfeed_stints():
    stints = _stints(killfeed=lambda i: i % 2 == 0)
    odd = ~stints["killfeed"]
    stints.loc[stints["killfeed"], "FirstPicks"] = 7.5  # 5 per ten minutes
    stints.loc[odd, "FirstPicks"] = 150.0
    rows, _ = build_baseline_rows(stints, {}, IMPACT_WEIGHTS)
    first_picks = _row(rows, "FirstPicks")
    assert first_picks["mean"] == pytest.approx(5.0)
    assert first_picks["n"] == int(stints["killfeed"].sum())
    assert _row(rows, "Eliminations")["n"] == len(stints)  # non-event features take every stint


def test_a_stint_under_the_minimum_playtime_is_excluded():
    stints = _stints()
    short = stints.iloc[[0]].assign(
        match_id=1000, player_id=1000, seconds=BASELINE_MIN_MINUTES * 60.0 - 1.0, Eliminations=10_000.0
    )
    rows, _ = build_baseline_rows(pd.concat([stints, short], ignore_index=True), {}, IMPACT_WEIGHTS)
    reference, _ = build_baseline_rows(stints, {}, IMPACT_WEIGHTS)
    assert _row(rows, "Eliminations") == _row(reference, "Eliminations")


def test_role_scale_expectation_and_badge_threshold_rows():
    n = 100
    stints = _stints(n)
    quintiles = {(i, i): i % RANK_QUINTILES for i in range(n)}
    rows, threshold = build_baseline_rows(stints, quintiles, IMPACT_WEIGHTS)

    scale = _row(rows, "ImpactPoints")
    assert scale["n"] == n and scale["std"] > 0.0
    assert _row(rows, "OverperformanceScore") is not None  # the all-quintile fallback
    for quintile in range(RANK_QUINTILES):
        cell = _row(rows, "OverperformanceScore", bucket=quintile)
        assert cell["n"] == n // RANK_QUINTILES
    assert threshold is not None
    assert {r["role"] for r in rows} == {"damage"}


def test_without_quintiles_there_is_an_empty_expectation_and_no_threshold():
    rows, threshold = build_baseline_rows(_stints(), {}, IMPACT_WEIGHTS)
    assert _row(rows, "ImpactPoints") is not None
    assert _row(rows, "OverperformanceScore")["n"] == 0
    assert threshold is None


def test_no_qualifying_stint_yields_no_rows():
    rows, threshold = build_baseline_rows(_stints(seconds=60.0), {}, IMPACT_WEIGHTS)
    assert rows == [] and threshold is None


def test_features_are_the_event_stats_plus_raw_ones():
    rows, _ = build_baseline_rows(_stints(), {}, IMPACT_WEIGHTS)
    stats = {r["stat"] for r in rows if r["hero"] is None and r["rank_bucket"] == -1}
    assert set(IMPACT_FEATURES) <= stats
    assert set(EVENT_STATS) <= stats
