from __future__ import annotations

import asyncio
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


class _Db:
    """The outbox rows plus who holds their row locks: what two drains contend on."""

    def __init__(self, rows: list[object], *, now: datetime | None = None) -> None:
        self.rows = rows
        self.now = now
        self.locks: dict[int, _Session] = {}

    def lock_due(self, session: _Session, limit: int) -> list[object]:
        """``SELECT ... FOR UPDATE SKIP LOCKED LIMIT n``: due rows nobody else holds."""
        now = self.now or datetime.now(UTC)
        due = [
            row
            for row in self.rows
            if row.status in {"pending", "failed"}
            and (row.next_attempt_at is None or row.next_attempt_at <= now)
            and self.locks.get(row.id, session) is session
        ][:limit]
        for row in due:
            self.locks[row.id] = session
        return due


class _Session:
    def __init__(self, db: _Db | None = None) -> None:
        self.db = db or _Db([])
        self.added: list[object] = []
        self.flushed = 0
        self.committed = 0

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        # The transaction ends, and with it every row lock it took.
        self.committed += 1
        self.db.locks = {row_id: owner for row_id, owner in self.db.locks.items() if owner is not self}

    async def scalars(self, _statement) -> list[object]:
        return self.db.lock_due(self, limit=100)


def _row(row_id: int, *, now: datetime | None = None) -> SimpleNamespace:
    now = now or datetime.now(UTC)
    return SimpleNamespace(
        id=row_id,
        event_id=f"event-{row_id}",
        event_type="encounter_completed",
        exchange="tournament.events",
        routing_key="tournament.encounter.completed",
        payload_json={"event_id": f"event-{row_id}", "event_type": "encounter_completed"},
        status="pending",
        attempts=0,
        next_attempt_at=now,
        created_at=now,
        published_at=None,
        last_error=None,
    )


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
        row = _row(1)
        session = _Session(_Db([row]))
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
        row = _row(1, now=now)
        session = _Session(_Db([row], now=now))
        broker = SimpleNamespace(publish=AsyncMock(side_effect=RuntimeError("broker down")))

        published = await publish_pending_outbox_events(session, broker, now=now, commit=True)

        self.assertEqual(0, published)
        self.assertEqual("failed", row.status)
        self.assertEqual(1, row.attempts)
        self.assertEqual("broker down", row.last_error)
        self.assertGreater(row.next_attempt_at, now)
        self.assertEqual(1, session.committed)

    async def test_two_drains_publish_each_event_once(self) -> None:
        """Every tournament-service replica drains the shared table each second.

        A drain holds its whole batch until its single commit: a row it
        released mid-pass would be free for the other replica to take -- and
        publish a second time.
        """
        db = _Db([_row(row_id) for row_id in range(1, 6)])
        published: list[str] = []

        async def publish(payload, *_args, **_kwargs) -> None:
            published.append(payload["event_id"])
            await asyncio.sleep(0)  # a real publish awaits the broker; the other drain runs meanwhile

        broker = SimpleNamespace(publish=publish)
        first = asyncio.create_task(publish_pending_outbox_events(_Session(db), broker))
        await asyncio.sleep(0)  # the first drain holds its rows and is mid-publish
        while not first.done():
            await publish_pending_outbox_events(_Session(db), broker)
            await asyncio.sleep(0)
        await first

        self.assertCountEqual(published, [f"event-{row_id}" for row_id in range(1, 6)])
