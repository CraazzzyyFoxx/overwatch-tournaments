from __future__ import annotations

import importlib
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ["DEBUG"] = "false"
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
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

admin_schemas = importlib.import_module("src.schemas.admin.tournament")
admin_tournament_service = importlib.import_module("src.services.admin.tournament")
models = importlib.import_module("src.models")
enums = importlib.import_module("shared.core.enums")


class AdminTournamentServiceTests(IsolatedAsyncioTestCase):
    async def test_create_uses_workspace_default_division_grid_version_when_missing(self) -> None:
        existing_result = Mock()
        existing_result.scalar_one_or_none.return_value = None

        session = SimpleNamespace(
            execute=AsyncMock(return_value=existing_result),
            scalar=AsyncMock(return_value=None),
            add=Mock(side_effect=lambda tournament: setattr(tournament, "id", 123)),
            commit=AsyncMock(),
        )
        data = admin_schemas.TournamentCreate(
            workspace_id=10,
            number=4,
            name="Test",
            is_league=False,
            start_date=date(2026, 4, 17),
            end_date=date(2026, 4, 18),
        )

        with (
            patch.object(
                admin_tournament_service,
                "get_workspace_division_grid_version_id",
                AsyncMock(return_value=77),
            ) as get_default_version,
            patch.object(
                admin_tournament_service,
                "get_tournament",
                AsyncMock(return_value="created"),
            ) as get_tournament,
            patch.object(
                admin_tournament_service.division_grid_cache,
                "invalidate_tournament",
                AsyncMock(),
            ) as invalidate_tournament,
            patch.object(
                admin_tournament_service.division_grid_cache,
                "invalidate_workspace",
                AsyncMock(),
            ) as invalidate_workspace,
        ):
            result = await admin_tournament_service.create_tournament(session, data)

        self.assertEqual("created", result)
        created_tournament = session.add.call_args.args[0]
        self.assertEqual(77, created_tournament.division_grid_version_id)
        get_default_version.assert_awaited_once_with(session, 10)
        session.commit.assert_awaited_once_with()
        invalidate_tournament.assert_awaited_once_with(123)
        invalidate_workspace.assert_awaited_once_with(10)
        get_tournament.assert_awaited_once_with(session, 123)

    async def test_update_uses_workspace_default_division_grid_version_when_null_requested(self) -> None:
        tournament = models.Tournament(
            workspace_id=10,
            number=4,
            name="Test",
            is_league=False,
            start_date=date(2026, 4, 17),
            end_date=date(2026, 4, 18),
            division_grid_version_id=55,
        )
        tournament.id = 123

        result = Mock()
        result.scalar_one_or_none.return_value = tournament
        session = SimpleNamespace(
            execute=AsyncMock(return_value=result),
            scalar=AsyncMock(return_value=None),
            commit=AsyncMock(),
        )
        data = admin_schemas.TournamentUpdate(division_grid_version_id=None)

        with (
            patch.object(
                admin_tournament_service,
                "get_workspace_division_grid_version_id",
                AsyncMock(return_value=77),
            ) as get_default_version,
            patch.object(
                admin_tournament_service,
                "get_tournament",
                AsyncMock(return_value=tournament),
            ) as get_tournament,
            patch.object(
                admin_tournament_service.division_grid_cache,
                "invalidate_tournament",
                AsyncMock(),
            ) as invalidate_tournament,
            patch.object(
                admin_tournament_service.division_grid_cache,
                "invalidate_workspace",
                AsyncMock(),
            ) as invalidate_workspace,
        ):
            result = await admin_tournament_service.update_tournament(session, 123, data)

        self.assertIs(result, tournament)
        self.assertEqual(77, tournament.division_grid_version_id)
        get_default_version.assert_awaited_once_with(session, 10)
        session.commit.assert_awaited_once_with()
        invalidate_tournament.assert_awaited_once_with(123)
        invalidate_workspace.assert_awaited_once_with(10)
        get_tournament.assert_awaited_once_with(session, 123)

    async def test_transition_to_live_auto_starts_first_ready_group_stage(self) -> None:
        tournament = SimpleNamespace(
            id=123,
            status=enums.TournamentStatus.DRAFT,
            is_finished=False,
            stages=[
            SimpleNamespace(
                id=11,
                order=0,
                stage_type=enums.StageType.ROUND_ROBIN,
                is_active=False,
                is_completed=False,
                items=[
                    SimpleNamespace(
                        id=21,
                        inputs=[
                            SimpleNamespace(slot=1, team_id=1),
                            SimpleNamespace(slot=2, team_id=2),
                        ],
                    ),
                    SimpleNamespace(
                        id=22,
                        inputs=[
                            SimpleNamespace(slot=1, team_id=3),
                            SimpleNamespace(slot=2, team_id=4),
                        ],
                    ),
                ],
            )
            ],
        )

        result = Mock()
        result.scalar_one_or_none.return_value = tournament
        session = SimpleNamespace(
            execute=AsyncMock(return_value=result),
            scalar=AsyncMock(return_value=0),
            commit=AsyncMock(),
        )

        with (
            patch.object(
                admin_tournament_service,
                "request_bracket_job",
                AsyncMock(),
            ) as request_bracket_job,
            patch.object(
                admin_tournament_service,
                "get_tournament",
                AsyncMock(return_value=tournament),
            ) as get_tournament,
        ):
            result_tournament = await admin_tournament_service.transition_status(
                session,
                tournament.id,
                enums.TournamentStatus.LIVE,
            )

        self.assertIs(result_tournament, tournament)
        self.assertEqual(enums.TournamentStatus.LIVE, tournament.status)
        self.assertFalse(tournament.is_finished)
        session.commit.assert_awaited_once_with()
        request_bracket_job.assert_awaited_once_with(
            session,
            tournament_id=123,
            stage_id=11,
            operation="activate_and_generate",
        )
        get_tournament.assert_awaited_once_with(session, tournament.id)

    async def test_transition_to_live_generates_for_already_active_group_stage(self) -> None:
        tournament = SimpleNamespace(
            id=123,
            status=enums.TournamentStatus.CHECK_IN,
            is_finished=False,
            stages=[
            SimpleNamespace(
                id=11,
                order=0,
                stage_type=enums.StageType.SWISS,
                is_active=True,
                is_completed=False,
                items=[
                    SimpleNamespace(
                        id=21,
                        inputs=[
                            SimpleNamespace(slot=1, team_id=1),
                            SimpleNamespace(slot=2, team_id=2),
                            SimpleNamespace(slot=3, team_id=3),
                            SimpleNamespace(slot=4, team_id=4),
                        ],
                    )
                ],
            )
            ],
        )

        result = Mock()
        result.scalar_one_or_none.return_value = tournament
        session = SimpleNamespace(
            execute=AsyncMock(return_value=result),
            scalar=AsyncMock(return_value=0),
            commit=AsyncMock(),
        )

        with (
            patch.object(
                admin_tournament_service,
                "request_bracket_job",
                AsyncMock(),
            ) as request_bracket_job,
            patch.object(
                admin_tournament_service,
                "get_tournament",
                AsyncMock(return_value=tournament),
            ),
        ):
            await admin_tournament_service.transition_status(
                session,
                tournament.id,
                enums.TournamentStatus.LIVE,
            )

        request_bracket_job.assert_awaited_once_with(
            session,
            tournament_id=123,
            stage_id=11,
            operation="generate_stage",
        )
