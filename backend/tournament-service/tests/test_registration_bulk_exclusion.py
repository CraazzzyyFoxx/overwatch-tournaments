from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from src.services.registration.lifecycle import bulk_set_exclusion  # noqa: E402


class _Result:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[SimpleNamespace]:
        return self._rows


def _registration(registration_id: int, *, status: str, ranked: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id=registration_id,
        tournament_id=7,
        status=status,
        roles=[SimpleNamespace(is_active=True, rank_value=2500 if ranked else None)],
        exclude_from_balancer=False,
        exclude_reason=None,
        balancer_status="incomplete",
    )


class BulkSetExclusionTests(IsolatedAsyncioTestCase):
    async def test_matches_single_registration_semantics(self) -> None:
        approved = _registration(1, status="approved", ranked=True)
        pending = _registration(2, status="pending", ranked=False)
        session = SimpleNamespace(
            execute=AsyncMock(return_value=_Result([approved, pending])),
            commit=AsyncMock(),
            info={},
        )

        updated, skipped = await bulk_set_exclusion(
            session,
            7,
            [1, 2, 404],
            exclude_from_balancer=True,
            exclude_reason="manual_exclusion",
        )

        self.assertEqual((2, 1), (updated, skipped))
        self.assertIs(approved.exclude_from_balancer, True)
        self.assertIs(pending.exclude_from_balancer, True)
        self.assertEqual("manual_exclusion", approved.exclude_reason)
        self.assertEqual("manual_exclusion", pending.exclude_reason)
        self.assertEqual("not_in_balancer", approved.balancer_status)
        self.assertEqual("not_in_balancer", pending.balancer_status)
        session.commit.assert_awaited_once()

        session.commit.reset_mock()
        updated, skipped = await bulk_set_exclusion(
            session,
            7,
            [1, 2],
            exclude_from_balancer=False,
            exclude_reason="ignored",
        )

        self.assertEqual((2, 0), (updated, skipped))
        self.assertIs(approved.exclude_from_balancer, False)
        self.assertIs(pending.exclude_from_balancer, False)
        self.assertIsNone(approved.exclude_reason)
        self.assertIsNone(pending.exclude_reason)
        self.assertEqual("ready", approved.balancer_status)
        self.assertEqual("not_in_balancer", pending.balancer_status)
        session.commit.assert_awaited_once()
