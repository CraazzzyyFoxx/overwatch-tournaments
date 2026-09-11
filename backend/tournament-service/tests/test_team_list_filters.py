"""Chip search on GET /teams reaches SQL, not a client pass over `per_page=-1`."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ.setdefault("DEBUG", "true")

from src import schemas  # noqa: E402
from src.services.team.service import TeamService  # noqa: E402


class _FakeResult:
    def unique(self) -> _FakeResult:
        return self

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list:
        return []

    def scalar_one(self) -> int:
        return 0


class _FakeSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult()

    async def scalar(self, statement: Any) -> int:
        self.statements.append(statement)
        return 0


class TeamListSearchTests(IsolatedAsyncioTestCase):
    async def _sql(self, **overrides: Any) -> str:
        session = _FakeSession()
        params = schemas.TeamFilterParams.from_query_params(schemas.TeamFilterQueryParams(tournament_id=7, **overrides))
        await TeamService().get_all(session, params)
        self.assertGreaterEqual(len(session.statements), 2)
        return " ".join(str(statement) for statement in session.statements).lower()

    async def test_search_filters_on_team_name(self) -> None:
        base = await self._sql()
        sql = await self._sql(search="wombat")
        self.assertNotEqual(sql, base)
        self.assertIn("like", sql)
        self.assertIn("team.name", sql)

    async def test_an_unfiltered_page_does_not_search(self) -> None:
        sql = await self._sql()
        self.assertNotIn(" like ", f" {sql} ")
