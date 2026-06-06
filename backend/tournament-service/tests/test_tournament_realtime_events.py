from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

events = importlib.import_module("src.services.tournament.recalculation_events")
tournament_events = importlib.import_module("src.services.tournament.events")
realtime_commit = importlib.import_module("src.services.tournament.realtime_commit")
realtime_pubsub = importlib.import_module("src.services.tournament.realtime_pubsub")


class TournamentRealtimeEventsTests(IsolatedAsyncioTestCase):
    async def test_changed_event_invalidates_cache_and_publishes_pubsub_update(self) -> None:
        invalidate = AsyncMock()
        publish = AsyncMock()

        with (
            patch.object(events, "invalidate_tournament_cache", invalidate),
            patch.object(events, "publish_tournament_update", publish),
        ):
            await events.handle_tournament_changed_event({"tournament_id": 42, "reason": "results_changed"})

        invalidate.assert_awaited_once_with(42, "results_changed")
        publish.assert_awaited_once_with(42, "results_changed")

    async def test_changed_outbox_event_registers_post_commit_realtime_update(self) -> None:
        session = SimpleNamespace(info={}, add=Mock(), flush=AsyncMock())

        await tournament_events.enqueue_tournament_changed(session, 42, "structure_changed")

        updates = realtime_commit.pop_registered_tournament_realtime_updates(session)
        self.assertEqual(updates, [(42, "structure_changed")])

    async def test_recalculation_outbox_event_registers_bracket_realtime_update(self) -> None:
        session = SimpleNamespace(info={}, add=Mock(), flush=AsyncMock())

        await tournament_events.enqueue_tournament_recalculation(session, 42)

        updates = realtime_commit.pop_registered_tournament_realtime_updates(session)
        self.assertEqual(updates, [(42, "bracket_changed")])

    async def test_registration_outbox_event_registers_structure_realtime_update(self) -> None:
        session = SimpleNamespace(info={}, add=Mock(), flush=AsyncMock())
        registration = SimpleNamespace(
            id=7,
            tournament_id=42,
            workspace_id=3,
            auth_user_id=11,
            user_id=None,
            battle_tag="Player#1234",
        )

        await tournament_events.enqueue_registration_approved(session, registration)

        updates = realtime_commit.pop_registered_tournament_realtime_updates(session)
        self.assertEqual(updates, [(42, "structure_changed")])

    async def test_post_commit_realtime_updates_collapse_structure_over_results(self) -> None:
        session = SimpleNamespace(info={})

        realtime_commit.register_tournament_realtime_update(session, 42, "results_changed")
        realtime_commit.register_tournament_realtime_update(session, 42, "structure_changed")

        updates = realtime_commit.pop_registered_tournament_realtime_updates(session)
        self.assertEqual(updates, [(42, "structure_changed")])

    async def test_post_commit_realtime_updates_collapse_results_over_bracket(self) -> None:
        session = SimpleNamespace(info={})

        realtime_commit.register_tournament_realtime_update(session, 42, "bracket_changed")
        realtime_commit.register_tournament_realtime_update(session, 42, "results_changed")

        updates = realtime_commit.pop_registered_tournament_realtime_updates(session)
        self.assertEqual(updates, [(42, "results_changed")])

    async def test_realtime_update_invalidates_cache_before_publishing(self) -> None:
        calls: list[str] = []

        async def invalidate(tournament_id: int, reason: str) -> None:
            calls.append(f"invalidate:{tournament_id}:{reason}")

        async def publish(tournament_id: int, reason: str) -> None:
            calls.append(f"publish:{tournament_id}:{reason}")

        with (
            patch.object(realtime_commit, "invalidate_tournament_cache", side_effect=invalidate),
            patch.object(realtime_pubsub, "publish_tournament_update", side_effect=publish),
        ):
            await realtime_commit.publish_tournament_realtime_updates([(42, "bracket_changed")])

        self.assertEqual(
            calls,
            [
                "invalidate:42:bracket_changed",
                "publish:42:bracket_changed",
            ],
        )
