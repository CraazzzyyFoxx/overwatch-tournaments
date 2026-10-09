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

# Patch targets must be the module that OWNS these functions (lifecycle), not the
# `admin` facade: the lifecycle functions resolve collaborators from their own
# module globals, so patching the facade would not intercept them.
registration_service = importlib.import_module("src.services.registration.lifecycle")


class RegistrationEventOutboxTests(IsolatedAsyncioTestCase):
    async def test_approve_registration_enqueues_event_before_commit(self) -> None:
        calls: list[str] = []
        registration = SimpleNamespace(
            id=7,
            tournament_id=42,
            workspace_id=3,
            auth_user_id=11,
            user_id=None,
            primary_handle=lambda _provider: "Player#1234",
            status="pending",
            reviewed_at=None,
            reviewed_by=None,
            exclude_reason="manual",
        )
        session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: calls.append("commit")))

        async def fake_enqueue(_session, _registration):
            calls.append("enqueue")

        with (
            patch.object(
                registration_service.lifecycle_service,
                "get_registration_by_id",
                AsyncMock(return_value=registration),
            ),
            patch.object(
                registration_service,
                "enqueue_registration_approved",
                AsyncMock(side_effect=fake_enqueue),
            ) as enqueue_approved,
        ):
            result = await registration_service.lifecycle_service.approve_registration(session, 7, reviewed_by=99)

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
            primary_handle=lambda _provider: "Player#5678",
            status="pending",
            reviewed_at=None,
            reviewed_by=None,
        )
        session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: calls.append("commit")))

        async def fake_enqueue(_session, _registration):
            calls.append("enqueue")

        with (
            patch.object(
                registration_service.lifecycle_service,
                "get_registration_by_id",
                AsyncMock(return_value=registration),
            ),
            patch.object(
                registration_service,
                "enqueue_registration_rejected",
                AsyncMock(side_effect=fake_enqueue),
            ) as enqueue_rejected,
        ):
            result = await registration_service.lifecycle_service.reject_registration(session, 8, reviewed_by=99)

        self.assertIs(result, registration)
        self.assertEqual("rejected", registration.status)
        enqueue_rejected.assert_awaited_once_with(session, registration)
        self.assertLess(calls.index("enqueue"), calls.index("commit"))
