from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

import pandas as pd

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ["DEBUG"] = "false"
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

mvp = importlib.import_module("src.services.ml.features.mvp_dominance")


class DominanceFromPerfRanksTests(TestCase):
    def test_normalises_rank_to_dominance(self) -> None:
        # Two 4-player matches; each player keeps the same rank in both.
        df = pd.DataFrame(
            {
                "match_id": [1, 1, 1, 1, 2, 2, 2, 2],
                "player_id": [10, 11, 12, 13, 10, 11, 12, 13],
                "perf_rank": [1, 2, 3, 4, 1, 2, 3, 4],
            }
        )
        out = mvp.dominance_from_perf_ranks(df).set_index("player_id")
        # rank 1 → (4-1)/(4-1)=1.0 ; rank 2 → 2/3 ; rank 4 → 0.0
        self.assertAlmostEqual(1.0, float(out.loc[10, "mvp_dominance"]), places=6)
        self.assertAlmostEqual(2 / 3, float(out.loc[11, "mvp_dominance"]), places=6)
        self.assertAlmostEqual(0.0, float(out.loc[13, "mvp_dominance"]), places=6)
        self.assertEqual(2, int(out.loc[10, "mvp_matches"]))

    def test_averages_across_matches(self) -> None:
        # Player 10 is MVP (rank 1) then last (rank 4) → mean of 1.0 and 0.0 = 0.5.
        df = pd.DataFrame(
            {
                "match_id": [1, 1, 1, 1, 2, 2, 2, 2],
                "player_id": [10, 11, 12, 13, 10, 11, 12, 13],
                "perf_rank": [1, 2, 3, 4, 4, 3, 2, 1],
            }
        )
        out = mvp.dominance_from_perf_ranks(df).set_index("player_id")
        self.assertAlmostEqual(0.5, float(out.loc[10, "mvp_dominance"]), places=6)

    def test_empty_frame_returns_empty(self) -> None:
        out = mvp.dominance_from_perf_ranks(pd.DataFrame())
        self.assertTrue(out.empty)
        self.assertEqual(["player_id", "mvp_dominance", "mvp_matches"], list(out.columns))
