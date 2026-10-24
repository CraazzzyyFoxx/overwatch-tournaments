from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))


linear = importlib.import_module("src.domain.linear")


class LinearAnalyticsTests(TestCase):
    def signal(
        self,
        *,
        map_diff: float = 0.0,
        placement_score: float = 0.0,
        recency_decay: float = 1.0,
        coverage_weight: float = 1.0,
        maps: int = 12,
        match_count: int = 4,
        log_available: float = 1.0,
    ):
        return linear.TournamentSignal(
            map_diff=map_diff,
            placement_score=placement_score,
            recency_decay=recency_decay,
            coverage_weight=coverage_weight,
            maps=maps,
            match_count=match_count,
            log_available=log_available,
        )

    def test_first_tournament_shift_is_hard_capped(self) -> None:
        metrics = linear.score_history([self.signal(map_diff=1.0, match_count=3)], noise_sd=None)

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
                    maps=20,
                    match_count=3,
                )
            ],
            noise_sd=None,
        )

        self.assertGreaterEqual(metrics.stable_shift, 1.0)
        self.assertLessEqual(metrics.stable_shift, 1.5)

    def test_trend_requires_three_tournaments(self) -> None:
        short_history = linear.score_history(
            [
                self.signal(map_diff=0.3),
                self.signal(map_diff=0.4, recency_decay=0.85),
            ],
            noise_sd=None,
        )

        self.assertAlmostEqual(short_history.stable_shift, short_history.trend_shift, places=6)

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
            ],
            noise_sd=None,
        )

        self.assertEqual(0.0, metrics.log_coverage)
        self.assertEqual(0.0, metrics.stable_shift)

    def test_custom_weights_change_stable_shift(self) -> None:
        signals = [self.signal(map_diff=1.0)]

        default = linear.score_history(signals, noise_sd=None)
        # Zero weight on every team component ⇒ the raw signal collapses to 0.
        zeroed = linear.score_history(signals, noise_sd=None, weights={"map_diff": 0.0, "placement_score": 0.0})

        self.assertGreater(abs(default.stable_shift), 0.0)
        self.assertAlmostEqual(0.0, zeroed.stable_shift, places=6)

    def test_default_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(1.0, sum(linear.RAW_SIGNAL_WEIGHTS.values()), places=6)

    def test_shift_scale_scales_stable_shift_linearly(self) -> None:
        # A small signal stays well below the clamps, so doubling the scale
        # doubles the stable shift.
        signals = [self.signal(map_diff=0.2)]
        base = linear.score_history(signals, noise_sd=None, shift_scale=1.0)
        doubled = linear.score_history(signals, noise_sd=None, shift_scale=2.0)

        self.assertAlmostEqual(2.0 * base.stable_shift, doubled.stable_shift, places=6)
