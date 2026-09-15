"""Challonge score translation, both directions.

``scores_csv`` is a comma-separated list of per-set results, so reading only
the first pair handed the series to whoever won set one. And on export an equal
score fell into the ``else`` branch, shipping a draw to Challonge as an away
win instead of its documented ``winner_id="tie"``.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

sync = importlib.import_module("src.services.challonge.sync")


class ParseScores(TestCase):
    def test_single_pair_is_the_series_score(self) -> None:
        self.assertEqual((3, 1), sync._parse_scores("3-1"))

    def test_multiple_pairs_reduce_to_sets_won(self) -> None:
        # Lost set one, won the next two: the series is 2-1 to home.
        self.assertEqual((2, 1), sync._parse_scores("0-1,1-0,2-1"))

    def test_drawn_set_counts_for_nobody(self) -> None:
        self.assertEqual((1, 1), sync._parse_scores("0-1,1-0,2-2"))

    def test_forfeit_pair_is_ignored(self) -> None:
        # A negative number is Challonge's forfeit marker: "0--1" must not read
        # as a home set win, and "-1--1" must not read as a draw either.
        self.assertEqual((1, 1), sync._parse_scores("0-1,1-0,0--1"))
        self.assertEqual((1, 0), sync._parse_scores("1-0,-1--1"))

    def test_no_pairs(self) -> None:
        self.assertEqual((0, 0), sync._parse_scores(None))
        self.assertEqual((0, 0), sync._parse_scores(""))


class PushTie(IsolatedAsyncioTestCase):
    async def test_equal_score_exports_as_tie(self) -> None:
        source = sync._ImportSource(challonge_id=777, source_id=5)
        encounter = SimpleNamespace(
            id=10,
            home_score=1,
            away_score=1,
            home_team=SimpleNamespace(id=1),
            away_team=SimpleNamespace(id=2),
        )
        session = SimpleNamespace(commit=AsyncMock())
        service = sync.sync_service

        update_match = AsyncMock()
        resolve_winner = AsyncMock(return_value=42)
        with (
            patch.object(service, "_resolve_export_target", AsyncMock(return_value=(source, 99))),
            patch.object(service, "_resolve_winner_challonge_id", resolve_winner),
            patch.object(service.sync_log, "_log_sync", AsyncMock()),
            patch.object(sync.challonge_client, "update_match", update_match),
        ):
            pushed = await service.push_single_result(session, SimpleNamespace(id=1), encounter)

        self.assertTrue(pushed)
        resolve_winner.assert_not_awaited()
        update_match.assert_awaited_once_with(777, 99, scores_csv="1-1", winner_id="tie")
        session.commit.assert_awaited_once()
