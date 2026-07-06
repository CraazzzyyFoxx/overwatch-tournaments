"""Tests for Match Quality scoring (Phase 3.2).

Covers the data-derived ``sigma_pool`` (skill-balance scale taken from the
field's own mu-gap distribution instead of a fixed 300) and the named,
overridable component weights.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

import numpy as np
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

mq = importlib.import_module("src.services.ml.models.match_quality")


class DeriveSigmaPoolTests(TestCase):
    def test_uses_p90_of_absolute_gaps(self) -> None:
        gaps = [0.0, 10.0, 20.0, 30.0, 100.0]
        # p90 of |gaps| = 72 (numpy linear interp between 30 and 100).
        self.assertAlmostEqual(72.0, mq._derive_sigma_pool(gaps), places=4)

    def test_falls_back_without_gaps(self) -> None:
        self.assertEqual(mq.DEFAULT_SIGMA_POOL, mq._derive_sigma_pool([]))

    def test_floored_at_one(self) -> None:
        self.assertEqual(1.0, mq._derive_sigma_pool([0.0, 0.0, 0.0]))


class SkillBalanceTests(TestCase):
    def test_even_match_scores_full(self) -> None:
        self.assertAlmostEqual(100.0, mq._skill_balance(2000.0, 2000.0, sigma_pool=200.0))

    def test_gap_at_scale_scores_zero(self) -> None:
        self.assertAlmostEqual(0.0, mq._skill_balance(2000.0, 2200.0, sigma_pool=200.0))

    def test_missing_mu_is_neutral(self) -> None:
        self.assertEqual(50.0, mq._skill_balance(None, 2000.0))

    def test_nan_mu_is_neutral(self) -> None:
        # A pandas/numpy NaN is NOT ``None`` — teams with no mu snapshot (or
        # bracket placeholder encounters with no teams) arrive as NaN. The
        # guard must treat them as missing, else NaN leaks into the JSON
        # response and 500s the read endpoint (allow_nan=False).
        self.assertEqual(50.0, mq._skill_balance(float("nan"), 2000.0))
        self.assertEqual(50.0, mq._skill_balance(2000.0, float("nan")))


class PredictabilityTests(TestCase):
    def test_missing_inputs_are_neutral(self) -> None:
        self.assertEqual(50.0, mq._predictability(None, 0.5))
        self.assertEqual(50.0, mq._predictability(1.0, None))

    def test_nan_inputs_are_neutral(self) -> None:
        self.assertEqual(50.0, mq._predictability(float("nan"), 0.5))
        self.assertEqual(50.0, mq._predictability(1.0, float("nan")))

    def test_perfect_call_scores_full(self) -> None:
        self.assertAlmostEqual(100.0, mq._predictability(1.0, 1.0))


class ComputeMatchQualityTests(TestCase):
    def _encounters(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "encounter_id": [1, 2],
                "home_avg_mu": [2000.0, 2000.0],
                "away_avg_mu": [2010.0, 2400.0],  # even vs lopsided
                "home_won": [1.0, 1.0],
                "p_home_wins": [0.5, 0.9],
            }
        )

    def test_derived_sigma_makes_even_match_more_balanced(self) -> None:
        encounters = self._encounters()
        scores = pd.DataFrame({"encounter_id": [1, 2], "home_score": [3, 3], "away_score": [2, 0]})

        result = mq.compute_match_quality(encounters, scores).set_index("encounter_id")

        # sigma_pool is derived from gaps {10, 400}; the 10-gap match should be
        # far more skill-balanced than the 400-gap one.
        self.assertGreater(result.loc[1, "skill_balance"], result.loc[2, "skill_balance"])

    def test_weights_are_overridable(self) -> None:
        encounters = self._encounters().head(1)
        scores = pd.DataFrame({"encounter_id": [1], "home_score": [3], "away_score": [2]})

        all_skill = mq.compute_match_quality(
            encounters,
            scores,
            competitiveness_weight=0.0,
            predictability_weight=0.0,
            skill_balance_weight=1.0,
            sigma_pool=200.0,
        ).iloc[0]

        self.assertAlmostEqual(all_skill["skill_balance"], all_skill["quality_score"], places=6)

    def test_empty_encounters_returns_empty(self) -> None:
        result = mq.compute_match_quality(pd.DataFrame(), pd.DataFrame())
        self.assertTrue(result.empty)

    def test_duplicate_encounter_ids_collapse_to_one_row(self) -> None:
        # Upstream merge fan-out can repeat an encounter; the writer inserts into
        # analytics.match_quality keyed by (encounter_id, algorithm_id), so the
        # scorer must emit exactly one row per encounter or the INSERT trips
        # uq_analytics_match_quality on a within-batch duplicate.
        encounters = pd.DataFrame(
            {
                "encounter_id": [1, 1, 2],
                "home_avg_mu": [2000.0, 2000.0, 2000.0],
                "away_avg_mu": [2010.0, 2010.0, 2400.0],
                "home_won": [1.0, 1.0, 1.0],
                "p_home_wins": [0.5, 0.5, 0.9],
            }
        )
        scores = pd.DataFrame({"encounter_id": [1, 2], "home_score": [3, 3], "away_score": [2, 0]})

        result = mq.compute_match_quality(encounters, scores)

        self.assertEqual(2, len(result))
        self.assertEqual([1, 2], sorted(result["encounter_id"].tolist()))
        self.assertEqual(1, int((result["encounter_id"] == 1).sum()))

    def test_missing_mu_never_emits_nan(self) -> None:
        # Reproduces the production 500: an encounter whose teams have no mu
        # snapshot (NaN mu) — bracket placeholder / forfeit rows — must yield
        # finite, JSON-safe scores, never NaN.
        encounters = pd.DataFrame(
            {
                "encounter_id": [1, 2],
                "home_avg_mu": [2000.0, float("nan")],
                "away_avg_mu": [float("nan"), float("nan")],
                "home_won": [1.0, float("nan")],
                "p_home_wins": [0.7, 0.5],
            }
        )
        scores = pd.DataFrame({"encounter_id": [1], "home_score": [3], "away_score": [2]})

        result = mq.compute_match_quality(encounters, scores)

        numeric = ["competitiveness", "predictability", "skill_balance", "quality_score"]
        self.assertTrue(
            bool(np.isfinite(result[numeric].to_numpy(dtype=float)).all()),
            msg=f"non-finite leaked: {result[numeric].to_dict('records')}",
        )
        # Row 2 has no mu and an unknown outcome ⇒ neutral skill/predictability.
        row2 = result.set_index("encounter_id").loc[2]
        self.assertEqual(50.0, row2["skill_balance"])
        self.assertEqual(50.0, row2["predictability"])
