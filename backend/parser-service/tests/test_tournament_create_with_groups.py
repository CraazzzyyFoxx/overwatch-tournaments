from __future__ import annotations

import importlib
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

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

tournament_flows = importlib.import_module("src.services.tournament.flows")


class TournamentCreateWithGroupsTests(IsolatedAsyncioTestCase):
    async def test_create_with_groups_uses_workspace_default_division_grid_when_missing(self) -> None:
        session = SimpleNamespace()
        created_tournament = SimpleNamespace(id=123)
        loaded_tournament = SimpleNamespace(id=123)
        challonge_tournament = SimpleNamespace(
            id=50,
            name="Imported",
            description="Desc",
            url="challonge-url",
            grand_finals_modifier="single match",
        )

        with (
            patch.object(tournament_flows.service, "get_by_number", AsyncMock(return_value=None)),
            patch.object(
                tournament_flows,
                "get_workspace_division_grid_version_id",
                AsyncMock(return_value=77),
            ) as get_default_version,
            patch.object(
                tournament_flows.challonge_service,
                "fetch_tournament",
                AsyncMock(return_value=challonge_tournament),
            ),
            patch.object(
                tournament_flows.service,
                "create",
                AsyncMock(return_value=created_tournament),
            ) as create_tournament,
            patch.object(
                tournament_flows.service,
                "get",
                AsyncMock(return_value=loaded_tournament),
            ),
            patch.object(
                tournament_flows,
                "create_groups",
                AsyncMock(return_value=loaded_tournament),
            ) as create_groups,
        ):
            result = await tournament_flows.create_with_groups(
                session,
                workspace_id=10,
                number=4,
                is_league=False,
                start_date=date(2026, 4, 17),
                end_date=date(2026, 4, 18),
                challonge_slug="slug",
            )

        self.assertIs(result, loaded_tournament)
        get_default_version.assert_awaited_once_with(session, 10)
        create_tournament.assert_awaited_once_with(
            session,
            workspace_id=10,
            number=4,
            is_league=False,
            name="Imported",
            description="Desc",
            challonge_id=50,
            challonge_slug="challonge-url",
            start_date=date(2026, 4, 17),
            end_date=date(2026, 4, 18),
            division_grid_version_id=77,
        )
        create_groups.assert_awaited_once_with(session, loaded_tournament, challonge_tournament)

    async def test_create_with_groups_uses_explicit_division_grid_when_provided(self) -> None:
        session = SimpleNamespace()
        created_tournament = SimpleNamespace(id=123)
        loaded_tournament = SimpleNamespace(id=123)
        challonge_tournament = SimpleNamespace(
            id=50,
            name="Imported",
            description="Desc",
            url="challonge-url",
            grand_finals_modifier="single match",
        )

        with (
            patch.object(tournament_flows.service, "get_by_number", AsyncMock(return_value=None)),
            patch.object(
                tournament_flows,
                "get_workspace_division_grid_version_id",
                AsyncMock(),
            ) as get_default_version,
            patch.object(
                tournament_flows.challonge_service,
                "fetch_tournament",
                AsyncMock(return_value=challonge_tournament),
            ),
            patch.object(
                tournament_flows.service,
                "create",
                AsyncMock(return_value=created_tournament),
            ) as create_tournament,
            patch.object(
                tournament_flows.service,
                "get",
                AsyncMock(return_value=loaded_tournament),
            ),
            patch.object(
                tournament_flows,
                "create_groups",
                AsyncMock(return_value=loaded_tournament),
            ),
        ):
            await tournament_flows.create_with_groups(
                session,
                workspace_id=10,
                number=4,
                is_league=False,
                start_date=date(2026, 4, 17),
                end_date=date(2026, 4, 18),
                challonge_slug="slug",
                division_grid_version_id=88,
            )

        get_default_version.assert_not_awaited()
        create_tournament.assert_awaited_once()
        self.assertEqual(88, create_tournament.await_args.kwargs["division_grid_version_id"])
