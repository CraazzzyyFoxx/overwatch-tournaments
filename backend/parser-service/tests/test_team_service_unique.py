from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

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

team_service = importlib.import_module("src.services.team.service")


class ParserTeamServiceUniquenessTests(IsolatedAsyncioTestCase):
    async def test_get_uses_unique_before_scalars_first(self) -> None:
        scalar_result = Mock()
        scalar_result.first.return_value = "team"

        unique_result = Mock()
        unique_result.scalars.return_value = scalar_result

        result = Mock()
        result.unique.return_value = unique_result

        session = SimpleNamespace(execute=AsyncMock(return_value=result))

        value = await team_service.get(session, 1, ["players", "players.user"])

        self.assertEqual("team", value)
        result.unique.assert_called_once_with()
        unique_result.scalars.assert_called_once_with()
        scalar_result.first.assert_called_once_with()

    async def test_get_player_by_user_and_tournament_uses_unique_before_scalars_first(self) -> None:
        scalar_result = Mock()
        scalar_result.first.return_value = "player"

        unique_result = Mock()
        unique_result.scalars.return_value = scalar_result

        result = Mock()
        result.unique.return_value = unique_result

        session = SimpleNamespace(execute=AsyncMock(return_value=result))

        value = await team_service.get_player_by_user_and_tournament(
            session,
            1,
            2,
            ["team", "team.players"],
        )

        self.assertEqual("player", value)
        result.unique.assert_called_once_with()
        unique_result.scalars.assert_called_once_with()
        scalar_result.first.assert_called_once_with()

    async def test_get_teams_by_tournament_uses_unique_before_scalars_all(self) -> None:
        scalar_result = Mock()
        scalar_result.all.return_value = ["team"]

        unique_result = Mock()
        unique_result.scalars.return_value = scalar_result

        result = Mock()
        result.unique.return_value = unique_result

        session = SimpleNamespace(execute=AsyncMock(return_value=result))

        value = await team_service.get_teams_by_tournament(session, 2, ["players"])

        self.assertEqual(["team"], value)
        result.unique.assert_called_once_with()
        unique_result.scalars.assert_called_once_with()
        scalar_result.all.assert_called_once_with()
