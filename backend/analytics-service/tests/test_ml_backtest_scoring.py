"""Tests for the realised-label backtest scoring (Phase 1.1).

The old harness only compared v2 shifts against v1 shifts (``shift_mae_v1_vs_v2``),
which measures agreement with a heuristic, not accuracy. These tests pin the new
behaviour: scoring shift predictions against the *realised* division move
(``current_div - next_tournament_div``) and reporting sign-accuracy, plus a
position MAE for standings.
"""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

from shared import models  # noqa: E402
from tests import test_hidden_tournament_exclusion as hidden  # noqa: E402
from tests.factories import identity_assign as _identity_assign  # noqa: E402
from tests.ow_analytics import exports as ow_exports  # noqa: E402
from tests.test_hidden_tournament_exclusion import _Fixture  # noqa: E402

ANALYTICS_TABLES = (models.AnalyticsAlgorithm.__table__, models.AnalyticsShift.__table__)

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
            "calibration_vs_organizer_moves": {"ece": 0.1},
            "n_tournaments": 12,
        }

        merged = backtest._merge_backtest_metrics(existing, report)

        self.assertEqual(0.4, merged["mae_train"])  # preserved
        self.assertEqual(0.2, merged["r2_val"])  # preserved
        self.assertEqual(0.7, merged["backtest"]["summary"]["mean_shift_sign_accuracy_v2"])
        self.assertEqual(0.1, merged["backtest"]["calibration_vs_organizer_moves"]["ece"])
        self.assertEqual(12, merged["backtest"]["n_tournaments"])

    def test_merge_tolerates_none_existing(self) -> None:
        merged = backtest._merge_backtest_metrics(None, {"summary": {}, "calibration_vs_organizer_moves": {}})
        self.assertIn("backtest", merged)


class LatestTournamentTests(IsolatedAsyncioTestCase):
    async def test_latest_is_the_last_to_start_not_the_highest_id(self) -> None:
        db = _Fixture()
        try:
            for tournament_id in (1, 2, 3):
                db.tournament(tournament_id)
            # Tournament 1 was created first but is the last to start.
            db.session.execute(
                sa.update(models.Tournament)
                .where(models.Tournament.id == 1)
                .values(start_date=datetime(2026, 2, 1, tzinfo=UTC))
            )

            latest = await backtest._latest_tournament_id(db.shim, discipline="overwatch", workspace_id=None)
        finally:
            db.close()

        self.assertEqual(1, latest)


class RealisedShiftMapTests(IsolatedAsyncioTestCase):
    def _session(self, rows: list[dict]) -> SimpleNamespace:
        result = SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))
        return SimpleNamespace(execute=AsyncMock(return_value=result))

    @staticmethod
    def _row(player_id: int, tournament_id: int, started_at: int, rank: int) -> dict:
        return {
            "player_id": player_id,
            "user_id": 10,
            "role": "tank",
            "tournament_id": tournament_id,
            "started_at": started_at,
            "rank": rank,
            "version_id": 1,
        }

    async def test_realised_shift_is_current_minus_next_div(self) -> None:
        # rank doubles as the canonical division under the identity stub; start order matches id order here.
        rows = [self._row(1, 10, 1, 7), self._row(2, 20, 2, 6), self._row(3, 30, 3, 6)]
        session = self._session(rows)

        with (
            patch.object(backtest, "load_source_grids", AsyncMock(return_value={})),
            patch.object(ow_exports, "assign_canonical_division", _identity_assign),
        ):
            fold_10 = await backtest._realised_shift_map(
                session, 10, history_through_tournament_id=30, discipline="overwatch"
            )
        self.assertEqual({1: 1.0}, fold_10)  # 7 - 6

    async def test_last_tournament_without_next_is_dropped(self) -> None:
        rows = [self._row(1, 10, 1, 7), self._row(3, 30, 3, 6)]
        session = self._session(rows)

        with (
            patch.object(backtest, "load_source_grids", AsyncMock(return_value={})),
            patch.object(ow_exports, "assign_canonical_division", _identity_assign),
        ):
            fold_30 = await backtest._realised_shift_map(
                session, 30, history_through_tournament_id=30, discipline="overwatch"
            )
        self.assertEqual({}, fold_30)

    async def test_next_tournament_is_the_next_to_start_up_to_the_horizon_start(self) -> None:
        # Start order 2, 4, 3: tournament 4 has a higher id than the horizon (3) but started before it.
        db = _Fixture()
        try:
            for tournament_id, day in ((2, 1), (4, 2), (3, 3)):
                db.tournament(tournament_id)
                db.session.execute(
                    sa.update(models.Tournament)
                    .where(models.Tournament.id == tournament_id)
                    .values(start_date=datetime(2026, 1, day, tzinfo=UTC))
                )
            member = db.member(10)
            fold = db.player(2, db.team(2, "fold"), member, name="p", rank=3000)
            db.player(4, db.team(4, "next"), member, name="p", rank=2000)
            db.player(3, db.team(3, "horizon"), member, name="p", rank=4000)

            realised = await backtest._realised_shift_map(
                db.shim, 2, history_through_tournament_id=3, discipline="overwatch"
            )
        finally:
            db.close()

        div = ow_exports.canonical_div_for
        self.assertEqual({fold: float(div({}, None, 3000) - div({}, None, 2000))}, realised)


class ShiftHitProbabilityTests(IsolatedAsyncioTestCase):
    async def test_hit_probability_is_the_mass_within_half_a_division_and_skips_null_sd(self) -> None:
        with patch.object(hidden, "TABLES", (*hidden.TABLES, *ANALYTICS_TABLES)):
            db = _Fixture()
        try:
            db.tournament(1)
            team = db.team(1, "team")
            players = [db.player(1, team, db.member(user), name=f"p{user}") for user in (10, 20, 30)]
            db.insert(models.AnalyticsAlgorithm.__table__, id=1, name="Shift v2")
            for player_id, sd in zip(players, (0.5, None, 0.0), strict=True):
                db.insert(
                    models.AnalyticsShift.__table__,
                    id=player_id,
                    algorithm_id=1,
                    tournament_id=1,
                    player_id=player_id,
                    shift=1.0,
                    shift_sd=sd,
                )

            p_hit = await backtest._v2_shift_hit_probability_map(db.shim, 1, "Shift v2")
        finally:
            db.close()

        # sd 0.5: 2Φ(1) − 1 ≈ 0.6827; the legacy NULL-sd row is skipped; sd 0 is a certain hit.
        self.assertEqual({players[0], players[2]}, set(p_hit))
        self.assertAlmostEqual(0.682689492, p_hit[players[0]], places=6)
        self.assertEqual(1.0, p_hit[players[2]])
