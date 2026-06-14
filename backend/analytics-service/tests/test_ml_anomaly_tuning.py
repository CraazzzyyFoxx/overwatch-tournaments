"""Tests for anomaly threshold tuning (Phase 6.2).

Once reviewers label anomalies (confirmed = true positive, dismissed = false
positive), ``tune_threshold`` picks a score cut-off that hits a target precision
with the most recall — replacing hand-set magic thresholds.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

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

tuning = importlib.import_module("src.services.ml.models.anomaly_tuning")


class PrecisionRecallCurveTests(TestCase):
    def test_curve_points_match_manual_counts(self) -> None:
        scores = [0.1, 0.4, 0.6, 0.9]
        labels = [False, False, True, True]

        curve = {round(p["threshold"], 1): p for p in tuning.precision_recall_curve(scores, labels)}

        # threshold 0.6 flags {0.6, 0.9}: precision 1.0, recall 1.0
        self.assertAlmostEqual(1.0, curve[0.6]["precision"])
        self.assertAlmostEqual(1.0, curve[0.6]["recall"])
        # threshold 0.4 flags {0.4, 0.6, 0.9}: 2 of 3 are TP
        self.assertAlmostEqual(2 / 3, curve[0.4]["precision"])
        self.assertAlmostEqual(1.0, curve[0.4]["recall"])

    def test_empty_inputs(self) -> None:
        self.assertEqual([], tuning.precision_recall_curve([], []))


class TuneThresholdTests(TestCase):
    def test_picks_lowest_threshold_meeting_target_precision(self) -> None:
        scores = [0.1, 0.4, 0.6, 0.9]
        labels = [False, False, True, True]

        best = tuning.tune_threshold(scores, labels, target_precision=0.8)

        self.assertIsNotNone(best)
        # 0.6 reaches precision 1.0 with full recall — preferred over 0.9.
        self.assertAlmostEqual(0.6, best["threshold"])
        self.assertAlmostEqual(1.0, best["recall"])

    def test_returns_none_when_target_unreachable(self) -> None:
        # All dismissed (no true positives) ⇒ precision is 0 everywhere.
        best = tuning.tune_threshold([0.2, 0.8], [False, False], target_precision=0.8)
        self.assertIsNone(best)

    def test_prefers_recall_then_lower_threshold(self) -> None:
        # Two thresholds both at precision 1.0; pick the one with higher recall.
        scores = [0.3, 0.5, 0.7, 0.9]
        labels = [True, True, True, True]  # all TP

        best = tuning.tune_threshold(scores, labels, target_precision=1.0)

        self.assertAlmostEqual(0.3, best["threshold"])  # flags all, recall 1.0
        self.assertAlmostEqual(1.0, best["recall"])
