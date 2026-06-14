from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "realtime-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

event_replay = importlib.import_module("src.services.event_replay")


class _ExplodingSession:
    """Session stand-in that fails the test if any query is executed."""

    async def execute(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("session.execute must not be called for a live-only subscribe")

    async def scalar(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("session.scalar must not be called for a live-only subscribe")


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list:
        return self._rows


class _RecordingSession:
    """Session stand-in that records execute() calls and returns no rows."""

    def __init__(self) -> None:
        self.execute_calls = 0

    async def execute(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        self.execute_calls += 1
        return _Result([])


class EventReplaySinceTests(IsolatedAsyncioTestCase):
    async def test_missing_cursor_is_live_only_and_skips_query(self) -> None:
        """A first-time subscriber (after_event_id=None) must NOT replay history.

        Replaying the whole backlog on every fresh page load is what caused the
        participants page to fire hundreds of redundant invalidation refetches.
        """
        service = event_replay.EventReplayService()

        events = await service.since(
            _ExplodingSession(),
            topic="tournament:72:bracket",
            after_event_id=None,
            up_to_event_id=500,
        )

        self.assertEqual(events, [])

    async def test_explicit_cursor_still_replays(self) -> None:
        """A reconnecting subscriber that knows its cursor still gets catch-up.

        Even an explicit cursor of 0 must query so events missed during a brief
        disconnect are delivered.
        """
        service = event_replay.EventReplayService()
        session = _RecordingSession()

        events = await service.since(
            session,
            topic="tournament:72:bracket",
            after_event_id=0,
            up_to_event_id=500,
        )

        self.assertEqual(events, [])
        self.assertEqual(session.execute_calls, 1)
