from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from cashews import cache

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "app-service"))

hero_stats_refresh = importlib.import_module("src.services.hero_stats_refresh")
refresher = hero_stats_refresh.hero_stats_refresh_service


class _FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value


class _FakeSession:
    """Records executed SQL; answers the two probe queries the refresh issues."""

    def __init__(self, *, got_lock: bool = True, populated: bool = True) -> None:
        self.statements: list[str] = []
        self.committed = False
        self._got_lock = got_lock
        self._populated = populated

    async def execute(self, clause: object) -> _FakeResult:
        sql = str(clause)
        self.statements.append(sql)
        if "pg_try_advisory_xact_lock" in sql:
            return _FakeResult(self._got_lock)
        if "relispopulated" in sql:
            return _FakeResult(self._populated)
        return _FakeResult(None)

    async def commit(self) -> None:
        self.committed = True


class _SessionMaker:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _SessionMaker:
        return self

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *_exc: object) -> None:
        return None


class HeroGlobalStatsRefreshTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        cache.setup("mem://", prefix="backend:")
        await cache.delete(hero_stats_refresh._COOLDOWN_KEY)

    async def test_work_mem_is_raised_transaction_locally_before_the_refresh(self) -> None:
        session = _FakeSession()

        await refresher.refresh(session)

        work_mem = [s for s in session.statements if "work_mem" in s]
        self.assertEqual(["SET LOCAL work_mem = '768MB'"], work_mem)
        # SET (not SET LOCAL) would leak into unrelated clients through pgBouncer's
        # transaction pooling.
        self.assertTrue(all(s.startswith("SET LOCAL ") for s in session.statements if s.startswith("SET ")))
        self.assertLess(
            session.statements.index(work_mem[0]),
            next(i for i, s in enumerate(session.statements) if s.startswith("REFRESH MATERIALIZED VIEW")),
        )
        self.assertTrue(session.committed)

    async def test_nested_loops_are_disabled_before_the_refresh(self) -> None:
        # The view's ``eligible`` CTE self-joins matches.statistics; the nested-loop
        # plan costs 2.5M buffer touches and twice the wall clock of the hash join
        # (measured: 15.0s -> 7.5s on a production restore). Ordering matters —
        # after the REFRESH the setting would apply to nothing.
        session = _FakeSession()

        await refresher.refresh(session)

        self.assertIn("SET LOCAL enable_nestloop = off", session.statements)
        self.assertLess(
            session.statements.index("SET LOCAL enable_nestloop = off"),
            next(i for i, s in enumerate(session.statements) if s.startswith("REFRESH MATERIALIZED VIEW")),
        )

    async def test_second_request_in_the_window_is_debounced(self) -> None:
        refresh = AsyncMock(return_value=True)
        maker = _SessionMaker(_FakeSession())

        with patch.object(refresher, "refresh", refresh):
            await refresher._run_refresh(maker, MagicMock())
            await refresher._run_refresh(maker, MagicMock())

        self.assertEqual(1, refresh.await_count)

    async def test_failed_refresh_releases_the_window(self) -> None:
        refresh = AsyncMock(side_effect=[RuntimeError("boom"), True])
        maker = _SessionMaker(_FakeSession())
        logger = MagicMock()

        with patch.object(refresher, "refresh", refresh):
            await refresher._run_refresh(maker, logger)
            await refresher._run_refresh(maker, logger)

        self.assertEqual(2, refresh.await_count)
        logger.exception.assert_called_once()
