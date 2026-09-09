"""What each tournament write announces, in resources.

The publisher now names WHAT went stale, never WHY. These tests pin the resource
set each producer stages, the union that replaces the old "strongest reason
wins" merge, and the one surviving reason->resource translation: the legacy
``tournament.changed`` consumer, kept only until parser-service and
balancer-service stop publishing to that exchange.

Staging is inspected through ``session.info["realtime_staged"]`` because these
are fake sessions with no database behind them; the rail's own persistence and
publication contract is covered by ``backend/tests/test_realtime_emit.py``.
"""

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

recalculation_events = importlib.import_module("src.services.tournament.recalculation_events")
tournament_events = importlib.import_module("src.services.tournament.events")

from shared.services.realtime import Resource, Scope  # noqa: E402


def _fake_session(**extra: object) -> SimpleNamespace:
    return SimpleNamespace(info={}, add=Mock(), flush=AsyncMock(), **extra)


def _staged_invalidations(session: SimpleNamespace) -> dict:
    staged = session.info.get("realtime_staged")
    return {} if staged is None else staged.invalidations


def _staged_resources(session: SimpleNamespace, scope: Scope) -> set[Resource]:
    return _staged_invalidations(session)[scope][0]



class TournamentProducerResourceTests(IsolatedAsyncioTestCase):
    async def test_recalculation_stales_encounters_only(self) -> None:
        # ``scalar`` answers the scrim-container probe the recalculation makes
        # before queueing a job; ``None`` means "an ordinary tournament".
        session = _fake_session(scalar=AsyncMock(return_value=None))

        with patch.object(tournament_events.jobs_service, "request_standings_recalculation", AsyncMock()) as request:
            await tournament_events.enqueue_tournament_recalculation(session, 42)

        request.assert_awaited_once_with(session, 42)
        self.assertEqual(_staged_resources(session, Scope.tournament(42)), {Resource.TOURNAMENT_ENCOUNTERS})

    async def test_registration_decision_stales_registrations_and_names_the_row(self) -> None:
        # BalancerRegistration has no denormalized workspace_id column —
        # enqueue_registration_approved derives it via a tournament lookup, and
        # the event's user_id likewise comes from the workspace_member anchor.
        session = _fake_session(scalar=AsyncMock(return_value=3))
        registration = SimpleNamespace(id=77, tournament_id=42, battle_tag="tag#1", workspace_member_id=5)

        with (
            patch.object(tournament_events, "_notify_registration_decision", AsyncMock()),
            patch.object(tournament_events, "enqueue_outbox_event", AsyncMock()),
        ):
            await tournament_events.enqueue_registration_approved(session, registration)

        resources, entity_ids = _staged_invalidations(session)[Scope.tournament(42)]
        self.assertEqual(resources, {Resource.TOURNAMENT_REGISTRATIONS})
        self.assertEqual(entity_ids, {"registration_ids": [77]})

    async def test_publish_invalidation_stages_both_halves(self) -> None:
        # Forgetting the cross-service half is silent: the page repairs itself
        # while app-service serves its cached aggregate until the TTL.
        session = _fake_session()

        with patch.object(tournament_events, "enqueue_invalidation_outbox", AsyncMock()) as outbox:
            await tournament_events.publish_tournament_invalidation(
                session, 42, tournament_events.STRUCTURE_RESOURCES
            )

        self.assertEqual(_staged_resources(session, Scope.tournament(42)), {Resource.TOURNAMENT_STRUCTURE})
        self.assertEqual(outbox.await_args.kwargs["scope"], Scope.tournament(42))
        self.assertEqual(outbox.await_args.kwargs["resources"], tournament_events.STRUCTURE_RESOURCES)

    async def test_two_writes_in_one_transaction_union_into_one_invalidation(self) -> None:
        # Replaces the old "strongest reason wins" merge: union is commutative
        # and idempotent, so no producer has to know what the others staged.
        session = _fake_session(scalar=AsyncMock(return_value=None))

        with (
            patch.object(tournament_events.jobs_service, "request_standings_recalculation", AsyncMock()),
            patch.object(tournament_events, "enqueue_outbox_event", AsyncMock()),
        ):
            await tournament_events.enqueue_tournament_recalculation(session, 42)
            await tournament_events.publish_tournament_invalidation(
                session, 42, tournament_events.STRUCTURE_RESOURCES
            )

        self.assertEqual(list(_staged_invalidations(session)), [Scope.tournament(42)])
        self.assertEqual(
            _staged_resources(session, Scope.tournament(42)),
            {Resource.TOURNAMENT_ENCOUNTERS, Resource.TOURNAMENT_STRUCTURE},
        )
