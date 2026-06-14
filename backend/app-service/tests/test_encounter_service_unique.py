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

service = importlib.import_module("src.services.encounter.service")


class EncounterResultUniquenessTests(IsolatedAsyncioTestCase):
    async def test_get_by_user_uses_unique_strategy_for_tuple_results(self) -> None:
        encounter = SimpleNamespace(id=11)
        match = SimpleNamespace(id=22)
        expected_rows = [(encounter, match, 123, [{"id": 1}])]
        unique_result = Mock()
        unique_result.all.return_value = expected_rows

        result = Mock()
        result.unique.return_value = unique_result

        total_result = Mock()
        total_result.scalar_one.return_value = 7

        session = SimpleNamespace(execute=AsyncMock(side_effect=[result, total_result]))
        params = SimpleNamespace(
            entities=["stage", "matches.map"],
            apply_pagination_sort=lambda query: query,
            apply_sort=lambda query: query,
        )

        rows, total = await service.get_by_user(session, 599, params, workspace_id=2)

        self.assertEqual(expected_rows, rows)
        self.assertEqual(7, total)
        result.unique.assert_called_once()
        strategy = result.unique.call_args.args[0]
        self.assertEqual((11, 22), strategy(expected_rows[0]))
        unique_result.all.assert_called_once_with()

    async def test_get_by_user_with_teams_uses_unique_strategy_for_tuple_results(self) -> None:
        team = SimpleNamespace(id=7)
        encounter = SimpleNamespace(id=13)
        match = SimpleNamespace(id=29)
        expected_rows = [(team, encounter, match, 321, [{"id": 2}])]
        unique_result = Mock()
        unique_result.all.return_value = expected_rows

        result = Mock()
        result.unique.return_value = unique_result

        session = SimpleNamespace(execute=AsyncMock(return_value=result))

        rows = await service.get_by_user_with_teams(session, 599, ["matches.map"])

        self.assertEqual(expected_rows, rows)
        result.unique.assert_called_once()
        strategy = result.unique.call_args.args[0]
        self.assertEqual((7, 13, 29), strategy(expected_rows[0]))
        unique_result.all.assert_called_once_with()
