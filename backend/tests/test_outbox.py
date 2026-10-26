from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from shared.messaging import outbox  # noqa: E402
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

    async def scalar(self, _statement) -> datetime | None:
        """``SELECT min(created_at) ... WHERE status IN ('pending', 'failed')``: locked or backing off alike."""
        return min((row.created_at for row in self.db.rows if row.status in {"pending", "failed"}), default=None)


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
    def setUp(self) -> None:
        outbox._declared_exchanges.clear()

    async def test_drain_declares_each_target_exchange_once_per_process(self) -> None:
        """A publish to an undeclared exchange closes the channel and fails the rest of the batch.

        Every producing service drains now, so the first process to publish onto an
        exchange on a fresh broker may be one that never consumes from it.
        """
        db = _Db([_row(1), _row(2)])
        broker = SimpleNamespace(publish=AsyncMock(), declare_exchange=AsyncMock())

        await publish_pending_outbox_events(_Session(db), broker)
        db.rows[0].status = db.rows[1].status = "pending"
        await publish_pending_outbox_events(_Session(db), broker)

        self.assertEqual(1, broker.declare_exchange.await_count)
        self.assertEqual("tournament.events", broker.declare_exchange.await_args.args[0].name)

    async def test_enqueue_outbox_event_adds_row_without_publishing(self) -> None:
        session = _Session()
        event = EncounterCompletedEvent(
            tournament_id=42,
            encounter_id=7,
            home_team_id=1,
            away_team_id=2,
            winner_team_id=1,
            source_service="stats-service",
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
        broker = SimpleNamespace(publish=AsyncMock(), declare_exchange=AsyncMock())

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
        broker = SimpleNamespace(
            publish=AsyncMock(side_effect=RuntimeError("broker down")), declare_exchange=AsyncMock()
        )

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

        broker = SimpleNamespace(publish=publish, declare_exchange=AsyncMock())
        first = asyncio.create_task(publish_pending_outbox_events(_Session(db), broker))
        await asyncio.sleep(0)  # the first drain holds its rows and is mid-publish
        while not first.done():
            await publish_pending_outbox_events(_Session(db), broker)
            await asyncio.sleep(0)
        await first

        self.assertCountEqual(published, [f"event-{row_id}" for row_id in range(1, 6)])

    async def test_a_hung_publish_ends_the_batch_and_its_bookkeeping_commits(self) -> None:
        """A blocked broker (resource alarm) sits on every publish: the first timeout ends the batch.

        Waiting one timeout per row kept the transaction idle past pgBouncer's idle_transaction_timeout, which then
        killed the connection: the failure counts were lost and the 20-attempt rule never ran.
        """
        rows = [_row(1), _row(2), _row(3)]
        calls: list[str] = []

        async def hang(payload, *_args, **_kwargs) -> None:
            calls.append(payload["event_id"])
            await asyncio.sleep(60)

        session = _Session(_Db(rows))
        broker = SimpleNamespace(publish=hang, declare_exchange=AsyncMock())
        started = asyncio.get_running_loop().time()
        with patch.object(outbox, "PUBLISH_TIMEOUT_SECONDS", 0.05):
            published = await asyncio.wait_for(publish_pending_outbox_events(session, broker), 5)

        self.assertLess(asyncio.get_running_loop().time() - started, 1)
        self.assertEqual((0, ["event-1"]), (published, calls))
        self.assertEqual(("failed", 1, "TimeoutError"), (rows[0].status, rows[0].attempts, rows[0].last_error))
        self.assertEqual([("pending", 0)] * 2, [(row.status, row.attempts) for row in rows[1:]])
        self.assertEqual(1, session.committed)

    async def test_the_batch_starts_no_publish_after_its_budget(self) -> None:
        rows = [_row(1), _row(2), _row(3)]

        async def slow(*_args, **_kwargs) -> None:
            await asyncio.sleep(0.15)

        session = _Session(_Db(rows))
        broker = SimpleNamespace(publish=slow, declare_exchange=AsyncMock())
        with patch.object(outbox, "BATCH_BUDGET_SECONDS", 0.25):
            published = await publish_pending_outbox_events(session, broker)

        # Rows 1 and 2 start inside the budget; row 3 would start after it and is left for the next tick.
        self.assertEqual(2, published)
        self.assertEqual(["published", "published", "pending"], [row.status for row in rows])
        self.assertEqual(0, rows[2].attempts)
        self.assertEqual(1, session.committed)

    async def test_the_last_allowed_failure_parks_the_row_as_dead(self) -> None:
        now = datetime.now(UTC)
        row = _row(1, now=now)
        row.status, row.attempts = "failed", outbox.MAX_ATTEMPTS - 1
        db = _Db([row], now=now)
        broker = SimpleNamespace(
            publish=AsyncMock(side_effect=RuntimeError("broker down")), declare_exchange=AsyncMock()
        )
        dead_before = outbox.OUTBOX_DEAD_TOTAL._value.get()

        await publish_pending_outbox_events(_Session(db), broker, now=now)
        db.now = now + timedelta(days=1)
        await publish_pending_outbox_events(_Session(db), broker, now=db.now)

        self.assertEqual("dead", row.status)
        self.assertEqual(outbox.MAX_ATTEMPTS, row.attempts)
        self.assertEqual(1, broker.publish.await_count)  # never drained again
        self.assertEqual(dead_before + 1, outbox.OUTBOX_DEAD_TOTAL._value.get())

    async def test_the_gauge_reports_the_oldest_unpublished_row_even_when_it_backs_off(self) -> None:
        now = datetime.now(UTC)
        failing = _row(1, now=now - timedelta(minutes=10))
        failing.status, failing.next_attempt_at = "failed", now + timedelta(minutes=5)  # out of every batch for now
        fresh = _row(2, now=now)
        db = _Db([failing, fresh], now=now)
        broker = SimpleNamespace(publish=AsyncMock(), declare_exchange=AsyncMock())

        self.assertEqual(1, await publish_pending_outbox_events(_Session(db), broker, now=now))
        self.assertEqual(600, outbox.OUTBOX_OLDEST_PENDING_AGE_SECONDS._value.get())

        failing.status = "dead"
        await publish_pending_outbox_events(_Session(db), broker, now=now)
        self.assertEqual(0, outbox.OUTBOX_OLDEST_PENDING_AGE_SECONDS._value.get())

    async def test_a_batch_caller_can_defer_the_flush(self) -> None:
        session = _Session()
        event = EncounterCompletedEvent(
            tournament_id=42, encounter_id=7, home_team_id=1, away_team_id=2, winner_team_id=1, source_service="t"
        )

        row = await enqueue_outbox_event(
            session, event, exchange="tournament.events", routing_key="tournament.encounter.completed", flush=False
        )

        self.assertIs(row, session.added[0])
        self.assertEqual(0, session.flushed)
