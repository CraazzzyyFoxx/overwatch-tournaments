from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.core import enums  # noqa: E402
from src.services.match_logs import backfill  # noqa: E402


def _stat_rows():
    return pd.DataFrame(
        [
            # round rows (hero NULL)
            {"user_id": 10, "round": 1, "hero_id": None, "name": enums.LogStatsName.Eliminations, "value": 5.0},
            {"user_id": 10, "round": 1, "hero_id": None, "name": enums.LogStatsName.HeroTimePlayed, "value": 300.0},
            # match totals
            {"user_id": 10, "round": 0, "hero_id": None, "name": enums.LogStatsName.Eliminations, "value": 5.0},
            {"user_id": 10, "round": 0, "hero_id": None, "name": enums.LogStatsName.HeroTimePlayed, "value": 300.0},
            # per-hero row must be ignored by pivots
            {"user_id": 10, "round": 0, "hero_id": 3, "name": enums.LogStatsName.Eliminations, "value": 5.0},
        ]
    )


def test_rebuild_frames_pivots_round_and_match():
    round_df, match_df = backfill.rebuild_frames(_stat_rows())
    assert list(round_df["round"].unique()) == [1]
    assert round_df[enums.LogStatsName.Eliminations].iloc[0] == 5.0
    assert match_df["round"].iloc[0] == 0
    assert match_df[enums.LogStatsName.HeroTimePlayed].iloc[0] == 300.0


def test_rebuild_frames_drops_already_derived_new_stats():
    rows = _stat_rows()
    rows = pd.concat(
        [
            rows,
            pd.DataFrame(
                [{"user_id": 10, "round": 0, "hero_id": None, "name": enums.LogStatsName.ImpactPoints, "value": 9.9}]
            ),
        ],
        ignore_index=True,
    )
    _, match_df = backfill.rebuild_frames(rows)
    assert enums.LogStatsName.ImpactPoints not in match_df.columns
