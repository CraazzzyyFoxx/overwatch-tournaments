"""Analytics and ML follow the tournament chronology key (spec 2026-11-05 §11.1), never the tournament id.

World: tournament 1 has the lowest id and starts last (March); 2 and 3 start together (February) and 3 ends first,
so the chronology is 3, 2, 1. SQLite stands in for Postgres as in ``test_hidden_tournament_exclusion``.
"""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

from shared import models  # noqa: E402
from tests import test_hidden_tournament_exclusion as hidden  # noqa: E402
from tests.test_hidden_tournament_exclusion import _Fixture  # noqa: E402

analytics_service = importlib.import_module("src.services.analytics.service").analytics_service
analytics_read_service = importlib.import_module("src.services.analytics.read_queries").analytics_read_service

FEB = datetime(2026, 2, 1, tzinfo=UTC)
FEB_2 = datetime(2026, 2, 2, tzinfo=UTC)
FEB_9 = datetime(2026, 2, 9, tzinfo=UTC)
MAR = datetime(2026, 3, 1, tzinfo=UTC)
WORLD = ((1, MAR, None), (2, FEB, FEB_9), (3, FEB, FEB_2))
CHRONOLOGY = [3, 2, 1]
USER = 100


class _ChronologyTestCase(IsolatedAsyncioTestCase):
    tables = hidden.TABLES

    def setUp(self) -> None:
        with patch.object(hidden, "TABLES", self.tables):
            self.db = _Fixture()
        self.addCleanup(self.db.close)

    def world(self, *, only: tuple[int, ...] = (1, 2, 3)) -> dict[int, int]:
        """The ``WORLD`` tournaments in ``only``, ``USER`` on a team of each; returns ``{tournament_id: team_id}``."""
        member = self.db.member(USER)
        teams: dict[int, int] = {}
        for tid, start, end in WORLD:
            if tid not in only:
                continue
            self.db.tournament(tid)
            self.db.session.execute(
                sa.update(models.Tournament).where(models.Tournament.id == tid).values(start_date=start, end_date=end)
            )
            teams[tid] = self.db.team(tid, f"t{tid}")
            self.db.player(tid, teams[tid], member, name=f"p{tid}")
        return teams


class AnalyticsFrameChronologyTests(_ChronologyTestCase):
    async def test_each_history_runs_in_chronology(self) -> None:
        self.world()
        rows = await analytics_service.get_analytics(self.db.shim, discipline="overwatch")
        self.assertEqual(CHRONOLOGY, [row["tournament_id"] for row in rows if row["user_id"] == USER])
        self.assertIn("ended_at", rows[0])


class StreaksChronologyTests(_ChronologyTestCase):
    tables = (*hidden.TABLES, models.User.__table__)

    def setUp(self) -> None:
        super().setUp()
        self.db.insert(models.User.__table__, id=USER, name="streaker")
        teams = self.world()
        member = self.db.session.scalar(
            sa.select(models.WorkspaceMember.id).where(models.WorkspaceMember.player_id == USER)
        )
        for tid, team in teams.items():
            self.db.insert(
                models.ParticipantResult.__table__,
                tournament_id=tid,
                workspace_member_id=member,
                final_team_id=team,
                placement=tid,
                field_size=1,
            )

    async def _positions(self, tournament_id: int) -> list[int]:
        rows = await analytics_read_service.get_streaks(self.db.shim, tournament_id)
        return [row[4] for row in rows if row[0].id == USER]

    async def test_positions_run_newest_first(self) -> None:
        self.assertEqual([1, 2, 3], await self._positions(1))

    async def test_the_cutoff_is_the_current_tournaments_place_in_the_chronology(self) -> None:
        # 1 has the lowest id but started after 2, so it is not in 2's history; 3 ended before 2, so it is.
        self.assertEqual([2, 3], await self._positions(2))


splits = importlib.import_module("src.services.ml.training.splits")
backfill = importlib.import_module("src.services.ml.inference.backfill")


class SplitsChronologyTests(_ChronologyTestCase):
    async def test_tournaments_up_to_a_cutoff_follow_the_key(self) -> None:
        self.world()
        up_to = {}
        for cutoff in (1, 2):
            up_to[cutoff] = [t.id for t in await splits.tournaments_up_to(self.db.shim, cutoff, discipline="overwatch")]
        # 3 ended before 2, so it precedes 2 although its id is higher; 1 started last.
        self.assertEqual({1: CHRONOLOGY, 2: [3, 2]}, up_to)


class BackfillChronologyTests(_ChronologyTestCase):
    async def _visited(self, start: date, end: date) -> list[int]:
        with patch.object(backfill, "run_for_tournament", AsyncMock(return_value={})):
            return list(await backfill.backfill_range(self.db.shim, from_date=start, to_date=end))

    async def test_a_date_range_is_swept_in_chronology(self) -> None:
        self.world()
        self.assertEqual(CHRONOLOGY, await self._visited(date(2026, 2, 1), date(2026, 3, 1)))
        # Whole UTC days: tournament 1 starts at 00:00 on March 1, the day after the range.
        self.assertEqual([3, 2], await self._visited(date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual([], await self._visited(date(2026, 3, 2), date(2026, 3, 1)))


evaluate = importlib.import_module("src.services.analytics.evaluate")
backtest = importlib.import_module("src.services.ml.training.backtest")


class TimelineChronologyTests(_ChronologyTestCase):
    async def test_lookback_window_follows_the_key(self) -> None:
        self.world()
        self.assertEqual(
            CHRONOLOGY, await analytics_service.lookback_tournament_ids(self.db.shim, 1, 5, discipline="overwatch")
        )
        self.assertEqual(
            [3, 2], await analytics_service.lookback_tournament_ids(self.db.shim, 2, 5, discipline="overwatch")
        )

    async def test_latest_tournament_breaks_a_start_tie_on_end_date(self) -> None:
        self.world(only=(2, 3))
        latest = await backtest._latest_tournament_id(self.db.shim, discipline="overwatch", workspace_id=None)
        self.assertEqual(2, latest)  # 3 has the higher id, 2 ends later

    async def test_evaluation_scope_follows_the_key(self) -> None:
        self.world()
        _, ids = await evaluate._scoped_tournaments(
            self.db.shim, discipline="overwatch", workspace_id=None, from_tournament_id=None, to_tournament_id=None
        )
        self.assertEqual(CHRONOLOGY, ids)

    async def test_replay_encounters_follow_the_key(self) -> None:
        for tid, team in self.world().items():
            self.db.encounter(tid, team, self.db.team(tid, f"away{tid}"))
        encounters = await analytics_service.get_matches_for_tournaments(
            self.db.shim, [1, 2, 3], discipline="overwatch"
        )
        self.assertEqual(CHRONOLOGY, [encounter.tournament_id for encounter in encounters])
