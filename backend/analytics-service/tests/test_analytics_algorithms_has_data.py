"""Tests for the per-tournament ``has_data`` annotation on analytics algorithms.

When the algorithms list is fetched with a tournament context, each algorithm is
flagged with whether it has computed shift rows for that tournament, so the UI
can default to a richer algorithm only when it is actually populated.
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ["DEBUG"] = "false"
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

analytics_flows = importlib.import_module("src.services.analytics_read.flows")

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _algorithm(algorithm_id: int, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=algorithm_id, created_at=NOW, updated_at=None, name=name)


def _params() -> SimpleNamespace:
    return SimpleNamespace(page=1, per_page=-1)


class AlgorithmHasDataTests(IsolatedAsyncioTestCase):
    async def test_annotates_has_data_for_tournament(self) -> None:
        algorithms = [
            _algorithm(1, "Linear"),
            _algorithm(2, "Points"),
            _algorithm(3, "OpenSkill + ML"),
        ]
        session = SimpleNamespace()

        with (
            patch.object(
                analytics_flows.service, "get_algorithms", AsyncMock(return_value=algorithms)
            ),
            patch.object(
                analytics_flows.service,
                "get_algorithm_ids_with_shift_data",
                AsyncMock(return_value={1, 3}),
            ),
        ):
            result = await analytics_flows.get_algorithms(
                session, _params(), tournament_id=7
            )

        has_data = {row.name: row.has_data for row in result.results}
        self.assertEqual({"Linear": True, "Points": False, "OpenSkill + ML": True}, has_data)

    async def test_has_data_is_none_without_tournament(self) -> None:
        algorithms = [_algorithm(1, "Linear"), _algorithm(3, "OpenSkill + ML")]
        session = SimpleNamespace()

        ids_mock = AsyncMock(return_value=set())
        with (
            patch.object(
                analytics_flows.service, "get_algorithms", AsyncMock(return_value=algorithms)
            ),
            patch.object(
                analytics_flows.service, "get_algorithm_ids_with_shift_data", ids_mock
            ),
        ):
            result = await analytics_flows.get_algorithms(session, _params())

        self.assertTrue(all(row.has_data is None for row in result.results))
        ids_mock.assert_not_awaited()  # no tournament ⇒ no data lookup
