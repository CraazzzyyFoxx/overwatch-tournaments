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
