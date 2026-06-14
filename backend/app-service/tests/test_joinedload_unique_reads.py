from __future__ import annotations

import importlib
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

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

gamemode_service = importlib.import_module("src.services.gamemode.service")
team_service = importlib.import_module("src.services.team.service")
tournament_service = importlib.import_module("src.services.tournament.service")


class JoinedloadReadUniquenessTests(IsolatedAsyncioTestCase):
    async def test_gamemode_get_uses_unique_before_scalar_one_or_none(self) -> None:
        unique_result = Mock()
        unique_result.scalar_one_or_none.return_value = "gamemode"

        result = Mock()
        result.unique.return_value = unique_result

        session = SimpleNamespace(execute=AsyncMock(return_value=result))

        value = await gamemode_service.get(session, 1, ["maps"])

        self.assertEqual("gamemode", value)
        result.unique.assert_called_once_with()
        unique_result.scalar_one_or_none.assert_called_once_with()

    async def test_team_get_uses_unique_before_scalars_first(self) -> None:
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

    async def test_tournament_get_bulk_uses_unique_before_scalars_all(self) -> None:
        scalar_result = Mock()
        scalar_result.all.return_value = ["tournament"]

        unique_result = Mock()
        unique_result.scalars.return_value = scalar_result

        result = Mock()
        result.unique.return_value = unique_result

        session = SimpleNamespace(execute=AsyncMock(return_value=result))

        value = await tournament_service.get_bulk_tournament(session, [1], ["stages"])

        self.assertEqual(["tournament"], value)
        result.unique.assert_called_once_with()
        unique_result.scalars.assert_called_once_with()
        scalar_result.all.assert_called_once_with()
