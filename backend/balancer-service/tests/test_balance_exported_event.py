from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

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

from shared.messaging.config import BALANCER_EVENTS_EXCHANGE  # noqa: E402
from src.schemas.team import InternalBalancerPlayer, InternalBalancerTeam, InternalBalancerTeamsPayload  # noqa: E402
from src.services.admin import balance_analytics  # noqa: E402


def _make_session_without_registrations() -> MagicMock:
    """Session whose registration lookup returns nothing (identity unresolved)."""
    scalar_result = MagicMock()
    scalar_result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=scalar_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _payload() -> InternalBalancerTeamsPayload:
    return InternalBalancerTeamsPayload(
        teams=[
            InternalBalancerTeam(
                id=1,
                name="Team A",
                average_mmr=2500.0,
                roster={
                    "Tank": [
                        InternalBalancerPlayer(
                            uuid="u1",
                            name="Alice",
                            assigned_rating=3000,
                            role_discomfort=5,
                            is_captain=True,
                            role_preferences=["Support"],
                        )
                    ],
                    "Support": [
                        InternalBalancerPlayer(
                            uuid="u2",
                            name="Bob",
                            assigned_rating=2000,
                            role_discomfort=0,
                            is_captain=False,
                            role_preferences=["Support"],
                        )
                    ],
                },
            )
        ]
    )


class BalanceExportedEventTests(IsolatedAsyncioTestCase):
    async def test_emits_event_with_denormalized_payload_and_no_direct_write(self) -> None:
        session = _make_session_without_registrations()
        balance = SimpleNamespace(
            id=123,
            tournament_id=42,
            workspace_id=7,
            algorithm="moo",
            division_scope="tournament",
            division_grid_json={"divisions": []},
            variants=[],
        )
        exported_teams = {"Team A": SimpleNamespace(id=99)}

        with patch.object(balance_analytics, "enqueue_outbox_event", AsyncMock()) as enqueue:
            await balance_analytics.enqueue_balance_exported_event(session, balance, _payload(), exported_teams)

        # Exactly one outbox event, and no direct analytics-table writes on the session.
        self.assertEqual(1, enqueue.await_count)
        session.add.assert_not_called()

        call = enqueue.await_args
        self.assertIs(call.args[0], session)
        event = call.args[1]
        self.assertEqual("balance_exported", event.event_type)
        self.assertEqual("balancer-service", event.source_service)
        self.assertEqual(42, event.tournament_id)
        self.assertEqual(123, event.balance_id)
        self.assertEqual(7, event.workspace_id)
        self.assertEqual("moo", event.algorithm)
        self.assertEqual("tournament", event.division_scope)
        self.assertEqual({"divisions": []}, event.division_grid_json)
        self.assertEqual(1, event.team_count)
        self.assertEqual(2, event.player_count)
        self.assertEqual(5, event.total_discomfort)
        self.assertEqual(1, event.off_role_count)
        self.assertEqual(2500.0, event.avg_sr_overall)
        self.assertEqual(1000.0, event.sr_range)
        self.assertEqual(500.0, event.sr_std_dev)

        self.assertEqual("balancer.balance.exported", call.kwargs["routing_key"])
        self.assertIs(BALANCER_EVENTS_EXCHANGE, call.kwargs["exchange"])

        # Per-player rows are denormalized into the event.
        self.assertEqual(2, len(event.players))
        by_role = {p.assigned_role: p for p in event.players}
        self.assertTrue(by_role["tank"].was_off_role)
        self.assertTrue(by_role["tank"].is_captain)
        self.assertEqual(3000, by_role["tank"].assigned_rank)
        self.assertEqual(5, by_role["tank"].discomfort)
        self.assertEqual(99, by_role["tank"].team_id)
        self.assertIsNone(by_role["tank"].user_id)
        self.assertFalse(by_role["support"].was_off_role)
        self.assertEqual("support", by_role["support"].preferred_role)

    async def test_no_event_when_payload_empty(self) -> None:
        session = _make_session_without_registrations()
        balance = SimpleNamespace(
            id=1,
            tournament_id=1,
            workspace_id=None,
            algorithm="moo",
            division_scope=None,
            division_grid_json=None,
            variants=[],
        )

        with patch.object(balance_analytics, "enqueue_outbox_event", AsyncMock()) as enqueue:
            result = await balance_analytics.enqueue_balance_exported_event(
                session, balance, InternalBalancerTeamsPayload(teams=[]), {}
            )

        self.assertIsNone(result)
        enqueue.assert_not_awaited()
