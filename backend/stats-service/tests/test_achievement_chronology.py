"""Achievement timelines and rule cutoffs follow the tournament chronology (spec 2026-11-05 §11.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_scrim_achievement_isolation import (
    IS_CAPTAIN_RULE,
    REAL_HOME_USER,
    WORKSPACE_ID,
    _EngineTestCase,
    achievement,
    evaluator,
    runner,
)

JAN = datetime(2026, 1, 1, tzinfo=UTC)
FEB = datetime(2026, 2, 1, tzinfo=UTC)
FEB_2 = datetime(2026, 2, 2, tzinfo=UTC)
FEB_9 = datetime(2026, 2, 9, tzinfo=UTC)
FEB_20 = datetime(2026, 2, 20, tzinfo=UTC)
MAR = datetime(2026, 3, 1, tzinfo=UTC)
WIN_STREAK = {"type": "consecutive", "params": {"metric": "win", "min_streak": 2}}


class ConsecutiveChronologyTests(_EngineTestCase):
    def _season(self, *, lost_ends: datetime) -> None:
        """Wins in 3 (January) and 1 (February, ends Feb 9); 2 starts with 1, ends ``lost_ends`` and is lost."""
        for tid, start, end in ((1, FEB, FEB_9), (2, FEB, lost_ends), (3, JAN, None)):
            self.db.tournament(tid, name=f"T{tid}", is_hidden=False, start=start, end=end)
            parts = self.db.rostered_tournament(tid)
            if tid != 2:
                self.db.winning_standing(tid, parts["home"])
        self.db.session.commit()

    async def test_a_start_tie_is_ordered_by_end_date(self) -> None:
        # 2 ends before 1: win (3), loss (2), win (1) -- no two wins in a row.
        self._season(lost_ends=FEB_2)
        self.assertEqual(set(), await evaluator.evaluate(self.db.shim, WIN_STREAK, await self.context(None)))

    async def test_a_lower_id_that_started_later_comes_later(self) -> None:
        # 3 has the highest id but started first; 2 ends after 1: win (3), win (1), loss (2).
        self._season(lost_ends=FEB_20)
        self.assertEqual(
            {(REAL_HOME_USER,)}, await evaluator.evaluate(self.db.shim, WIN_STREAK, await self.context(None))
        )


class RuleCutoffChronologyTests(_EngineTestCase):
    def _two_tournaments(self, *, cutoff: int) -> None:
        # 1 has the lowest id and starts in March; 3 started in January.
        for tid, start in ((1, MAR), (3, JAN)):
            self.db.tournament(tid, name=f"T{tid}", is_hidden=False, start=start)
            self.db.rostered_tournament(tid)
        self.db.rule(1, "captain", IS_CAPTAIN_RULE, ["tournament.encounter"], min_tournament_id=cutoff)
        self.db.session.commit()

    async def _created(self, tournament_id: int) -> int:
        """Results the run would create. ``diff_and_apply`` is stubbed: persisting uses Postgres-only SQL."""

        async def diff_and_apply(_session, _rule, results, *_args, **_kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            return SimpleNamespace(to_insert=results, to_delete=[])

        with patch.object(runner, "diff_and_apply", diff_and_apply):
            run = await runner.run_evaluation(
                self.db.shim,
                WORKSPACE_ID,
                achievement.EvaluationRunTrigger.parse_complete,
                tournament_id=tournament_id,
                changed_tables=["tournament.encounter"],
            )
        return run.results_created

    async def test_a_tournament_that_started_before_the_cutoff_is_skipped(self) -> None:
        self._two_tournaments(cutoff=1)
        self.assertEqual(0, await self._created(3))
        self.assertGreater(await self._created(1), 0)

    async def test_a_cutoff_tournament_that_no_longer_exists_does_not_skip(self) -> None:
        self._two_tournaments(cutoff=999)
        self.assertGreater(await self._created(3), 0)
