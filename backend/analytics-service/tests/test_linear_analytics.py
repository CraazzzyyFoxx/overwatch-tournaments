from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

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
        map_diff: float,
        placement_score: float,
        log_residual: float,
        recency_decay: float = 1.0,
        coverage_weight: float = 1.0,
        newcomer_weight: float = 1.0,
        match_count: int = 4,
        log_available: float = 1.0,
    ):
        return linear.TournamentSignal(
            map_diff=map_diff,
            placement_score=placement_score,
            log_residual=log_residual,
            recency_decay=recency_decay,
            coverage_weight=coverage_weight,
            newcomer_weight=newcomer_weight,
            match_count=match_count,
            log_available=log_available,
        )

    def test_first_tournament_shift_is_hard_capped(self) -> None:
        metrics = linear.score_history(
            [
                self.signal(
                    map_diff=1.0,
                    placement_score=1.0,
                    log_residual=1.0,
                    match_count=3,
                )
            ]
        )

        self.assertEqual(1, metrics.sample_tournaments)
        self.assertLessEqual(abs(metrics.stable_shift), 1.5)
        self.assertAlmostEqual(metrics.stable_shift, metrics.trend_shift, places=6)

    def test_first_place_can_produce_meaningful_shift(self) -> None:
        metrics = linear.score_history(
            [
                self.signal(
                    map_diff=1 / 3,
                    placement_score=1.0,
                    log_residual=0.0,
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
                self.signal(map_diff=0.4, placement_score=0.2, log_residual=0.0),
                self.signal(map_diff=0.6, placement_score=0.1, log_residual=0.0, recency_decay=0.85),
            ]
        )

        self.assertAlmostEqual(short_history.stable_shift, short_history.trend_shift, places=6)

    def test_newcomer_weight_damps_shift_and_evidence(self) -> None:
        veteran = linear.score_history(
            [
                self.signal(map_diff=0.8, placement_score=0.5, log_residual=0.2),
                self.signal(map_diff=0.7, placement_score=0.4, log_residual=0.1, recency_decay=0.85),
            ]
        )
        newcomer = linear.score_history(
            [
                self.signal(
                    map_diff=0.8,
                    placement_score=0.5,
                    log_residual=0.2,
                    newcomer_weight=0.75,
                ),
                self.signal(
                    map_diff=0.7,
                    placement_score=0.4,
                    log_residual=0.1,
                    recency_decay=0.85,
                    newcomer_weight=0.75,
                ),
            ]
        )

        self.assertLess(newcomer.effective_evidence, veteran.effective_evidence)
        self.assertLess(newcomer.stable_shift, veteran.stable_shift)

    def test_missing_logs_and_standings_fall_back_to_zero_residuals(self) -> None:
        metrics = linear.score_history(
            [
                self.signal(
                    map_diff=0.2,
                    placement_score=0.0,
                    log_residual=0.0,
                    coverage_weight=0.7,
                    log_available=0.0,
                    match_count=2,
                ),
                self.signal(
                    map_diff=-0.1,
                    placement_score=0.0,
                    log_residual=0.0,
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
                self.signal(map_diff=0.3, placement_score=0.2, log_residual=0.0, match_count=1),
                self.signal(map_diff=0.4, placement_score=0.2, log_residual=0.1, match_count=1, recency_decay=0.85),
            ],
            openskill_shift=1.8,
        )

        self.assertLess(abs(metrics.hybrid_shift - metrics.stable_shift), 0.1)

    def test_last_tournament_signal_disagreement_reduces_confidence(self) -> None:
        aligned = linear.score_history(
            [
                self.signal(map_diff=0.4, placement_score=0.4, log_residual=0.3),
                self.signal(map_diff=0.5, placement_score=0.3, log_residual=0.2, recency_decay=0.85),
            ]
        )
        conflicting = linear.score_history(
            [
                self.signal(map_diff=0.4, placement_score=0.4, log_residual=0.3),
                self.signal(map_diff=0.5, placement_score=-0.3, log_residual=0.2, recency_decay=0.85),
            ]
        )

        self.assertLess(conflicting.confidence, aligned.confidence)
