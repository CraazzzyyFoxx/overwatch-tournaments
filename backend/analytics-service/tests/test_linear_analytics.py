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
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

linear = importlib.import_module("src.services.analytics.linear")


class LinearAnalyticsTests(TestCase):
    def signal(
        self,
        *,
        map_diff: float = 0.0,
        placement_score: float = 0.0,
        recency_decay: float = 1.0,
        coverage_weight: float = 1.0,
        newcomer_weight: float = 1.0,
        match_count: int = 4,
        log_available: float = 1.0,
    ):
        return linear.TournamentSignal(
            map_diff=map_diff,
            placement_score=placement_score,
            recency_decay=recency_decay,
            coverage_weight=coverage_weight,
            newcomer_weight=newcomer_weight,
            match_count=match_count,
            log_available=log_available,
        )

    def test_first_tournament_shift_is_hard_capped(self) -> None:
        metrics = linear.score_history([self.signal(map_diff=1.0, match_count=3)])

        self.assertEqual(1, metrics.sample_tournaments)
        self.assertLessEqual(abs(metrics.stable_shift), 1.5)
        self.assertAlmostEqual(metrics.stable_shift, metrics.trend_shift, places=6)

    def test_strong_individual_perf_produces_meaningful_shift(self) -> None:
        metrics = linear.score_history(
            [
                self.signal(
                    map_diff=1.0,
                    coverage_weight=0.7,
                    log_available=0.0,
                    match_count=3,
                )
            ]
        )

        self.assertGreaterEqual(metrics.stable_shift, 1.0)
        self.assertLessEqual(metrics.stable_shift, 1.5)

    def test_trend_requires_three_tournaments(self) -> None:
        short_history = linear.score_history(
            [
                self.signal(map_diff=0.3),
                self.signal(map_diff=0.4, recency_decay=0.85),
            ]
        )

        self.assertAlmostEqual(short_history.stable_shift, short_history.trend_shift, places=6)

    def test_newcomer_weight_damps_shift_and_evidence(self) -> None:
        veteran = linear.score_history(
            [
                self.signal(map_diff=0.6),
                self.signal(map_diff=0.5, recency_decay=0.85),
            ]
        )
        newcomer = linear.score_history(
            [
                self.signal(map_diff=0.6, newcomer_weight=0.75),
                self.signal(map_diff=0.5, recency_decay=0.85, newcomer_weight=0.75),
            ]
        )

        self.assertLess(newcomer.effective_evidence, veteran.effective_evidence)
        self.assertLess(newcomer.stable_shift, veteran.stable_shift)

    def test_missing_logs_and_standings_fall_back_to_zero_residuals(self) -> None:
        metrics = linear.score_history(
            [
                self.signal(
                    map_diff=0.0,
                    coverage_weight=0.7,
                    log_available=0.0,
                    match_count=2,
                ),
                self.signal(
                    map_diff=0.0,
                    coverage_weight=0.7,
                    log_available=0.0,
                    recency_decay=0.85,
                    match_count=1,
                ),
            ]
        )

        self.assertEqual(0.0, metrics.log_coverage)
        self.assertGreaterEqual(metrics.confidence, 0.0)
        self.assertLessEqual(metrics.confidence, 1.0)

    def test_hybrid_stays_close_to_stable_when_match_sample_is_low(self) -> None:
        metrics = linear.score_history(
            [
                self.signal(map_diff=0.2, match_count=1),
                self.signal(map_diff=0.3, match_count=1, recency_decay=0.85),
            ],
            openskill_shift=1.8,
        )

        self.assertLess(abs(metrics.hybrid_shift - metrics.stable_shift), 0.1)

    def test_custom_weights_change_stable_shift(self) -> None:
        signals = [self.signal(map_diff=1.0)]

        default = linear.score_history(signals)
        # Zero weight on every team component ⇒ the raw signal collapses to 0.
        zeroed = linear.score_history(signals, weights={"map_diff": 0.0, "placement_score": 0.0})

        self.assertGreater(abs(default.stable_shift), 0.0)
        self.assertAlmostEqual(0.0, zeroed.stable_shift, places=6)

    def test_default_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(1.0, sum(linear.RAW_SIGNAL_WEIGHTS.values()), places=6)

    def test_shift_scale_scales_stable_shift_linearly(self) -> None:
        # A small signal stays well below the clamps, so doubling the scale
        # doubles the stable shift.
        signals = [self.signal(map_diff=0.2)]
        base = linear.score_history(signals, shift_scale=1.0)
        doubled = linear.score_history(signals, shift_scale=2.0)

        self.assertAlmostEqual(2.0 * base.stable_shift, doubled.stable_shift, places=6)


class FitRawSignalWeightsTests(TestCase):
    def test_recovers_known_weights_on_clean_data(self) -> None:
        import numpy as np

        rng = np.random.default_rng(0)
        components = rng.uniform(-1.0, 1.0, size=(400, 2))
        # realised = 0.7*a + 0.3*b (sums to 1) over an arbitrary component set.
        realised = components @ np.array([0.7, 0.3])

        weights = linear.fit_raw_signal_weights(components, realised, component_names=("a", "b"))

        self.assertAlmostEqual(0.7, weights["a"], places=2)
        self.assertAlmostEqual(0.3, weights["b"], places=2)
        self.assertAlmostEqual(1.0, sum(weights.values()), places=6)

    def test_falls_back_to_defaults_on_too_few_samples(self) -> None:
        weights = linear.fit_raw_signal_weights([[1.0]], [0.5])

        self.assertEqual(dict(linear.RAW_SIGNAL_WEIGHTS), weights)
