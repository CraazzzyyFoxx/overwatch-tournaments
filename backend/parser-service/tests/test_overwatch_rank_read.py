from __future__ import annotations

import importlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "x")
os.environ.setdefault("CHALLONGE_API_KEY", "x")

read_service = importlib.import_module("src.services.overwatch_rank.read_service")


def _snap(**kw):
    base = {
        "battle_tag_id": 1,
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


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def scalars(self, query):
        return FakeScalars(self._rows)


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
