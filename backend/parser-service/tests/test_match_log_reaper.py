"""Stall recovery for match-log records the queue dropped.

``process_match_log`` expires messages after five minutes, so a record whose
event was never consumed (batch upload, worker restart) stays ``pending``
forever, and a worker killed mid-parse leaves one stuck on ``processing``.
These tests pin the recovery contract: stalled rows get republished, spent ones
get retired, fresh ones are left alone.
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"

reaper = importlib.import_module("src.services.match_logs.reaper")
messaging_config = importlib.import_module("shared.messaging.config")
models = importlib.import_module("src.models")

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
LONG_AGO = NOW - timedelta(days=14)


def _record(**overrides) -> models.LogProcessingRecord:
    record = models.LogProcessingRecord(
        tournament_id=78,
        filename="logs/Log-2026-07-19-20-15-39.txt",
        status=models.LogProcessingStatus.pending,
        source=models.LogProcessingSource.upload,
        attempts=0,
    )
    record.id = overrides.pop("id", 1)
    record.created_at = overrides.pop("created_at", LONG_AGO)
    record.updated_at = overrides.pop("updated_at", None)
    record.tournament = models.Tournament(id=78, workspace_id=7, name="OWT 78", slug="owt-78")
    for field, value in overrides.items():
        setattr(record, field, value)
    return record


class _FakeSession:
    """Returns a canned row set and records that the pass committed."""

    def __init__(self, rows: list[models.LogProcessingRecord]) -> None:
        self._rows = rows
        self.commits = 0

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    async def execute(self, _statement):
        rows = self._rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    async def commit(self) -> None:
        self.commits += 1


class _FakeRedis:
    """Grants leadership unless told otherwise; `eval` covers lock release."""

    def __init__(self, *, leader: bool = True) -> None:
        self.leader = leader

    async def set(self, *_args, **_kwargs):
        return self.leader

    async def eval(self, *_args, **_kwargs):
        return 1


class MatchLogReaperTests(IsolatedAsyncioTestCase):
    async def _run(
        self,
        rows: list[models.LogProcessingRecord],
        *,
        leader: bool = True,
        publish: AsyncMock | None = None,
    ):
        session = _FakeSession(rows)
        publish = publish or AsyncMock()
        with (
            patch.object(reaper, "publish_message", publish),
            patch.object(reaper.logs_realtime, "emit_logs_updated", AsyncMock()) as signal,
        ):
            result = await reaper.reclaim_stalled_logs(
                redis=_FakeRedis(leader=leader),
                broker=SimpleNamespace(),
                session_factory=lambda: session,
                now=NOW,
            )
        return result, publish, signal, session

    async def test_stale_pending_record_is_requeued(self) -> None:
        record = _record(attempts=0)

        result, publish, signal, session = await self._run([record])

        self.assertEqual(1, result.requeued)
        self.assertEqual(0, result.exhausted)
        publish.assert_awaited_once()
        payload, queue = publish.await_args.args[1], publish.await_args.args[2]
        self.assertEqual(78, payload["tournament_id"])
        self.assertEqual("logs/Log-2026-07-19-20-15-39.txt", payload["filename"])
        self.assertIs(messaging_config.PROCESS_MATCH_LOG_QUEUE, queue)
        # Stamped so the next tick doesn't republish the same row immediately —
        # a no-op status assignment would never flush.
        self.assertEqual(NOW, record.updated_at)
        self.assertEqual(1, session.commits)
        # The admin console refetches on this signal, staged inside the same
        # transaction as the reset so a failed commit announces nothing.
        signal.assert_awaited_once()
        self.assertEqual(7, signal.await_args.args[1])

    async def test_stalled_processing_record_is_reset_and_requeued(self) -> None:
        record = _record(
            status=models.LogProcessingStatus.processing,
            started_at=LONG_AGO,
            attempts=2,
        )

        result, publish, _signal, _session = await self._run([record])

        self.assertEqual(1, result.requeued)
        self.assertEqual(models.LogProcessingStatus.pending, record.status)
        self.assertIsNone(record.started_at)
        publish.assert_awaited_once()

    async def test_record_out_of_attempts_is_failed_not_requeued(self) -> None:
        record = _record(
            status=models.LogProcessingStatus.processing,
            started_at=LONG_AGO,
            attempts=reaper.settings.log_reaper_max_attempts,
        )

        result, publish, _signal, _session = await self._run([record])

        self.assertEqual(0, result.requeued)
        self.assertEqual(1, result.exhausted)
        self.assertEqual(models.LogProcessingStatus.failed, record.status)
        self.assertEqual(NOW, record.finished_at)
        self.assertIn("attempts", record.error_message)
        publish.assert_not_awaited()

    async def test_publish_failure_leaves_the_row_pending_for_the_next_tick(self) -> None:
        record = _record(status=models.LogProcessingStatus.processing, started_at=LONG_AGO, attempts=1)
        publish = AsyncMock(side_effect=RuntimeError("broker down"))

        result, _publish, _signal, session = await self._run([record], publish=publish)

        self.assertEqual(0, result.requeued)
        self.assertEqual(models.LogProcessingStatus.pending, record.status)
        self.assertEqual(1, session.commits)

    async def test_second_replica_skips_the_tick(self) -> None:
        result, publish, _signal, session = await self._run([_record()], leader=False)

        self.assertEqual(0, result.touched)
        publish.assert_not_awaited()
        self.assertEqual(0, session.commits)

    async def test_nothing_stalled_publishes_nothing(self) -> None:
        result, publish, signal, _session = await self._run([])

        self.assertEqual(0, result.touched)
        publish.assert_not_awaited()
        signal.assert_not_awaited()

    def test_pending_window_outlives_the_queue_ttl(self) -> None:
        # Requeueing inside the TTL window would run a second parse alongside a
        # message still waiting on a busy consumer.
        queue_ttl_ms = messaging_config.PROCESS_MATCH_LOG_QUEUE.arguments["x-message-ttl"]
        self.assertGreater(reaper.settings.log_reaper_pending_after_seconds, queue_ttl_ms / 1000)

    def test_stalled_selection_covers_both_stuck_states(self) -> None:
        criterion = reaper.stalled_conditions(
            now=NOW,
            pending_after_seconds=900,
            processing_after_seconds=1800,
        )
        sql = str(criterion)

        # `pending` has no started_at, so its staleness rides the last write.
        self.assertIn("coalesce(log_processing.record.updated_at, log_processing.record.created_at)", sql)
        # `processing` is measured from when the parse actually began.
        self.assertIn("coalesce(log_processing.record.started_at", sql)
        # `done` and `failed` are terminal: the reaper must never touch them.
        self.assertEqual(2, sql.count("log_processing.record.status"))
        cutoffs = sorted(v for v in criterion.compile().params.values() if isinstance(v, datetime))
        self.assertEqual([NOW - timedelta(seconds=1800), NOW - timedelta(seconds=900)], cutoffs)
