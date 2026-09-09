from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"

flows = importlib.import_module("src.services.match_logs.flows")
enums = importlib.import_module("src.core.enums")

from shared.services.realtime import Resource, Scope  # noqa: E402


def _encounter(*, status: Any, home_score: int, away_score: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        tournament_id=42,
        home_team_id=1,
        away_team_id=2,
        home_score=home_score,
        away_score=away_score,
        status=status,
        result_status=enums.EncounterResultStatus.NONE,
    )


class MatchLogOutboxTests(IsolatedAsyncioTestCase):
    async def test_a_parsed_log_stales_encounters_and_standings_on_both_rails(self) -> None:
        # Two rails for one fact, by design: emit() for this service's own cache
        # and every connected client, the outbox row for tournament-service and
        # app-service, whose cashews entries have no TTL-plus-replay safety net
        # if a Redis publish is lost.
        session = object()
        encounter = _encounter(status=enums.EncounterStatus.COMPLETED, home_score=3, away_score=1)

        with (
            patch.object(flows, "emit", AsyncMock()) as emit,
            patch.object(flows, "enqueue_invalidation_outbox", AsyncMock()) as invalidate,
            patch.object(flows, "enqueue_outbox_event", AsyncMock()) as enqueue,
        ):
            await flows._enqueue_match_log_tournament_events(session, encounter)

        emit.assert_awaited_once()
        self.assertIs(emit.await_args.args[0], session)
        self.assertEqual(Scope.tournament(42), emit.await_args.kwargs["scope"])
        self.assertEqual(
            [Resource.TOURNAMENT_ENCOUNTERS, Resource.TOURNAMENT_STANDINGS],
            emit.await_args.kwargs["invalidates"],
        )
        self.assertEqual({"encounter_ids": [7]}, emit.await_args.kwargs["entity_ids"])

        invalidate.assert_awaited_once()
        self.assertEqual(Scope.tournament(42), invalidate.await_args.kwargs["scope"])
        self.assertEqual(
            (Resource.TOURNAMENT_ENCOUNTERS, Resource.TOURNAMENT_STANDINGS),
            invalidate.await_args.kwargs["resources"],
        )

        # The two domain events are unrelated to caching and stay as they were:
        # a durable standings recalculation request, and the completed-encounter
        # fan-out that only fires for a finished encounter.
        self.assertEqual(2, enqueue.await_count)
        recalc_call, completed_call = enqueue.await_args_list
        self.assertIs(recalc_call.args[0], session)
        self.assertEqual("tournament_standings_invalidated", recalc_call.args[1].event_type)
        self.assertEqual("parser-service", recalc_call.args[1].source_service)
        self.assertEqual("tournament.standings.invalidated", recalc_call.kwargs["routing_key"])
        self.assertEqual("encounter_completed", completed_call.args[1].event_type)
        self.assertEqual(7, completed_call.args[1].encounter_id)
        self.assertEqual(1, completed_call.args[1].winner_team_id)
        self.assertEqual("tournament.encounter.completed", completed_call.kwargs["routing_key"])

    async def test_an_open_encounter_publishes_no_completion(self) -> None:
        encounter = _encounter(status=enums.EncounterStatus.OPEN, home_score=0, away_score=0)

        with (
            patch.object(flows, "emit", AsyncMock()),
            patch.object(flows, "enqueue_invalidation_outbox", AsyncMock()),
            patch.object(flows, "enqueue_outbox_event", AsyncMock()) as enqueue,
        ):
            await flows._enqueue_match_log_tournament_events(object(), encounter)

        self.assertEqual(1, enqueue.await_count)
        self.assertEqual("tournament_standings_invalidated", enqueue.await_args_list[0].args[1].event_type)
