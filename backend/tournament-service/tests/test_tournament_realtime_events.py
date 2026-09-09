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
        # ``scalar`` answers the scrim-container probe the recalculation now makes
        # before queueing a job (docs/plans/2026-08-12-scrim-rooms.md §5);
        # ``None`` means "an ordinary tournament".
        session = SimpleNamespace(info={}, add=Mock(), flush=AsyncMock(), scalar=AsyncMock(return_value=None))

        with patch.object(tournament_events.jobs_service, "request_standings_recalculation", AsyncMock()) as request:
            await tournament_events.enqueue_tournament_recalculation(session, 42)

        request.assert_awaited_once_with(session, 42)
        updates = realtime_commit.pop_registered_tournament_realtime_updates(session)
        self.assertEqual(updates, [(42, "bracket_changed")])

    async def test_registration_outbox_event_registers_registration_realtime_update(self) -> None:
        # BalancerRegistration has no denormalized workspace_id column anymore —
        # enqueue_registration_approved derives it via a tournament lookup. The
        # event's user_id is likewise resolved from the workspace_member anchor
        # (dbarch02 dropped registration.user_id); None here skips that lookup.
        session = SimpleNamespace(info={}, add=Mock(), flush=AsyncMock(), scalar=AsyncMock(return_value=3))
        registration = SimpleNamespace(
            id=7,
            tournament_id=42,
            workspace_member_id=None,
            battle_tag="Player#1234",
        )

        await tournament_events.enqueue_registration_approved(session, registration)

        updates = realtime_commit.pop_registered_tournament_realtime_updates(session)
        self.assertEqual(updates, [(42, "registration_changed")])

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

    async def test_registration_changed_emits_alongside_a_disjoint_bracket_family_reason(self) -> None:
        # registration_changed's plan (registration/registrationsList/
        # registrationForm) is disjoint from results_changed's plan
        # (detail/heroPlaytime/standings/encounters) — neither is a superset of
        # the other, so both must be published or one invalidation is dropped.
        session = SimpleNamespace(info={})

        realtime_commit.register_tournament_realtime_update(session, 42, "results_changed")
        realtime_commit.register_tournament_realtime_update(session, 42, "registration_changed")

        updates = realtime_commit.pop_registered_tournament_realtime_updates(session)
        self.assertEqual(set(updates), {(42, "results_changed"), (42, "registration_changed")})

    async def test_structure_changed_absorbs_registration_changed(self) -> None:
        # structure_changed's plan already includes the registration keys, so a
        # redundant second event would add nothing.
        session = SimpleNamespace(info={})

        realtime_commit.register_tournament_realtime_update(session, 42, "registration_changed")
        realtime_commit.register_tournament_realtime_update(session, 42, "structure_changed")

        updates = realtime_commit.pop_registered_tournament_realtime_updates(session)
        self.assertEqual(updates, [(42, "structure_changed")])

    async def test_form_changed_survives_every_other_reason(self) -> None:
        # The form key is in no other reason's plan — not even
        # structure_changed's — so folding it away would silently drop the only
        # signal an admin form edit produces.
        session = SimpleNamespace(info={})

        realtime_commit.register_tournament_realtime_update(session, 42, "registration_form_changed")
        realtime_commit.register_tournament_realtime_update(session, 42, "structure_changed")

        updates = realtime_commit.pop_registered_tournament_realtime_updates(session)
        self.assertEqual(set(updates), {(42, "structure_changed"), (42, "registration_form_changed")})

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
