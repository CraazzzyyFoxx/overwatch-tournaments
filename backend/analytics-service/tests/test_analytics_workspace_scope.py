from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import pandas as pd

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))


analytics_flows = importlib.import_module("src.services.analytics.flows")


class AnalyticsWorkspaceScopeTests(IsolatedAsyncioTestCase):
    async def test_get_data_frame_passes_workspace_scope_to_history_queries(self) -> None:
        session = SimpleNamespace()

        with (
            patch.object(
                analytics_flows.analytics_service,
                "get_analytics",
                AsyncMock(return_value=[]),
            ) as get_analytics,
            patch.object(
                analytics_flows.analytics_service,
                "get_tournament_version_ids",
                AsyncMock(return_value={}),
            ) as get_tournament_version_ids,
        ):
            frame = await analytics_flows.flows_service.get_data_frame(session, workspace_id=5, discipline="overwatch")

        self.assertTrue(frame.empty)
        get_analytics.assert_awaited_once_with(session, workspace_id=5, workspace_ids=None, discipline="overwatch")
        get_tournament_version_ids.assert_awaited_once_with(
            session, workspace_id=5, workspace_ids=None, discipline="overwatch"
        )

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
                analytics_flows.analytics_service,
                "lookback_tournament_ids",
                AsyncMock(return_value=[3, 7]),
            ) as lookback,
            patch.object(
                analytics_flows.analytics_service,
                "get_matches_for_tournaments",
                AsyncMock(return_value=[]),
            ) as get_matches,
            patch.object(
                analytics_flows.analytics_service,
                "get_teams_with_players",
                AsyncMock(return_value=[team]),
            ),
            patch.object(
                analytics_flows,
                "prepare_openskill_data",
                return_value=(set(), {}, []),
            ),
        ):
            shift_map, has_history = await analytics_flows.flows_service.compute_openskill_shift_map(
                session,
                tournament_id=7,
                df=df,
                workspace_id=5,
                discipline="overwatch",
            )

        self.assertEqual({}, shift_map)
        self.assertFalse(has_history)
        # The OpenSkill window is resolved by start date (an explicit id list, not an id interval) and the
        # workspace scope is threaded into both the lookup and the match query.
        lookback.assert_awaited_once_with(
            session,
            7,
            analytics_flows.OPENSKILL_LOOKBACK,
            workspace_id=5,
            workspace_ids=None,
            discipline="overwatch",
        )
        get_matches.assert_awaited_once_with(
            session, [3, 7], workspace_id=5, workspace_ids=None, discipline="overwatch"
        )

    async def test_previous_cost_skips_an_unranked_tournament(self) -> None:
        rows = [
            {
                "tournament_id": tid,
                "started_at": datetime(2026, 1, tid, tzinfo=UTC),
                "team_id": tid,
                "player_name": "p",
                "player_id": tid,
                "user_id": 1,
                "role": "tank",
                "rank": rank,
                "wins": 2,
                "losses": 1,
                "match_count": 3,
                "overall_position": None,
                "team_count": None,
                "performance_points": None,
            }
            for tid, rank in ((1, 2500), (2, None), (3, 2600))
        ]
        with (
            patch.object(analytics_flows.analytics_service, "get_analytics", AsyncMock(return_value=rows)),
            patch.object(analytics_flows.analytics_service, "get_tournament_version_ids", AsyncMock(return_value={})),
            patch.object(analytics_flows, "load_source_grids", AsyncMock(return_value={})),
        ):
            frame = await analytics_flows.flows_service.get_data_frame(SimpleNamespace(), discipline="overwatch")

        unranked, last = (frame.loc[frame["tournament_id"] == tid].iloc[0] for tid in (2, 3))
        self.assertTrue(pd.isna(unranked["div"]))
        self.assertTrue(pd.isna(unranked["previous_cost"]))
        self.assertFalse(unranked["is_changed"])
        self.assertTrue(pd.isna(unranked["normalized_shift_one"]))
        self.assertEqual(2500, last["previous_cost"])
        self.assertEqual(frame.loc[frame["tournament_id"] == 1, "div"].iloc[0], last["previous_div"])
