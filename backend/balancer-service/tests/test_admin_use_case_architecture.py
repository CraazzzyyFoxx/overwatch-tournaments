from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ["DEBUG"] = "false"

from src.application.admin.balancer_use_cases import (  # noqa: E402
    ExportBalance,
    SaveBalance,
)


class BalancerAdminUseCaseTests(IsolatedAsyncioTestCase):
    async def test_save_balance_delegates_to_balance_service(self) -> None:
        class FakeBalancerService:
            async def save_balance(self, session, tournament_id: int, data, user):
                return SimpleNamespace(id=99, tournament_id=tournament_id, saved_by=user.id)

        use_case = SaveBalance(balancer_service=FakeBalancerService())
        result = await use_case.execute(
            session=object(),
            tournament_id=12,
            payload=SimpleNamespace(result_json={"teams": []}),
            user=SimpleNamespace(id=7),
        )

        self.assertEqual(result.id, 99)
        self.assertEqual(result.saved_by, 7)

    async def test_export_balance_delegates_to_balance_service(self) -> None:
        class FakeBalancerService:
            async def export_balance(self, session, balance_id: int):
                return (SimpleNamespace(id=balance_id), 5, 6)

        use_case = ExportBalance(balancer_service=FakeBalancerService())
        result = await use_case.execute(session=object(), balance_id=44)

        self.assertEqual(result[0].id, 44)
        self.assertEqual(result[1:], (5, 6))
