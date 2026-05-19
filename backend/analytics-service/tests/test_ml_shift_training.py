from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

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

performance_v2 = importlib.import_module("src.services.ml.models.performance_v2")
shift_features = importlib.import_module("src.services.ml.features.shift_features")
shift_v2 = importlib.import_module("src.services.ml.models.shift_v2")
orchestrator = importlib.import_module("src.services.ml.training.orchestrator")


class _ConstantBooster:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, frame: pd.DataFrame):
        return [self.value] * len(frame)


class ShiftRankHistoryTests(IsolatedAsyncioTestCase):
    async def test_explicit_history_horizon_keeps_sparse_future_tournament_labels(self) -> None:
        rows = [
            {
                "player_id": 1,
                "user_id": 10,
                "role": "tank",
                "tournament_id": 10,
                "rank": 1500,
                "is_newcomer": False,
                "div": 7,
            },
            {
                "player_id": 2,
                "user_id": 10,
                "role": "tank",
                "tournament_id": 20,
                "rank": 1600,
                "is_newcomer": False,
                "div": 6,
            },
        ]
        result = SimpleNamespace(
            mappings=lambda: SimpleNamespace(all=lambda: rows),
        )
        session = SimpleNamespace(execute=AsyncMock(return_value=result))

        history = await shift_features._player_rank_history(
            session,
            [10],
            history_through_tournament_id=20,
        )

        first_row = history.loc[history["tournament_id"] == 10].iloc[0]
        self.assertEqual(6, first_row["next_tournament_div"])

        query = session.execute.await_args.args[0]
        params = query.compile().params
        self.assertIn(20, params.values())


class ShiftTrainingDiagnosticsTests(TestCase):
    def test_shift_feature_order_includes_level_adjusted_performance(self) -> None:
        self.assertIn("linear_stable_shift", shift_v2.SHIFT_FEATURE_ORDER)
        self.assertIn("linear_confidence", shift_v2.SHIFT_FEATURE_ORDER)
        self.assertIn("performance_v2_local_residual", shift_v2.SHIFT_FEATURE_ORDER)
        self.assertIn("performance_v2_local_zscore", shift_v2.SHIFT_FEATURE_ORDER)
        self.assertIn("performance_v2_local_percentile", shift_v2.SHIFT_FEATURE_ORDER)

    def test_empty_label_error_reports_missing_columns(self) -> None:
        frame = pd.DataFrame(
            {
                "next_tournament_div": [None],
                "current_div": [4.0],
                "os_shift": [None],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            r"non-null counts: \{'next_tournament_div': 0, 'current_div': 1, 'os_shift': 0\}",
        ):
            shift_v2.train_shift_v2(frame)

    def test_residual_target_uses_current_to_next_division_move(self) -> None:
        frame = pd.DataFrame(
            {
                "prior_div": [12.0],
                "current_div": [10.0],
                "next_tournament_div": [8.0],
                "os_shift": [1.25],
            }
        )

        target = shift_v2.build_residual_target(frame)

        self.assertAlmostEqual(0.75, float(target.iloc[0]))

    def test_residual_target_prefers_linear_stable_baseline_when_available(self) -> None:
        frame = pd.DataFrame(
            {
                "current_div": [10.0],
                "next_tournament_div": [8.0],
                "os_shift": [-1.0],
                "linear_stable_shift": [1.5],
            }
        )

        target = shift_v2.build_residual_target(frame)

        self.assertAlmostEqual(0.5, float(target.iloc[0]))

    def test_prediction_anchors_to_linear_stable_baseline(self) -> None:
        model = shift_v2.ShiftModelV2(
            booster=_ConstantBooster(0.0),
            booster_q10=_ConstantBooster(-0.1),
            booster_q90=_ConstantBooster(0.1),
        )
        frame = pd.DataFrame(
            {
                "os_shift": [-2.5],
                "linear_stable_shift": [1.0],
                "linear_confidence": [0.8],
                "tournaments_played": [3],
                "is_newcomer": [False],
            }
        )

        prediction = model.predict_with_confidence(frame)

        self.assertAlmostEqual(1.0, float(prediction["shift_v2"].iloc[0]))
        self.assertLess(float(prediction["confidence"].iloc[0]), 1.0)

    def test_validation_rows_are_reused_when_they_are_the_only_labelled_rows(self) -> None:
        train_df = pd.DataFrame(
            {
                "tournament_id": [62],
                "next_tournament_div": [6.0],
                "current_div": [None],
                "os_shift": [0.2],
            }
        )
        val_df = pd.DataFrame(
            {
                "tournament_id": [63],
                "next_tournament_div": [5.0],
                "current_div": [6.0],
                "os_shift": [0.3],
            }
        )

        prepared_train, prepared_val = orchestrator._prepare_shift_training_frames(
            train_df,
            val_df,
        )

        self.assertEqual([63], prepared_train["tournament_id"].tolist())
        self.assertTrue(prepared_val.empty)


class PerformanceBaselineTests(TestCase):
    def test_logistic_baseline_scales_features(self) -> None:
        frame = pd.DataFrame(
            {
                "team_avg_mu": [900.0, 1200.0, 1500.0, 1800.0],
                "opp_avg_mu": [1800.0, 1500.0, 1200.0, 900.0],
                "mu_gap": [-900.0, -300.0, 300.0, 900.0],
                "won": [0, 0, 1, 1],
            }
        )

        _, baseline = performance_v2.build_target(frame)

        self.assertIn("standardscaler", baseline.named_steps)
        self.assertEqual(
            1000,
            baseline.named_steps["logisticregression"].max_iter,
        )
