from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from src import models, schemas  # noqa: E402
from src.services.encounter import flows, service  # noqa: E402


class EncounterRedesignFilterTests(TestCase):
    def test_my_team_scope_joins_auth_linked_player(self) -> None:
        params = schemas.EncounterSearchParams(scope="my_team")

        query = service._encounter_ids_query(params, viewer_auth_user_id=42)
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))

        self.assertIn("tournament.player", compiled)
        self.assertIn("auth.user_player", compiled)
        self.assertIn("auth_user_id = 42", compiled)

    def test_my_team_scope_without_user_returns_empty_filter(self) -> None:
        params = schemas.EncounterSearchParams(scope="my_team")

        query = service._encounter_ids_query(params, viewer_auth_user_id=None)
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))

        self.assertTrue("false" in compiled.lower() or "0 = 1" in compiled)

    def test_list_filter_query_includes_requested_filters(self) -> None:
        params = schemas.EncounterSearchParams(
            tournament_id=1,
            stage_id=2,
            stage_item_id=3,
            best_of=5,
            status="completed",
            has_logs=True,
            closeness_min=0.25,
            closeness_max=0.9,
        )

        query = service._encounter_ids_query(params, workspace_id=7)
        compiled = str(query.compile(compile_kwargs={"literal_binds": True})).lower()

        self.assertIn("encounter.tournament_id = 1", compiled)
        self.assertIn("encounter.stage_id = 2", compiled)
        self.assertIn("encounter.stage_item_id = 3", compiled)
        self.assertIn("encounter.best_of = 5", compiled)
        self.assertIn("encounter.status = 'completed'", compiled)
        self.assertIn("encounter.has_logs is true", compiled)
        self.assertIn("encounter.closeness >= 0.25", compiled)
        self.assertIn("encounter.closeness <= 0.9", compiled)
        self.assertIn("tournament.workspace_id = 7", compiled)


class _EmptyScalarResult:
    def scalar_one_or_none(self):
        return None


class _EmptyMatchResult:
    def unique(self):
        return self

    def scalars(self):
        return self

    def first(self):
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.query = None

    async def execute(self, query):
        self.query = query
        return _EmptyScalarResult()


class EncounterRedesignSerializationTests(IsolatedAsyncioTestCase):
    async def test_get_match_applies_workspace_filter(self) -> None:
        session = _FakeSession()
        session.execute = AsyncMock(return_value=_EmptyMatchResult())

        result = await service.get_match(cast(AsyncSession, session), 6748, [], workspace_id=2)

        self.assertIsNone(result)
        compiled = str(session.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("match.id = 6748", compiled)
        self.assertIn("join tournament.encounter", compiled)
        self.assertIn("join tournament.tournament", compiled)
        self.assertIn("tournament.workspace_id = 2", compiled)

    async def test_delete_saved_view_is_scoped_to_owner_and_workspace(self) -> None:
        session = _FakeSession()

        with self.assertRaises(HTTPException) as exc:
            await service.delete_saved_view(
                cast(AsyncSession, session),
                workspace_id=7,
                auth_user_id=42,
                saved_view_id=11,
            )

        self.assertEqual(exc.exception.status_code, 404)
        compiled = str(session.query.compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("encounter_saved_view.id = 11", compiled)
        self.assertIn("encounter_saved_view.workspace_id = 7", compiled)
        self.assertIn("encounter_saved_view.auth_user_id = 42", compiled)

    async def test_saved_view_serializer_normalizes_filter_defaults(self) -> None:
        saved_view = models.EncounterSavedView(
            id=11,
            workspace_id=7,
            auth_user_id=42,
            name="Close Bo5",
            filters_json={"query": "final", "scope": "my_team", "closeness_min": 0.8},
            sort_order=2,
        )

        read = flows._saved_view_to_read(saved_view)

        self.assertEqual(read.id, 11)
        self.assertEqual(read.workspace_id, 7)
        self.assertEqual(read.name, "Close Bo5")
        self.assertEqual(read.filters.query, "final")
        self.assertEqual(read.filters.scope, "my_team")
        self.assertEqual(read.filters.sort, "date")
        self.assertEqual(read.filters.closeness_min, 0.8)

    async def test_overview_maps_service_data_to_public_schema(self) -> None:
        raw = {
            "total": 10,
            "recent_count": 3,
            "with_logs_count": 4,
            "avg_closeness": 0.625,
            "live_now_count": 0,
            "upcoming_count": 2,
            "histogram_rows": [(6, 4), (9, 1)],
            "score_rows": [(2, 0, 5), (2, 1, 3)],
            "stage_rows": [("Group", 7), ("Final", 3)],
            "hot_map_rows": [("King's Row", 6)],
            "avg_series_seconds": 2520.0,
            "completed_series_count": 8,
            "sweep_count": 2,
            "went_distance_count": 3,
            "home_wins": 5,
            "away_wins": 3,
            "closest": [],
            "upcoming": [],
            "live": [],
            "preset_counts": {
                "all": 10,
                "my_team": 0,
                "finals": 3,
                "close_bo5": 1,
                "upsets": 0,
                "with_logs": 4,
            },
        }

        with patch.object(service, "get_overview_data", AsyncMock(return_value=raw)):
            read = await flows.get_encounters_overview(
                cast(AsyncSession, object()),
                schemas.EncounterSearchParams(),
            )

        self.assertEqual(read.kpis.total_encounters, 10)
        self.assertEqual(read.kpis.with_logs_pct, 40.0)
        self.assertEqual(read.kpis.avg_closeness, 62.5)
        self.assertEqual(read.closeness_histogram[6].count, 4)
        self.assertEqual(read.score_heatmap[0].home, 2)
        self.assertEqual(read.stage_split[1].pct, 30.0)
        self.assertEqual(read.pulse.sweep_rate, 25.0)
        self.assertEqual(read.side_balance.home_win_pct, 62.5)
