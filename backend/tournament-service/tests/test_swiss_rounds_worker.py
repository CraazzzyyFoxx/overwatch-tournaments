from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


enums = importlib.import_module("shared.core.enums")
swiss_rounds = importlib.import_module("src.services.standings.swiss_auto_round")
standings = importlib.import_module("src.services.standings.service")


def _round(round_number: int, *, completed: bool, stage_item_id: int = 501):
    """One duel of the scope, flattened the way ``load_stage_encounters`` hands it over."""
    return standings.StageEncounter(
        id=round_number,
        round=round_number,
        stage_id=77,
        stage_item_id=stage_item_id,
        completed=completed,
        seats=(
            standings.Seat(team_id=1, slot=1, score=2.0 if completed else 0.0, placement=1 if completed else None),
            standings.Seat(team_id=2, slot=2, score=0.0, placement=2 if completed else None),
        ),
    )


class SwissRoundWorkerTests(IsolatedAsyncioTestCase):
    async def test_generated_round_does_not_commit_or_recalculate_directly(self) -> None:
        stage_item = SimpleNamespace(id=501)
        stage = SimpleNamespace(id=77, status="live", items=[stage_item], max_rounds=5)
        encounters = [_round(1, completed=True)]
        skeleton = SimpleNamespace(pairings=[SimpleNamespace(round_number=2)])
        generated = [SimpleNamespace(id=101)]

        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())

        with (
            patch.object(swiss_rounds.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(swiss_rounds, "_collect_item_team_ids", Mock(return_value=[1, 2])),
            patch.object(swiss_rounds.stage_service, "_generate_stage_skeleton", AsyncMock(return_value=skeleton)),
            patch.object(standings.standings_service, "load_stage_encounters", AsyncMock(return_value=encounters)),
            patch.object(swiss_rounds.stage_service, "_seat_teams", AsyncMock(return_value={})),
            patch.object(
                swiss_rounds.stage_service,
                "_create_encounters_from_skeleton",
                AsyncMock(return_value=generated),
            ),
            patch.object(swiss_rounds, "lifecycle_notifier", AsyncMock()),
        ):
            result = await swiss_rounds.swiss_rounds_service.generate_next_swiss_round(
                session,
                tournament_id=999,
                stage_id=77,
                stage_item_id=501,
                expected_next_round=2,
            )

        self.assertEqual(generated, result)
        session.commit.assert_not_awaited()

    async def test_stale_round_is_idempotently_skipped(self) -> None:
        stage_item = SimpleNamespace(id=501)
        stage = SimpleNamespace(id=77, status="live", items=[stage_item], max_rounds=5)
        # Round 2 already exists (and is still being played): the event is stale.
        encounters = [_round(2, completed=False)]
        session = SimpleNamespace()

        with (
            patch.object(swiss_rounds.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(swiss_rounds, "_collect_item_team_ids", Mock(return_value=[1, 2])),
            patch.object(standings.standings_service, "load_stage_encounters", AsyncMock(return_value=encounters)),
            patch.object(swiss_rounds.stage_service, "_generate_stage_skeleton", AsyncMock()) as generate,
        ):
            result = await swiss_rounds.swiss_rounds_service.generate_next_swiss_round(
                session,
                tournament_id=999,
                stage_id=77,
                stage_item_id=501,
                expected_next_round=2,
            )

        self.assertEqual([], result)
        generate.assert_not_awaited()

    async def test_generate_ready_rounds_does_not_enqueue_a_bracket_job(self) -> None:
        item = SimpleNamespace(id=501)
        stage = SimpleNamespace(id=77, status="live", items=[item], max_rounds=5)
        generated = [SimpleNamespace(id=101)]

        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [stage])))
        )

        with (
            patch.object(standings.standings_service, "load_stage_encounters", AsyncMock(return_value=[])),
            patch.object(swiss_rounds, "stage_item_ready_for_next_round", return_value=True),
            patch.object(swiss_rounds, "next_round_number", return_value=2),
            patch.object(
                swiss_rounds.swiss_rounds_service,
                "generate_next_swiss_round",
                AsyncMock(return_value=generated),
            ) as generate,
        ):
            result = await swiss_rounds.swiss_rounds_service.generate_ready_rounds(session, 999)

        self.assertEqual(generated, result)
        self.assertFalse(hasattr(swiss_rounds, "request_bracket_job"))
        generate.assert_awaited_once()
        self.assertEqual(77, generate.await_args.kwargs["stage_id"])
        self.assertIs(stage, generate.await_args.kwargs["stage"])
