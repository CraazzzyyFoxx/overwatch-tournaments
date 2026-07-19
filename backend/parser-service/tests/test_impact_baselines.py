from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.core.impact import IMPACT_WEIGHTS  # noqa: E402
from src.services.baselines import flows  # noqa: E402


def _stats_frame(n=90):
    rng = np.random.default_rng(42)
    df = pd.DataFrame(
        {
            "role": ["damage"] * n,
            "rank": np.concatenate(
                [
                    rng.integers(100, 400, n // 3),
                    rng.integers(600, 900, n // 3),
                    rng.integers(1200, 2000, n - 2 * (n // 3)),
                ]
            ),
            "minutes": 15.0,
            "has_killfeed": [True] * (n // 2) + [False] * (n - n // 2),
        }
    )
    for stat in IMPACT_WEIGHTS:
        df[f"{stat}_rate"] = rng.normal(10.0, 3.0, n)
    return df


def _frame_with_elimination_rates(ranks, elimination_rates, has_killfeed=True):
    """Small deterministic frame: one role ("damage"), given ranks/rates.

    All other ``IMPACT_WEIGHTS`` stats get a constant filler rate — only
    ``Eliminations_rate`` (not an ``EVENT_STATS`` member, so it is never
    killfeed-filtered) carries the values under test.
    """
    n = len(ranks)
    df = pd.DataFrame(
        {
            "role": ["damage"] * n,
            "rank": ranks,
            "minutes": [15.0] * n,
            "has_killfeed": [has_killfeed] * n,
        }
    )
    for stat in IMPACT_WEIGHTS:
        df[f"{stat}_rate"] = 5.0
    df["Eliminations_rate"] = elimination_rates
    return df


def test_rows_cover_all_buckets_and_role_wide():
    rows = flows.build_baseline_rows(_stats_frame())
    buckets = {(r["role"], r["rank_bucket"]) for r in rows}
    assert ("damage", -1) in buckets
    assert {("damage", 0), ("damage", 1), ("damage", 2)} <= buckets


def test_event_stats_use_only_killfeed_rows():
    df = _stats_frame()
    df.loc[df.has_killfeed, "FirstPicks_rate"] = 5.0
    df.loc[~df.has_killfeed, "FirstPicks_rate"] = 100.0  # must be ignored
    rows = flows.build_baseline_rows(df)
    fp = next(r for r in rows if r["stat"] == "FirstPicks" and r["rank_bucket"] == -1)
    assert fp["mean"] == 5.0


def test_short_playtime_rows_excluded():
    df = _stats_frame()
    df["Eliminations_rate"] = 10.0
    extra = df.iloc[[0]].copy()
    extra["minutes"] = 1.0
    extra["Eliminations_rate"] = 10_000.0
    rows = flows.build_baseline_rows(pd.concat([df, extra], ignore_index=True))
    el = next(r for r in rows if r["stat"] == "Eliminations" and r["rank_bucket"] == -1)
    assert el["mean"] == 10.0


def test_bucket_bounds_frozen_in_meta():
    rows = flows.build_baseline_rows(_stats_frame())
    bounds = rows[0]["meta"]["bucket_bounds"]
    assert len(bounds) == 2 and bounds[0] < bounds[1]


def test_std_is_sample_stdev_ddof1():
    """bucket=-1 (role-wide) aggregates every row for the role, so with a
    known-constant rate series the emitted mean/std must match the ddof=1
    (sample) stdev formula exactly — not population stdev (ddof=0)."""
    rates = [8.0, 10.0, 12.0]
    df = _frame_with_elimination_rates(ranks=[100, 700, 1500], elimination_rates=rates)

    rows = flows.build_baseline_rows(df)
    row = next(r for r in rows if r["stat"] == "Eliminations" and r["rank_bucket"] == -1)

    expected_mean = sum(rates) / len(rates)  # 10.0
    variance_ddof1 = sum((x - expected_mean) ** 2 for x in rates) / (len(rates) - 1)  # (4+0+4)/2 = 4.0
    expected_std = variance_ddof1**0.5  # 2.0

    assert expected_mean == pytest.approx(10.0)
    assert expected_std == pytest.approx(2.0)
    assert row["mean"] == pytest.approx(expected_mean)
    assert row["std"] == pytest.approx(expected_std)


def test_single_row_bucket_std_is_zero_not_nan():
    """Ranks [100, 500, 1500] split into exactly one row per tercile bucket
    (verified via numpy.quantile below), so bucket 0's sample variance is
    undefined (n=1). The NaN guard must emit 0.0, never NaN."""
    ranks = [100, 500, 1500]
    bucket_bounds = np.quantile(np.array(ranks, dtype=float), [1 / 3, 2 / 3])
    assert ranks[0] <= bucket_bounds[0] < ranks[1] <= bucket_bounds[1] < ranks[2]

    df = _frame_with_elimination_rates(ranks=ranks, elimination_rates=[8.0, 10.0, 12.0])
    rows = flows.build_baseline_rows(df)
    bucket0 = next(r for r in rows if r["stat"] == "Eliminations" and r["rank_bucket"] == 0)

    assert bucket0["mean"] == pytest.approx(8.0)
    assert bucket0["std"] == 0.0
    assert not pd.isna(bucket0["std"])
