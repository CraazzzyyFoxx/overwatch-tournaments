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
sys.path.insert(0, str(backend_root / "parser-service"))

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
        get_analytics.assert_awaited_once_with(session, workspace_id=5)
        get_tournament_version_ids.assert_awaited_once_with(session, workspace_id=5)

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
                "get_matches",
                AsyncMock(return_value=[]),
            ) as get_matches,
            patch.object(
                analytics_flows.team_service,
                "get_by_tournament",
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
        get_matches.assert_awaited_once_with(session, -3, 7, workspace_id=5)
