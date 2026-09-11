"""Admin achievement-rule list pages in SQL, not a client slice of every rule."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("DEBUG", "true")

from src import schemas  # noqa: E402
from src.services.achievement.rule_service import achievement_rule_service  # noqa: E402


class _FakeResult:
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


class RuleListFilterTests(IsolatedAsyncioTestCase):
    async def _sql(self, **overrides: Any) -> str:
        session = _FakeSession()
        params = schemas.AchievementRuleListParams.from_query_params(
            schemas.AchievementRuleListQueryParams(page=1, per_page=15, **overrides)
        )
        await achievement_rule_service.list_rules(session, workspace_id=3, params=params)
        self.assertEqual(len(session.statements), 2)
        return " ".join(str(statement) for statement in session.statements).lower()

    async def test_search_matches_name_or_slug(self) -> None:
        base = await self._sql()
        sql = await self._sql(search="clutch")
        self.assertNotEqual(sql, base)
        self.assertIn("like", sql)
        self.assertIn("rule.name", sql)
        self.assertIn("rule.slug", sql)

    async def test_category_and_enabled_reach_the_count_query(self) -> None:
        sql = await self._sql(category="hero", enabled=True)
        self.assertIn("hero", sql)
        self.assertIn("enabled", sql)

    async def test_page_applies_limit(self) -> None:
        sql = await self._sql()
        self.assertIn("limit", sql)
