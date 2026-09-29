from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))


read_service = importlib.import_module("src.services.overwatch_rank.queries")
domain = importlib.import_module("src.domain.overwatch_rank")


def _snap(**kw):
    base = {
        "social_account_id": 1,
        "battle_tag": "A#1",
        "role": "tank",
        "platform": "pc",
        "rank_value": 2000,
        "division": "gold",
        "tier": 5,
        "is_ranked": True,
        "season": 13,
    }
    base.update(kw)
    return SimpleNamespace(**base)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    """``scalars`` answers the window query, then the opening-row query;
    ``execute`` answers the ``battle_tag_state`` poll lookup."""

    def __init__(self, rows, opening=(), polled=()):
        self._scalars = [list(rows), list(opening)]
        self._polled = list(polled)

    async def scalars(self, query):
        return FakeResult(self._scalars.pop(0))

    async def execute(self, query):
        return FakeResult(self._polled)


class RankSeriesTests(IsolatedAsyncioTestCase):
    async def test_groups_into_series_sorted_with_peak_and_current(self) -> None:
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        t1 = datetime(2026, 1, 2, tzinfo=UTC)
        t2 = datetime(2026, 1, 3, tzinfo=UTC)
        rows = [
            # tank series (out of order to verify sort), rising then peak in middle
            _snap(captured_at=t1, rank_value=2100),
            _snap(captured_at=t0, rank_value=2000),
            _snap(captured_at=t2, rank_value=2050),
            # a second series: support role
            _snap(role="support", captured_at=t0, rank_value=3000, division="diamond", tier=5),
        ]
        series = await read_service.get_rank_series(FakeSession(rows), user_id=1)

        self.assertEqual(len(series), 2)
        by_role = {s.role: s for s in series}
        tank = by_role["tank"]
        self.assertEqual([p.captured_at for p in tank.points], [t0, t1, t2])  # sorted asc
        self.assertEqual(tank.current.captured_at, t2)  # latest
        self.assertEqual(tank.peak_rank_value, 2100)  # max across points
        self.assertEqual(tank.latest_captured_at, t2)
        self.assertEqual(by_role["support"].peak_rank_value, 3000)

    async def test_unranked_points_excluded_from_peak(self) -> None:
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [_snap(captured_at=t0, rank_value=None, is_ranked=False, division=None, tier=None)]
        series = await read_service.get_rank_series(FakeSession(rows), user_id=1)
        self.assertEqual(len(series), 1)
        self.assertIsNone(series[0].peak_rank_value)
        self.assertFalse(series[0].current.is_ranked)

    async def test_rank_held_through_the_window_is_drawn_to_the_last_poll(self) -> None:
        # The only change predates the window; the account was polled since.
        before = datetime(2026, 1, 1, 12, tzinfo=UTC)
        date_from = datetime(2026, 1, 10, 8, tzinfo=UTC)
        polled = datetime(2026, 1, 12, 9, tzinfo=UTC)
        series = await read_service.get_rank_series(
            FakeSession([], opening=[_snap(captured_at=before)], polled=[(1, polled)]),
            user_id=1,
            date_from=date_from,
            date_to=datetime(2026, 1, 13, tzinfo=UTC),
            granularity="daily",
        )
        [tank] = series
        self.assertEqual(
            [p.captured_at for p in tank.points],
            [datetime(2026, 1, d, tzinfo=UTC) for d in (10, 11, 12)],
        )
        self.assertEqual({p.rank_value for p in tank.points}, {2000})
        self.assertEqual(tank.current.captured_at, before)  # the real row, not a filled one

    async def test_account_not_polled_inside_the_window_has_no_series(self) -> None:
        before = datetime(2026, 1, 1, tzinfo=UTC)
        series = await read_service.get_rank_series(
            FakeSession([], opening=[_snap(captured_at=before)], polled=[(1, before)]),
            user_id=1,
            date_from=datetime(2026, 1, 10, tzinfo=UTC),
            date_to=datetime(2026, 1, 13, tzinfo=UTC),
            granularity="daily",
        )
        self.assertEqual(series, [])


class FillRankSeriesTests(TestCase):
    def test_daily_bucket_carries_the_state_it_closes_on(self) -> None:
        day = datetime(2026, 1, 5, tzinfo=UTC)
        changes = [day - timedelta(days=3), day + timedelta(hours=2), day + timedelta(hours=20)]
        filled = domain.fill_rank_series(changes, start=day, end=day + timedelta(days=1, hours=1), granularity="daily")
        # Two changes on the 5th: that day shows the later; the 6th carries it on.
        self.assertEqual(filled, [(day, 2), (day + timedelta(days=1), 2)])

    def test_hourly_stamps_are_bucket_starts_whatever_the_window_start(self) -> None:
        start = datetime(2026, 1, 5, 10, 37, tzinfo=UTC)
        filled = domain.fill_rank_series(
            [datetime(2026, 1, 1, tzinfo=UTC)], start=start, end=start + timedelta(hours=1), granularity="hourly"
        )
        self.assertEqual([at for at, _ in filled], [datetime(2026, 1, 5, h, tzinfo=UTC) for h in (10, 11)])

    def test_raw_moves_the_opening_state_to_start_and_repeats_the_latest_at_end(self) -> None:
        start = datetime(2026, 1, 5, tzinfo=UTC)
        change = start + timedelta(hours=5)
        end = start + timedelta(days=1)
        filled = domain.fill_rank_series([start - timedelta(days=2), change], start=start, end=end, granularity="raw")
        self.assertEqual(filled, [(start, 0), (change, 1), (end, 1)])


class CurrentRanksTests(IsolatedAsyncioTestCase):
    async def test_maps_rows_to_current_ranks(self) -> None:
        rows = [
            _snap(captured_at=datetime(2026, 1, 3, tzinfo=UTC)),
            _snap(role="support", captured_at=datetime(2026, 1, 3, tzinfo=UTC)),
        ]
        ranks = await read_service.get_current_ranks(FakeSession(rows), user_id=1)
        self.assertEqual(len(ranks), 2)
        self.assertEqual({r.role for r in ranks}, {"tank", "support"})
        self.assertTrue(all(r.battle_tag == "A#1" for r in ranks))
