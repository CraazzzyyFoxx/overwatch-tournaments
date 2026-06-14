from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

registration_service = importlib.import_module("src.services.registration.admin")


class RegistrationEventOutboxTests(IsolatedAsyncioTestCase):
    async def test_approve_registration_enqueues_event_before_commit(self) -> None:
        calls: list[str] = []
        registration = SimpleNamespace(
            id=7,
            tournament_id=42,
            workspace_id=3,
            auth_user_id=11,
            user_id=None,
            battle_tag="Player#1234",
            status="pending",
            reviewed_at=None,
            reviewed_by=None,
            exclude_from_balancer=True,
            exclude_reason="manual",
        )
        session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: calls.append("commit")))

        async def fake_enqueue(_session, _registration):
            calls.append("enqueue")

        with (
            patch.object(
                registration_service,
                "get_registration_by_id",
                AsyncMock(return_value=registration),
            ),
            patch.object(
                registration_service,
                "enqueue_registration_approved",
                AsyncMock(side_effect=fake_enqueue),
            ) as enqueue_approved,
        ):
            result = await registration_service.approve_registration(session, 7, reviewed_by=99)

        self.assertIs(result, registration)
        self.assertEqual("approved", registration.status)
        enqueue_approved.assert_awaited_once_with(session, registration)
        self.assertLess(calls.index("enqueue"), calls.index("commit"))

    async def test_reject_registration_enqueues_event_before_commit(self) -> None:
        calls: list[str] = []
        registration = SimpleNamespace(
            id=8,
            tournament_id=42,
            workspace_id=3,
            auth_user_id=12,
            user_id=None,
            battle_tag="Player#5678",
            status="pending",
            reviewed_at=None,
            reviewed_by=None,
        )
        session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: calls.append("commit")))

        async def fake_enqueue(_session, _registration):
            calls.append("enqueue")

        with (
            patch.object(
                registration_service,
                "get_registration_by_id",
                AsyncMock(return_value=registration),
            ),
            patch.object(
                registration_service,
                "enqueue_registration_rejected",
                AsyncMock(side_effect=fake_enqueue),
            ) as enqueue_rejected,
        ):
            result = await registration_service.reject_registration(session, 8, reviewed_by=99)

        self.assertIs(result, registration)
        self.assertEqual("rejected", registration.status)
        enqueue_rejected.assert_awaited_once_with(session, registration)
        self.assertLess(calls.index("enqueue"), calls.index("commit"))
