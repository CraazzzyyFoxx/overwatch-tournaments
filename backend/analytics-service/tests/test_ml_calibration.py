"""Tests for confidence calibration (Phase 1.2).

``compute_calibration_report`` turns ``(confidence, |error|)`` pairs into a
reliability curve + Expected Calibration Error so we can tell whether the
``confidence`` numbers emitted by Shift v2 / Linear actually track real error.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

import numpy as np

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

calibration = importlib.import_module("src.services.ml.training.calibration")


class CalibrationReportTests(TestCase):
    def test_empty_inputs(self) -> None:
        report = calibration.compute_calibration_report([], [])
        self.assertEqual(0, report["n"])
        self.assertIsNone(report["ece"])
        self.assertEqual([], report["bins"])

    def test_perfect_calibration_has_low_ece(self) -> None:
        # For each confidence bin centred at c, exactly a fraction c of rows are
        # accurate (error <= tolerance) ⇒ hit_rate ≈ confidence ⇒ ECE ≈ 0.
        confidences: list[float] = []
        errors: list[float] = []
        for c in [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]:
            k = 100
            n_hit = round(c * k)
            confidences += [c] * k
            errors += [0.0] * n_hit + [1.0] * (k - n_hit)

        report = calibration.compute_calibration_report(confidences, errors, n_bins=10, accuracy_tolerance=0.5)

        self.assertEqual(1000, report["n"])
        self.assertEqual(10, len(report["bins"]))
        self.assertLess(report["ece"], 0.05)

    def test_confidence_error_correlation_is_negative_when_calibrated(self) -> None:
        # Higher confidence ⇒ smaller error ⇒ negative Pearson correlation.
        rng = np.random.default_rng(0)
        confidences = rng.uniform(0, 1, size=200)
        errors = (1.0 - confidences) * 2.0 + rng.normal(0, 0.05, size=200)

        report = calibration.compute_calibration_report(confidences.tolist(), errors.tolist())

        self.assertLess(report["confidence_error_corr"], 0.0)

    def test_miscalibrated_confidence_has_high_ece(self) -> None:
        # Confidence is high but the error always exceeds the tolerance ⇒
        # hit_rate ≈ 0 while confidence ≈ 0.9 ⇒ ECE close to 0.9.
        confidences = [0.9] * 50
        errors = [2.0] * 50

        report = calibration.compute_calibration_report(confidences, errors, accuracy_tolerance=0.5)

        self.assertEqual(0.0, report["accuracy_rate"])
        self.assertGreater(report["ece"], 0.8)
