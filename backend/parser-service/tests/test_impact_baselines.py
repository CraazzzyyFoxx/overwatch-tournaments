from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

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
