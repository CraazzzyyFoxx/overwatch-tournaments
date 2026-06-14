from __future__ import annotations

import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock


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

from src.services.achievements import service_v2  # noqa: E402


class AchievementQueryTests(IsolatedAsyncioTestCase):
    async def test_get_uses_outer_join_for_zero_rarity_rules(self) -> None:
        captured_queries = []

        async def execute_side_effect(query):
            captured_queries.append(query)
            return SimpleNamespace(first=lambda: None)

        session = SimpleNamespace(execute=AsyncMock(side_effect=execute_side_effect))

        await service_v2.get(session, 123, [], workspace_id=77)

        self.assertEqual(1, len(captured_queries))
        self.assertIn("LEFT OUTER JOIN", str(captured_queries[0]).upper())
