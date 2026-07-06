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
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

local_performance = importlib.import_module("src.services.ml.features.local_performance")
extractors = importlib.import_module("src.services.ml.features.extractors")
anomalies = importlib.import_module("src.services.ml.models.anomalies")


class LocalPerformanceTests(TestCase):
    def test_attaches_nearby_division_baseline(self) -> None:
        frame = pd.DataFrame(
            {
                "tournament_id": [7] * 6,
                "player_id": [1, 2, 3, 4, 5, 6],
                "role": ["Damage"] * 6,
                "division": [3, 3, 4, 4, 5, 5],
                "raw_value": [-0.2, -0.1, 0.0, 0.1, 0.2, 0.9],
            }
        )

        result = local_performance.attach_local_performance(
            frame,
            initial_radius=1,
            max_radius=2,
            min_reference_n=2,
            prior_strength=0.0,
        )

        standout = result[result["player_id"] == 6].iloc[0]
        self.assertGreater(standout["local_residual"], 0)
        self.assertGreater(standout["local_zscore"], 0)
        self.assertEqual(3, standout["local_reference_n"])
        self.assertGreaterEqual(standout["local_percentile"], 80.0)


class PlayerAnomalyTests(TestCase):
    def test_smurf_uses_deterministic_review_rule_for_small_role_groups(self) -> None:
        frame = pd.DataFrame(
            {
                "player_id": [1, 2, 3, 4],
                "role": ["Damage"] * 4,
                "rank": [1100, 1200, 1000, 500],
                "impact_score": [55.0, 50.0, 60.0, 95.0],
                "local_zscore": [0.0, -0.1, 0.2, 1.1],
                "local_percentile": [50.0, 45.0, 55.0, 86.0],
                "kd": [1.0, 1.1, 1.0, 2.1],
                "weapon_accuracy": [30.0, 31.0, 28.0, 45.0],
                "final_blows_p10": [4.0, 4.5, 4.2, 8.0],
            }
        )

        flags = anomalies.detect_smurfs(frame)

        self.assertEqual(["smurf"], [flag["kind"] for flag in flags])
        self.assertEqual(4, flags[0]["player_id"])
        self.assertEqual("review", flags[0]["evidence"]["severity"])

    def test_smurf_ignores_borderline_local_overperformance(self) -> None:
        frame = pd.DataFrame(
            {
                "player_id": [1, 2, 3, 4],
                "role": ["Damage"] * 4,
                "rank": [1100, 1200, 1000, 500],
                "impact_score": [55.0, 50.0, 60.0, 95.0],
                "local_zscore": [0.0, -0.1, 0.2, 0.8],
                "local_percentile": [50.0, 45.0, 55.0, 76.0],
                "kd": [1.0, 1.1, 1.0, 2.1],
                "weapon_accuracy": [30.0, 31.0, 28.0, 45.0],
                "final_blows_p10": [4.0, 4.5, 4.2, 8.0],
            }
        )

        flags = anomalies.detect_smurfs(frame)

        self.assertEqual([], flags)

    def test_smurf_flags_strong_cohort_outlier_regardless_of_rank(self) -> None:
        # Player 4 has the HIGHEST rank (fails the low-rank gate) but is far above
        # their role+division cohort (local_zscore 1.8) — must still be surfaced.
        frame = pd.DataFrame(
            {
                "player_id": [1, 2, 3, 4],
                "role": ["Damage"] * 4,
                "rank": [1100, 1200, 1000, 1300],
                "impact_score": [55.0, 50.0, 60.0, 65.0],
                "local_zscore": [0.0, -0.1, 0.2, 1.8],
                "local_percentile": [50.0, 45.0, 55.0, 92.0],
                "kd": [1.0, 1.1, 1.0, 1.6],
                "weapon_accuracy": [30.0, 31.0, 28.0, 39.0],
                "final_blows_p10": [4.0, 4.5, 4.2, 6.0],
            }
        )

        flags = anomalies.detect_smurfs(frame)

        smurf = next(f for f in flags if f["player_id"] == 4)
        self.assertEqual("smurf", smurf["kind"])
        self.assertIn("strong_cohort_outlier", smurf["reasons"])
        # The low-rank gate is NOT claimed as a reason here.
        self.assertNotIn("low_rank", smurf["reasons"])

    def test_smurf_strong_outlier_threshold_is_respected(self) -> None:
        # local_zscore below strong_local_z_threshold and not a classic smurf → no flag.
        frame = pd.DataFrame(
            {
                "player_id": [1, 2, 3, 4],
                "role": ["Damage"] * 4,
                "rank": [1100, 1200, 1000, 1300],
                "impact_score": [55.0, 50.0, 60.0, 65.0],
                "local_zscore": [0.0, -0.1, 0.2, 1.3],
                "local_percentile": [50.0, 45.0, 55.0, 88.0],
                "kd": [1.0, 1.1, 1.0, 1.6],
                "weapon_accuracy": [30.0, 31.0, 28.0, 39.0],
                "final_blows_p10": [4.0, 4.5, 4.2, 6.0],
            }
        )

        self.assertEqual([], anomalies.detect_smurfs(frame))

    def test_smurf_flags_raw_scoreboard_dominator(self) -> None:
        # Player 4: mid local_z / impact (neither classic smurf nor strong cohort
        # outlier) but consistently tops the raw match scoreboard → flagged.
        frame = pd.DataFrame(
            {
                "player_id": [1, 2, 3, 4],
                "role": ["Tank"] * 4,
                "rank": [1100, 1200, 1000, 1300],
                "impact_score": [55.0, 50.0, 60.0, 58.0],
                "local_zscore": [0.0, -0.1, 0.2, 0.3],
                "local_percentile": [50.0, 45.0, 55.0, 56.0],
                "kd": [1.0, 1.1, 1.0, 1.2],
                "weapon_accuracy": [30.0, 31.0, 28.0, 32.0],
                "final_blows_p10": [4.0, 4.5, 4.2, 5.0],
                "mvp_dominance": [0.5, 0.45, 0.55, 0.85],
            }
        )

        flags = anomalies.detect_smurfs(frame)

        smurf = next(f for f in flags if f["player_id"] == 4)
        self.assertEqual("smurf", smurf["kind"])
        self.assertIn("raw_mvp_dominance", smurf["reasons"])
        self.assertNotIn("strong_cohort_outlier", smurf["reasons"])
        self.assertAlmostEqual(0.85, smurf["evidence"]["mvp_dominance"], places=2)

    def test_smurf_dominance_threshold_respected(self) -> None:
        # mvp_dominance below threshold and nothing else suspicious → no flag.
        frame = pd.DataFrame(
            {
                "player_id": [1, 2, 3, 4],
                "role": ["Tank"] * 4,
                "rank": [1100, 1200, 1000, 1300],
                "impact_score": [55.0, 50.0, 60.0, 58.0],
                "local_zscore": [0.0, -0.1, 0.2, 0.3],
                "local_percentile": [50.0, 45.0, 55.0, 56.0],
                "kd": [1.0, 1.1, 1.0, 1.2],
                "weapon_accuracy": [30.0, 31.0, 28.0, 32.0],
                "final_blows_p10": [4.0, 4.5, 4.2, 5.0],
                "mvp_dominance": [0.5, 0.45, 0.55, 0.70],
            }
        )

        self.assertEqual([], anomalies.detect_smurfs(frame))

    def test_troll_prefers_local_history(self) -> None:
        frame = pd.DataFrame(
            {
                "player_id": [1, 2],
                "local_zscore_history": [[-1.6, -1.8, -2.0], [0.1, -0.2, 0.0]],
            }
        )

        flags = anomalies.detect_trolls(frame)

        self.assertEqual(["troll"], [flag["kind"] for flag in flags])
        self.assertEqual(1, flags[0]["player_id"])
        self.assertIn("recent_local_zscores", flags[0]["evidence"])

    def test_troll_adds_low_confidence_single_tournament_review_signal(self) -> None:
        frame = pd.DataFrame(
            {
                "player_id": [1, 2],
                "impact_score": [12.0, 40.0],
                "local_zscore": [-2.0, -1.9],
                "local_zscore_history": [[-2.0], [-1.9]],
            }
        )

        flags = anomalies.detect_trolls(frame)

        self.assertEqual([1], [flag["player_id"] for flag in flags])
        self.assertLessEqual(flags[0]["confidence"], 0.55)

    def test_troll_ignores_borderline_single_tournament_review_signal(self) -> None:
        frame = pd.DataFrame(
            {
                "player_id": [1],
                "impact_score": [19.0],
                "local_zscore": [-1.8],
                "local_zscore_history": [[-1.8]],
            }
        )

        flags = anomalies.detect_trolls(frame)

        self.assertEqual([], flags)

    def test_sandbag_detects_sharp_current_tournament_drop(self) -> None:
        frame = pd.DataFrame(
            {
                "player_id": [1, 2],
                "confidence": [0.9, 0.9],
                "local_zscore_history": [[0.6, -1.7], [0.1, -0.3]],
            }
        )

        flags = anomalies.detect_sandbags(frame)

        self.assertEqual(["sandbag"], [flag["kind"] for flag in flags])
        self.assertEqual(1, flags[0]["player_id"])
        self.assertGreater(flags[0]["score"], 1.5)

    def test_sandbag_ignores_borderline_current_tournament_drop(self) -> None:
        frame = pd.DataFrame(
            {
                "player_id": [1],
                "confidence": [0.9],
                "local_zscore_history": [[0.1, -1.2]],
            }
        )

        flags = anomalies.detect_sandbags(frame)

        self.assertEqual([], flags)

    def test_throw_ignores_team_wide_late_drop(self) -> None:
        rows = []
        for player_id in range(1, 6):
            for source_round, value in enumerate([10.0, 10.0, 1.0, 1.0], start=1):
                rows.append(
                    {
                        "encounter_id": 100,
                        "match_id": 10,
                        "source_round": source_round,
                        "player_id": player_id,
                        "team_id": 20,
                        "performance_points": value,
                    }
                )

        residuals = extractors._normalise_round_residuals(pd.DataFrame(rows))
        flags = anomalies.detect_throws(residuals)

        self.assertEqual([], flags)

    def test_throw_detects_individual_late_drop_against_team_peers(self) -> None:
        rows = []
        for player_id in range(1, 6):
            values = [10.0, 10.0, 1.0, 1.0] if player_id == 1 else [5.0, 5.0, 5.0, 5.0]
            for source_round, value in enumerate(values, start=1):
                rows.append(
                    {
                        "encounter_id": 100,
                        "match_id": 10,
                        "source_round": source_round,
                        "player_id": player_id,
                        "team_id": 20,
                        "performance_points": value,
                    }
                )

        residuals = extractors._normalise_round_residuals(pd.DataFrame(rows))
        flags = anomalies.detect_throws(residuals)

        self.assertEqual(["throw"], [flag["kind"] for flag in flags])
        self.assertEqual(1, flags[0]["player_id"])
        self.assertGreaterEqual(flags[0]["evidence"]["post_negative_fraction"], 0.6)
