"""Tests for the Monte Carlo standings tie-break (Phase 3.1).

The round-robin ranker used to break win-count ties with a pure random shuffle.
It now breaks them by a sampled **map differential** (a 2-map sweep is more
likely the more lopsided the matchup), so an equal-win team that wins more
dominantly ranks ahead — only exact ``(wins, map_diff)`` ties stay random.
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

standings_v2 = importlib.import_module("src.services.ml.models.standings_v2")
runner = importlib.import_module("src.services.ml.inference.runner")


class BuildMatchupsTests(TestCase):
    """``_build_matchups`` must survive bracket placeholder encounters.

    Semis/finals/byes are stored as ``Encounter`` rows with NULL team ids long
    before the feeding matches finish. pandas reads those NULLs as NaN in a
    float64 column; the old ``.astype(int)`` blew up with
    ``IntCastingNaNError``. Such rows can't form a matchup and must be dropped.
    """

    def test_drops_encounters_with_unassigned_teams(self) -> None:
        feature_frame = pd.DataFrame(
            {
                "home_team_id": [2080.0, float("nan"), 2099.0],
                "away_team_id": [2074.0, 2078.0, float("nan")],
            }
        )
        p_home = np.array([0.6, 0.5, 0.7])

        matchups = runner._build_matchups(feature_frame, p_home)

        self.assertEqual(1, len(matchups))
        self.assertEqual([2080], matchups["home_team_id"].tolist())
        self.assertEqual([2074], matchups["away_team_id"].tolist())
        # p_home stayed aligned to the surviving row (not the dropped ones).
        self.assertAlmostEqual(0.6, float(matchups["p_home_wins"].iloc[0]))
        self.assertTrue(str(matchups["home_team_id"].dtype).startswith("int"))

    def test_all_teams_known_keeps_every_row_in_order(self) -> None:
        feature_frame = pd.DataFrame({"home_team_id": [1.0, 2.0], "away_team_id": [3.0, 4.0]})

        matchups = runner._build_matchups(feature_frame, np.array([0.4, 0.8]))

        self.assertEqual(2, len(matchups))
        self.assertEqual([0.4, 0.8], matchups["p_home_wins"].tolist())

    def test_empty_frame_yields_empty_matchups(self) -> None:
        empty = pd.DataFrame({"home_team_id": [], "away_team_id": []})

        matchups = runner._build_matchups(empty, np.zeros(0, dtype=float))

        self.assertTrue(matchups.empty)


class _ScriptedRng:
    """Deterministic stand-in: ``random()`` yields scripted values in order."""

    def __init__(self, values: list[float]) -> None:
        self._values = values
        self._i = 0

    def random(self) -> float:
        value = self._values[self._i]
        self._i += 1
        return value

    def shuffle(self, seq) -> None:  # identity — keep insertion order
        return None


class RoundRobinTieBreakTests(TestCase):
    def test_map_diff_breaks_equal_win_ties(self) -> None:
        # Two winners with one win each; team 1 wins by 2 maps, team 3 by 1.
        # Per match the ranker draws the winner first, then the margin (scaled
        # by the winner's win probability: 2*0.9-1 = 0.8).
        matches = [(1, 2, 0.9), (3, 4, 0.9)]
        # match1: win 0.0(<0.9 ⇒ home 1), margin 0.0(<0.8 ⇒ 2)
        # match2: win 0.0(<0.9 ⇒ home 3), margin 0.99(≥0.8 ⇒ 1)
        rng = _ScriptedRng([0.0, 0.0, 0.0, 0.99])

        standing = standings_v2._round_robin_standings([1, 2, 3, 4], matches, rng)

        self.assertEqual(1, standing[1])  # 1 win, +2 map diff
        self.assertEqual(2, standing[3])  # 1 win, +1 map diff
        self.assertEqual(3, standing[4])  # 0 wins, -1 map diff
        self.assertEqual(4, standing[2])  # 0 wins, -2 map diff

    def test_upset_win_is_narrow_so_expected_winner_outranks_it(self) -> None:
        # Both team 2 and team 3 finish with one win:
        #   - team 2 wins an UPSET (was a 0.1 underdog) ⇒ narrow 1-map margin
        #   - team 3 wins as EXPECTED (0.9 favourite)    ⇒ 2-map margin
        # The convincing winner must edge ahead on map differential.
        matches = [(1, 2, 0.9), (3, 4, 0.9)]
        # match1: win 0.95(≥0.9 ⇒ away 2 upsets), margin draw 0.0 (2*0.1-1<0 ⇒ 1)
        # match2: win 0.0(<0.9 ⇒ home 3 expected), margin 0.0(<0.8 ⇒ 2)
        rng = _ScriptedRng([0.95, 0.0, 0.0, 0.0])

        standing = standings_v2._round_robin_standings([1, 2, 3, 4], matches, rng)

        self.assertEqual(1, standing[3])  # expected winner, +2 map diff
        self.assertEqual(2, standing[2])  # upset winner, +1 map diff

    def test_win_count_dominates_map_diff(self) -> None:
        # Team 1 wins twice, team 2 once: more wins must outrank any map diff.
        matches = [(1, 2, 0.9), (1, 3, 0.9), (2, 3, 0.9)]
        rng = _ScriptedRng([0.0, 0.0] * 3)  # every margin 2, every home wins

        standing = standings_v2._round_robin_standings([1, 2, 3], matches, rng)

        self.assertEqual(1, standing[1])
        self.assertEqual(2, standing[2])
        self.assertEqual(3, standing[3])

    def test_produces_valid_permutation_with_real_rng(self) -> None:
        rng = np.random.default_rng(0)
        matches = [(1, 2, 0.7), (2, 3, 0.4), (1, 3, 0.55), (3, 4, 0.6), (1, 4, 0.8)]

        standing = standings_v2._round_robin_standings([1, 2, 3, 4], matches, rng)

        self.assertEqual({1, 2, 3, 4}, set(standing.keys()))
        self.assertEqual([1, 2, 3, 4], sorted(standing.values()))


class SharpenProbabilitiesTests(TestCase):
    """``_sharpen_probabilities`` pushes win-probabilities away from 0.5."""

    def test_k_one_is_noop(self) -> None:
        p = np.array([0.2, 0.5, 0.8])
        out = standings_v2._sharpen_probabilities(p, 1.0)
        np.testing.assert_allclose(out, p)

    def test_half_is_a_fixed_point(self) -> None:
        self.assertAlmostEqual(0.5, standings_v2._sharpen_probabilities(0.5, 3.0))

    def test_k_above_one_pushes_away_from_half(self) -> None:
        # Favourites get more confident, underdogs less — spread grows.
        self.assertGreater(standings_v2._sharpen_probabilities(0.6, 2.0), 0.6)
        self.assertLess(standings_v2._sharpen_probabilities(0.4, 2.0), 0.4)

    def test_symmetric_around_half(self) -> None:
        # sharpen(1 - p) == 1 - sharpen(p): no home/away bias.
        self.assertAlmostEqual(
            standings_v2._sharpen_probabilities(0.3, 2.5),
            1.0 - standings_v2._sharpen_probabilities(0.7, 2.5),
        )

    def test_monotonic_increasing(self) -> None:
        out = standings_v2._sharpen_probabilities(np.array([0.1, 0.3, 0.5, 0.7, 0.9]), 2.0)
        self.assertTrue(np.all(np.diff(out) > 0))

    def test_clamps_extremes_to_finite_open_interval(self) -> None:
        lo = standings_v2._sharpen_probabilities(0.0, 2.0)
        hi = standings_v2._sharpen_probabilities(1.0, 2.0)
        for v in (lo, hi):
            self.assertTrue(np.isfinite(v))
        self.assertGreater(lo, 0.0)
        self.assertLess(hi, 1.0)

    def test_scalar_returns_float_array_returns_ndarray(self) -> None:
        self.assertIsInstance(standings_v2._sharpen_probabilities(0.6, 2.0), float)
        self.assertIsInstance(standings_v2._sharpen_probabilities(np.array([0.6, 0.4]), 2.0), np.ndarray)


class SimulateStandingsSharpeningTests(TestCase):
    """Sharpening widens the spread of predicted places across teams."""

    @staticmethod
    def _round_robin_matchups(strengths: dict[int, float]) -> pd.DataFrame:
        # Mild logistic edges (slope 0.2) keep p_home near 0.5 — the
        # under-dispersed regime that collapses mean_position to the centre.
        teams = list(strengths)
        rows = []
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                home, away = teams[i], teams[j]
                diff = strengths[home] - strengths[away]
                p = 1.0 / (1.0 + np.exp(-0.2 * diff))
                rows.append((home, away, p))
        return pd.DataFrame(rows, columns=["home_team_id", "away_team_id", "p_home_wins"])

    def test_sharpening_widens_position_spread(self) -> None:
        strengths = {1: 5.0, 2: 4.0, 3: 3.0, 4: 2.0, 5: 1.0, 6: 0.0}
        teams = list(strengths)
        matchups = self._round_robin_matchups(strengths)

        base = standings_v2.simulate_standings(
            matchups, teams, n_iter=3000, rng=np.random.default_rng(0), prob_sharpening=1.0
        )
        sharp = standings_v2.simulate_standings(
            matchups, teams, n_iter=3000, rng=np.random.default_rng(0), prob_sharpening=2.0
        )

        base_spread = float(base["mean_position"].std())
        sharp_spread = float(sharp["mean_position"].std())
        self.assertGreater(sharp_spread, base_spread)
        # Every team still lands in a valid [1, n_teams] mean position.
        for frame in (base, sharp):
            self.assertTrue(((frame["mean_position"] >= 1.0) & (frame["mean_position"] <= 6.0)).all())

    def test_default_is_noop_identical_to_explicit_one(self) -> None:
        strengths = {1: 3.0, 2: 1.0, 3: 0.0}
        teams = list(strengths)
        matchups = self._round_robin_matchups(strengths)

        default = standings_v2.simulate_standings(matchups, teams, n_iter=1500, rng=np.random.default_rng(7))
        explicit = standings_v2.simulate_standings(
            matchups, teams, n_iter=1500, rng=np.random.default_rng(7), prob_sharpening=1.0
        )

        np.testing.assert_allclose(
            default.set_index("team_id")["mean_position"].to_numpy(),
            explicit.set_index("team_id")["mean_position"].to_numpy(),
        )
