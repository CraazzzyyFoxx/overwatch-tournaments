from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

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
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

analytics_flows = importlib.import_module("src.services.analytics.flows")


class AnalyticsWorkspaceScopeTests(IsolatedAsyncioTestCase):
    async def test_get_data_frame_passes_workspace_scope_to_history_queries(self) -> None:
        session = SimpleNamespace()

        with (
            patch.object(
                analytics_flows.service,
                "get_analytics",
                AsyncMock(return_value=[]),
            ) as get_analytics,
            patch.object(
                analytics_flows.service,
                "get_tournament_version_ids",
                AsyncMock(return_value={}),
            ) as get_tournament_version_ids,
        ):
            frame = await analytics_flows.get_data_frame(session, workspace_id=5)

        self.assertTrue(frame.empty)
        get_analytics.assert_awaited_once_with(session, workspace_id=5, workspace_ids=None)
        get_tournament_version_ids.assert_awaited_once_with(session, workspace_id=5, workspace_ids=None)

    async def test_compute_openskill_shift_map_passes_workspace_scope_to_match_history(self) -> None:
        session = SimpleNamespace()
        df = pd.DataFrame(
            [
                {
                    "version_id": None,
                    "tournament_id": 7,
                    "id_role": "1-tank",
                    "div": 4,
                    "player_id": 12,
                }
            ]
        )

        team = SimpleNamespace(players=[])

        with (
            patch.object(
                analytics_flows.service,
                "lookback_start_tournament_id",
                AsyncMock(return_value=3),
            ) as lookback_start,
            patch.object(
                analytics_flows.service,
                "get_matches",
                AsyncMock(return_value=[]),
            ) as get_matches,
            patch.object(
                analytics_flows.service,
                "get_teams_with_players",
                AsyncMock(return_value=[team]),
            ),
            patch.object(
                analytics_flows.service,
                "get_grid_versions",
                AsyncMock(return_value={}),
            ),
            patch.object(
                analytics_flows,
                "prepare_openskill_data",
                return_value=(set(), {}, []),
            ),
        ):
            shift_map, has_history = await analytics_flows.compute_openskill_shift_map(
                session,
                tournament_id=7,
                df=df,
                workspace_id=5,
            )

        self.assertEqual({}, shift_map)
        self.assertFalse(has_history)
        # The OpenSkill window is resolved chronologically (not tid-10) and the
        # workspace scope is threaded into both the lookup and the match query.
        lookback_start.assert_awaited_once_with(
            session,
            7,
            analytics_flows.OPENSKILL_LOOKBACK,
            workspace_id=5,
            workspace_ids=None,
        )
        get_matches.assert_awaited_once_with(session, 3, 7, workspace_id=5, workspace_ids=None)


class LookbackWindowTests(IsolatedAsyncioTestCase):
    """Unit tests for the chronological OpenSkill lookback window helper."""

    @staticmethod
    def _session_returning(ids: list[int]) -> SimpleNamespace:
        # ``lookback_start_tournament_id`` awaits ``session.scalars(...)`` and
        # then reads ``.all()`` off the result.
        scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: ids))
        return SimpleNamespace(scalars=scalars)

    async def test_returns_min_of_recent_ids_not_numeric_offset(self) -> None:
        service = importlib.import_module("src.services.analytics.service")
        # 10 most-recent tournaments up to #73, but ids are sparse: the oldest
        # in the window is #28, far from the naive 73 - 10 = 63.
        session = self._session_returning([73, 70, 64, 61, 55, 50, 44, 40, 33, 28])

        start = await service.lookback_start_tournament_id(session, 73, 10)

        self.assertEqual(28, start)
        self.assertNotEqual(63, start)  # would be the buggy tid - look_back

    async def test_falls_back_to_end_when_no_rows(self) -> None:
        service = importlib.import_module("src.services.analytics.service")
        session = self._session_returning([])

        start = await service.lookback_start_tournament_id(session, 73, 10)

        self.assertEqual(73, start)
