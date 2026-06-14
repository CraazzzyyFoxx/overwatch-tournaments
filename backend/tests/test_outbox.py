from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from shared.messaging.outbox import enqueue_outbox_event, publish_pending_outbox_events  # noqa: E402
from shared.schemas.events import EncounterCompletedEvent  # noqa: E402


class _ScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self.rows)


class _Session:
    def __init__(self, rows: list[object] | None = None) -> None:
        self.rows = rows or []
        self.added: list[object] = []
        self.flushed = 0
        self.committed = 0

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def execute(self, _statement) -> _Result:
        publishable = [row for row in self.rows if row.status in {"pending", "failed"}]
        return _Result(publishable)


class OutboxTests(IsolatedAsyncioTestCase):
    async def test_enqueue_outbox_event_adds_row_without_publishing(self) -> None:
        session = _Session()
        event = EncounterCompletedEvent(
            tournament_id=42,
            encounter_id=7,
            home_team_id=1,
            away_team_id=2,
            winner_team_id=1,
            source_service="parser-service",
        )

        row = await enqueue_outbox_event(
            session,
            event,
            exchange="tournament.events",
            routing_key="tournament.encounter.completed",
        )

        self.assertIs(row, session.added[0])
        self.assertEqual(event.event_id, row.event_id)
        self.assertEqual("encounter_completed", row.event_type)
        self.assertEqual("pending", row.status)
        self.assertEqual(1, session.flushed)

    async def test_publish_pending_marks_success_and_skips_repeated_drain(self) -> None:
        row = SimpleNamespace(
            id=1,
            event_id="event-1",
            event_type="encounter_completed",
            exchange="tournament.events",
            routing_key="tournament.encounter.completed",
            payload_json={"event_id": "event-1", "event_type": "encounter_completed"},
            status="pending",
            attempts=0,
            next_attempt_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            published_at=None,
            last_error=None,
        )
        session = _Session([row])
        broker = SimpleNamespace(publish=AsyncMock())

        first = await publish_pending_outbox_events(session, broker, commit=True)
        second = await publish_pending_outbox_events(session, broker, commit=True)

        self.assertEqual(1, first)
        self.assertEqual(0, second)
        self.assertEqual("published", row.status)
        self.assertIsNotNone(row.published_at)
        self.assertEqual(1, broker.publish.await_count)
        self.assertEqual(1, session.committed)

    async def test_publish_failure_leaves_retryable_row(self) -> None:
        now = datetime.now(UTC)
        row = SimpleNamespace(
            id=1,
            event_id="event-1",
            event_type="encounter_completed",
            exchange="tournament.events",
            routing_key="tournament.encounter.completed",
            payload_json={"event_id": "event-1", "event_type": "encounter_completed"},
            status="pending",
            attempts=0,
            next_attempt_at=now,
            created_at=now,
            published_at=None,
            last_error=None,
        )
        session = _Session([row])
        broker = SimpleNamespace(publish=AsyncMock(side_effect=RuntimeError("broker down")))

        published = await publish_pending_outbox_events(session, broker, now=now, commit=True)

        self.assertEqual(0, published)
        self.assertEqual("failed", row.status)
        self.assertEqual(1, row.attempts)
        self.assertEqual("broker down", row.last_error)
        self.assertGreater(row.next_attempt_at, now)
        self.assertEqual(1, session.committed)
