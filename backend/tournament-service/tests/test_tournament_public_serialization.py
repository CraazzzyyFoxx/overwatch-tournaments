from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient_to_detached

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
from src.core import enums  # noqa: E402
from src.services.team import service as team_service  # noqa: E402
from src.services.tournament import flows, service  # noqa: E402


def _tournament() -> models.Tournament:
    return models.Tournament(
        id=1,
        created_at=datetime.now(UTC),
        updated_at=None,
        workspace_id=1,
        number=10,
        name="Tournament 10",
        description=None,
        is_league=False,
        is_finished=False,
        is_hidden=False,
        status=enums.TournamentStatus.LIVE,
        start_date=datetime.now(UTC),
        end_date=datetime.now(UTC),
        registration_opens_at=None,
        registration_closes_at=None,
        check_in_opens_at=None,
        check_in_closes_at=None,
        win_points=1.0,
        draw_points=0.5,
        loss_points=0.0,
        team_formation="balancer",
        division_grid_version_id=5,
    )


class TournamentSerializationTests(IsolatedAsyncioTestCase):
    async def test_to_pydantic_does_not_touch_unrequested_division_grid_version(self) -> None:
        tournament = _tournament()
        make_transient_to_detached(tournament)

        read = await flows.to_pydantic(cast(AsyncSession, object()), tournament, [])

        self.assertEqual(5, read.division_grid_version_id)
        self.assertIsNone(read.division_grid_version)

    async def test_to_pydantic_resolves_requested_teams_count(self) -> None:
        tournament = _tournament()
        make_transient_to_detached(tournament)
        session = cast(AsyncSession, object())
        count_boundary = AsyncMock(return_value=20)

        with patch.object(
            team_service,
            "get_team_count_by_tournament",
            count_boundary,
        ):
            read = await flows.to_pydantic(
                session,
                tournament,
                ["teams_count"],
            )

        self.assertEqual(20, read.teams_count)
        count_boundary.assert_awaited_once_with(session, tournament.id)

    async def test_to_pydantic_leaves_unrequested_teams_count_unresolved(self) -> None:
        tournament = _tournament()
        make_transient_to_detached(tournament)
        unexpected_count = AsyncMock(side_effect=AssertionError("unrequested count query"))

        with patch.object(
            team_service,
            "get_team_count_by_tournament",
            unexpected_count,
        ):
            read = await flows.to_pydantic(cast(AsyncSession, object()), tournament, [])

        self.assertIsNone(read.teams_count)
        unexpected_count.assert_not_awaited()

    async def test_bulk_team_count_skips_database_for_empty_tournament_ids(self) -> None:
        result = await team_service.get_team_count_by_tournament_bulk(
            cast(AsyncSession, object()),
            [],
        )

        self.assertEqual({}, result)

    async def test_get_all_uses_bulk_teams_counts_for_requested_entity(self) -> None:
        tournament = _tournament()
        second_tournament = _tournament()
        second_tournament.id = 2
        second_tournament.number = 11
        second_tournament.name = "Tournament 11"
        make_transient_to_detached(tournament)
        make_transient_to_detached(second_tournament)
        params = schemas.TournamentPaginationSortSearchParams(entities=["teams_count"])
        session = cast(AsyncSession, object())
        bulk_count_boundary = AsyncMock(return_value={tournament.id: 20, second_tournament.id: 16})
        unexpected_singular_count = AsyncMock(side_effect=AssertionError("N+1 team count query"))

        with (
            patch.object(
                flows.service,
                "get_all",
                AsyncMock(return_value=([tournament, second_tournament], 2)),
            ),
            patch.object(flows, "resolve_tournament_challonge", AsyncMock(return_value={})),
            patch.object(team_service, "get_team_count_by_tournament_bulk", bulk_count_boundary),
            patch.object(
                team_service,
                "get_team_count_by_tournament",
                unexpected_singular_count,
            ),
        ):
            page = await flows.get_all(session, params)

        self.assertEqual([20, 16], [item.teams_count for item in page.results])
        bulk_count_boundary.assert_awaited_once_with(session, [tournament.id, second_tournament.id])
        unexpected_singular_count.assert_not_awaited()

    async def test_get_all_skips_bulk_teams_count_when_unrequested(self) -> None:
        tournament = _tournament()
        make_transient_to_detached(tournament)
        params = schemas.TournamentPaginationSortSearchParams()
        session = cast(AsyncSession, object())
        unexpected_bulk_count = AsyncMock(side_effect=AssertionError("unrequested bulk count query"))

        with (
            patch.object(flows.service, "get_all", AsyncMock(return_value=([tournament], 1))),
            patch.object(flows, "resolve_tournament_challonge", AsyncMock(return_value={})),
            patch.object(team_service, "get_team_count_by_tournament_bulk", unexpected_bulk_count),
        ):
            page = await flows.get_all(session, params)

        self.assertIsNone(page.results[0].teams_count)
        unexpected_bulk_count.assert_not_awaited()


class TournamentLoadOptionTests(TestCase):
    def test_stages_load_options_stay_summary_only(self) -> None:
        paths = "\n".join(str(getattr(option, "path", "")) for option in service.tournament_entities(["stages"]))

        self.assertIn("Tournament.stages", paths)
        self.assertNotIn("Stage.items", paths)
        self.assertNotIn("StageItem.inputs", paths)

    def test_division_grid_version_is_explicit_load_option(self) -> None:
        paths = "\n".join(
            str(getattr(option, "path", "")) for option in service.tournament_entities(["division_grid_version"])
        )

        self.assertIn("Tournament.division_grid_version", paths)
