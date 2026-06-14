"""Tests for the realised-label backtest scoring (Phase 1.1).

The old harness only compared v2 shifts against v1 shifts (``shift_mae_v1_vs_v2``),
which measures agreement with a heuristic, not accuracy. These tests pin the new
behaviour: scoring shift predictions against the *realised* division move
(``current_div - next_tournament_div``) and reporting sign-accuracy, plus a
position MAE for standings.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

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

backtest = importlib.import_module("src.services.ml.training.backtest")


class ShiftScoreTests(TestCase):
    def test_scores_compute_mae_rmse_and_sign_accuracy(self) -> None:
        realised = {1: 1.0, 2: -2.0, 3: 0.0, 4: 1.0}
        predicted = {1: 0.8, 2: -1.0, 3: 0.2, 4: -0.5, 5: 9.0}

        scores = backtest._shift_scores(realised, predicted)

        self.assertEqual(4, scores["n"])  # key 5 is ignored (not in realised)
        self.assertAlmostEqual(0.725, scores["shift_mae"], places=6)
        self.assertAlmostEqual(0.9124144, scores["shift_rmse"], places=5)
        # Moved players: 1 (+), 2 (-), 4 (+). Predicted signs: +, -, - → 2/3.
        self.assertAlmostEqual(2 / 3, scores["shift_sign_accuracy"], places=6)

    def test_scores_handle_no_overlap(self) -> None:
        scores = backtest._shift_scores({1: 1.0}, {2: 0.5})

        self.assertEqual(0, scores["n"])
        self.assertIsNone(scores["shift_mae"])
        self.assertIsNone(scores["shift_sign_accuracy"])

    def test_sign_accuracy_is_none_when_no_one_moved(self) -> None:
        scores = backtest._shift_scores({1: 0.0, 2: 0.0}, {1: 0.4, 2: -0.1})

        self.assertEqual(2, scores["n"])
        self.assertIsNotNone(scores["shift_mae"])
        self.assertIsNone(scores["shift_sign_accuracy"])

    def test_subthreshold_prediction_for_a_real_move_is_a_miss(self) -> None:
        # Player moved +1 but the model predicted a near-zero "no move" — the
        # correct sign must NOT be rewarded as a hit on noise.
        scores = backtest._shift_scores({1: 1.0, 2: -1.0}, {1: 0.1, 2: -0.8})

        # Player 1: |0.1| < 0.5 ⇒ miss. Player 2: |−0.8| ≥ 0.5 and sign matches ⇒ hit.
        self.assertAlmostEqual(0.5, scores["shift_sign_accuracy"], places=6)


class PositionMaeTests(TestCase):
    def test_position_mae_over_common_teams(self) -> None:
        actual = {1: 1, 2: 2, 3: 3}
        predicted = {1: 1.5, 2: 2.0, 3: 5.0, 4: 9.0}

        self.assertAlmostEqual(2.5 / 3, backtest._position_mae(actual, predicted), places=6)

    def test_position_mae_none_without_overlap(self) -> None:
        self.assertIsNone(backtest._position_mae({1: 1}, {2: 1.0}))


class MergeBacktestMetricsTests(TestCase):
    def test_merge_adds_backtest_block_without_dropping_existing(self) -> None:
        existing = {"mae_train": 0.4, "r2_val": 0.2}
        report = {
            "summary": {"mean_shift_sign_accuracy_v2": 0.7},
            "calibration": {"ece": 0.1},
            "n_tournaments": 12,
        }

        merged = backtest._merge_backtest_metrics(existing, report)

        self.assertEqual(0.4, merged["mae_train"])  # preserved
        self.assertEqual(0.2, merged["r2_val"])  # preserved
        self.assertEqual(0.7, merged["backtest"]["summary"]["mean_shift_sign_accuracy_v2"])
        self.assertEqual(0.1, merged["backtest"]["calibration"]["ece"])
        self.assertEqual(12, merged["backtest"]["n_tournaments"])

    def test_merge_tolerates_none_existing(self) -> None:
        merged = backtest._merge_backtest_metrics(None, {"summary": {}, "calibration": {}})
        self.assertIn("backtest", merged)


class RealisedShiftMapTests(IsolatedAsyncioTestCase):
    def _session(self, rows: list[dict]) -> SimpleNamespace:
        result = SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))
        return SimpleNamespace(execute=AsyncMock(return_value=result))

    async def test_realised_shift_is_current_minus_next_div(self) -> None:
        rows = [
            {"player_id": 1, "user_id": 10, "role": "tank", "tournament_id": 10, "div": 7},
            {"player_id": 2, "user_id": 10, "role": "tank", "tournament_id": 20, "div": 6},
            {"player_id": 3, "user_id": 10, "role": "tank", "tournament_id": 30, "div": 6},
        ]
        session = self._session(rows)

        fold_10 = await backtest._realised_shift_map(
            session, 10, history_through_tournament_id=30
        )
        self.assertEqual({1: 1.0}, fold_10)  # 7 - 6

    async def test_last_tournament_without_next_is_dropped(self) -> None:
        rows = [
            {"player_id": 1, "user_id": 10, "role": "tank", "tournament_id": 10, "div": 7},
            {"player_id": 3, "user_id": 10, "role": "tank", "tournament_id": 30, "div": 6},
        ]
        session = self._session(rows)

        fold_30 = await backtest._realised_shift_map(
            session, 30, history_through_tournament_id=30
        )
        self.assertEqual({}, fold_30)
