"""The read-only shift-method evaluation: next-tournament encounter scoring and the level loader's rules.

The loader runs its real queries on the in-memory SQLite stand-in of ``test_hidden_tournament_exclusion`` (plus the two
analytics tables it reads): T_p is a property of the emitted chronology, which a mock session cannot falsify.
"""

from __future__ import annotations

import importlib
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

import numpy as np
import pandas as pd
import sqlalchemy as sa

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

from shared import models  # noqa: E402
from tests import test_hidden_tournament_exclusion as hidden  # noqa: E402
from tests.ow_analytics import exports as ow_exports  # noqa: E402

evaluate = importlib.import_module("src.services.analytics.evaluate")
ratings = importlib.import_module("src.domain.ratings")

SHIFT_V2 = ow_exports.MODELS["shift"].algorithm_name
ALGORITHMS = (ratings.POINTS, ratings.LINEAR, ratings.OPENSKILL, SHIFT_V2)
ANALYTICS_TABLES = (models.AnalyticsAlgorithm.__table__, models.AnalyticsShift.__table__)


def _div(rank: int) -> float:
    return float(ow_exports.canonical_div_for({}, None, rank))


class FitAndAucTests(TestCase):
    def test_k_is_the_maximum_likelihood_slope(self) -> None:
        # Home is one division stronger in every encounter and wins 3 of 4: σ(k) = 3/4, so k = ln 3.
        k = evaluate._fit_k(np.full(4, -1.0), np.array([1.0, 1.0, 1.0, 0.0]))

        self.assertAlmostEqual(math.log(3), k, places=6)

    def test_k_is_never_negative(self) -> None:
        # The stronger side loses more often than it wins: the best k ≥ 0 is no signal at all.
        self.assertEqual(0.0, evaluate._fit_k(np.full(4, -1.0), np.array([1.0, 0.0, 0.0, 0.0])))

    def test_auc_ranks_predictions_and_counts_ties_half(self) -> None:
        home_won = np.array([1.0, 0.0, 1.0, 0.0])

        self.assertAlmostEqual(0.75, evaluate._auc(np.array([0.9, 0.8, 0.3, 0.1]), home_won))
        self.assertAlmostEqual(0.5, evaluate._auc(np.full(4, 0.5), home_won))
        self.assertIsNone(evaluate._auc(np.array([0.9, 0.1]), np.array([1.0, 1.0])))


class ScoreMethodsTests(TestCase):
    def test_the_true_levels_beat_no_moves_and_rank_first(self) -> None:
        # Four teams, true strength = team id (lower = stronger); team 1's two players average to 1.
        levels = pd.DataFrame(
            {
                "team_id": [1, 1, 2, 3, 4],
                "no_moves": [5.0, 5.0, 5.0, 5.0, 5.0],
                "truth": [0.0, 2.0, 2.0, 3.0, 4.0],
            }
        )
        stored = pd.DataFrame({"truth": [True, False, True, True, True]})
        # The stronger side wins every encounter but one upset (3 beats 2), so k stays finite.
        encounters = pd.DataFrame(
            [(1, 2, True), (2, 1, False), (3, 4, True), (4, 3, False), (1, 4, True), (2, 3, False)],
            columns=["home_team_id", "away_team_id", "home_won"],
        )

        scores = evaluate.score_methods(evaluate.EvaluationFrame((1,), levels, stored, encounters))

        truth, no_moves = scores
        self.assertEqual(["truth", "no_moves"], [s["method"] for s in scores])
        self.assertEqual(6, truth["n_encounters"])
        self.assertAlmostEqual(0.8, truth["coverage"])
        self.assertIsNone(no_moves["coverage"])
        self.assertGreater(truth["k"], 0.0)
        self.assertLess(truth["log_loss"], no_moves["log_loss"])
        self.assertLess(truth["brier"], no_moves["brier"])
        self.assertGreater(truth["auc"], 0.5)
        # Equal levels everywhere: no slope, a coin flip.
        self.assertEqual(0.0, no_moves["k"])
        self.assertAlmostEqual(math.log(2), no_moves["log_loss"])
        self.assertAlmostEqual(0.25, no_moves["brier"])
        self.assertAlmostEqual(0.5, no_moves["auc"])


class _EvaluationDatabaseTestCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        with patch.object(hidden, "TABLES", (*hidden.TABLES, *ANALYTICS_TABLES)):
            self.db = hidden._Fixture()
        for algorithm_id, name in enumerate(ALGORITHMS, 1):
            self.db.insert(models.AnalyticsAlgorithm.__table__, id=algorithm_id, name=name)
        self.algorithm_ids = {name: algorithm_id for algorithm_id, name in enumerate(ALGORITHMS, 1)}

    def tearDown(self) -> None:
        self.db.close()

    def start(self, tournament_id: int, day: int) -> None:
        self.db.tournament(tournament_id)
        self.db.session.execute(
            sa.update(models.Tournament)
            .where(models.Tournament.id == tournament_id)
            .values(start_date=datetime(2026, 1, day, tzinfo=UTC))
        )

    def shift(self, algorithm: str, tournament_id: int, player_id: int, value: float) -> None:
        self.db.insert(
            models.AnalyticsShift.__table__,
            id=self.db._id(),
            algorithm_id=self.algorithm_ids[algorithm],
            tournament_id=tournament_id,
            player_id=player_id,
            shift=value,
        )

    def world(self) -> dict[str, int]:
        """Ids are not chronological: tournament 3 started before tournament 2, the evaluated T′."""
        db = self.db
        for tournament_id, day in ((1, 1), (3, 2), (2, 3), (4, 4)):
            self.start(tournament_id, day)
        a, b, c = db.member(100), db.member(200), db.member(300)

        early = db.team(1, "early")
        a_1 = db.player(1, early, a, name="a", rank=1500)
        c_1 = db.player(1, early, c, name="c", rank=3000)
        a_3 = db.player(3, db.team(3, "middle"), a, name="a", rank=2500)
        home, away = db.team(2, "home"), db.team(2, "away")
        a_2 = db.player(2, home, a, name="a", rank=3500)
        b_2 = db.player(2, home, b, name="b", rank=2000)
        c_2 = db.player(2, away, c, name="c", rank=4000)

        # A's T_p is tournament 3 (the latest to START before T′), not tournament 1 (the highest lower id).
        self.shift(ratings.POINTS, 3, a_3, 1.5)
        self.shift(ratings.LINEAR, 3, a_3, -0.5)
        self.shift(ratings.POINTS, 1, a_1, 9.0)
        # A row at T′ itself is what the method says after the fact: never read.
        self.shift(ratings.POINTS, 2, a_2, 7.0)
        # C's only earlier tournament is 1: Points has a row there, Linear does not.
        self.shift(ratings.POINTS, 1, c_1, 2.0)

        db.encounter(2, home, away)  # home wins 2-1
        draw = db.encounter(2, home, away)
        db.session.execute(
            sa.update(models.EncounterTeam).where(models.EncounterTeam.encounter_id == draw).values(placement=1)
        )
        # A later tournament is out of the evaluated range.
        later_home, later_away = db.team(4, "later home"), db.team(4, "later away")
        db.player(4, later_home, a, name="a", rank=3500)
        db.player(4, later_away, c, name="c", rank=4000)
        db.encounter(4, later_home, later_away)
        return {"home": home, "away": away, "a_2": a_2, "b_2": b_2, "c_2": c_2}


class LoaderTests(_EvaluationDatabaseTestCase):
    async def test_levels_follow_chronological_t_p_newcomer_fallback_and_missing_rows(self) -> None:
        ids = self.world()

        frame = await evaluate.load_evaluation_frame(
            self.db.shim, discipline="overwatch", from_tournament_id=2, to_tournament_id=2
        )

        self.assertEqual((2,), frame.tournament_ids)
        # The draw is no duel outcome; tournament 4 is outside the range.
        self.assertEqual(
            [(ids["home"], ids["away"], True)],
            list(frame.encounters[["home_team_id", "away_team_id", "home_won"]].itertuples(index=False, name=None)),
        )
        a, b, c = (frame.levels.loc[ids[key]] for key in ("a_2", "b_2", "c_2"))

        self.assertEqual(_div(3500), a["organizer"])
        self.assertEqual(_div(2500), a["no_moves"])
        self.assertEqual(_div(2500) - 1.5, a[ratings.POINTS])
        self.assertEqual(_div(2500) + 0.5, a[ratings.LINEAR])
        self.assertEqual(_div(2500), a[ratings.OPENSKILL])
        self.assertEqual(_div(2500), a[SHIFT_V2])
        # A newcomer has no T_p: every method is the organizer's level.
        self.assertEqual({_div(2000)}, set(b.drop("team_id")))
        self.assertEqual(_div(3000), c["no_moves"])
        self.assertEqual(_div(3000) - 2.0, c[ratings.POINTS])
        self.assertEqual(_div(3000), c[ratings.LINEAR])  # no stored row: no move

        stored = frame.stored.loc[[ids["a_2"], ids["b_2"], ids["c_2"]]]
        self.assertEqual([True, False, True], list(stored[ratings.POINTS]))
        self.assertEqual([True, False, False], list(stored[ratings.LINEAR]))
        self.assertEqual([False, False, False], list(stored[ratings.OPENSKILL]))

    async def test_evaluate_issues_only_selects_and_reports_every_method(self) -> None:
        self.world()
        seen: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            seen.append(statement)

        sa.event.listen(self.db.engine, "before_cursor_execute", record)
        try:
            report = await evaluate.evaluate_shift_methods(self.db.shim, from_tournament_id=2, to_tournament_id=2)
        finally:
            sa.event.remove(self.db.engine, "before_cursor_execute", record)

        self.assertTrue(seen)
        self.assertTrue(all(s.lstrip().upper().startswith(("SELECT", "WITH")) for s in seen), seen)
        self.assertEqual("overwatch", report["discipline"])
        self.assertEqual({"organizer", "no_moves", *ALGORITHMS}, {m["method"] for m in report["methods"]})
        self.assertEqual({1}, {m["n_encounters"] for m in report["methods"]})
        self.assertIn("log_loss", evaluate.format_table(report))
