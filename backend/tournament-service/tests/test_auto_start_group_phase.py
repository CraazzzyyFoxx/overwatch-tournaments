"""Going LIVE starts the tournament's first group PHASE, not its first stage.

Stages sharing an ``order`` run in parallel (a Low and a High division), so both
have to be generated/activated; a stage of a later phase must stay untouched.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

enums = importlib.import_module("shared.core.enums")
tournament_service = importlib.import_module("src.services.admin.tournament")

LIVE = enums.TournamentStatus.LIVE


def _group_stage(stage_id: int, order: int, *, is_active: bool = False, teams: int = 4) -> SimpleNamespace:
    inputs = [SimpleNamespace(team_id=index + 1) for index in range(teams)]
    return SimpleNamespace(
        id=stage_id,
        order=order,
        stage_type=enums.StageType.ROUND_ROBIN,
        is_active=is_active,
        is_completed=False,
        items=[SimpleNamespace(id=stage_id * 10, inputs=inputs)],
    )


class AutoStartGroupPhaseTests(IsolatedAsyncioTestCase):
    async def test_both_parallel_divisions_of_the_first_phase_start(self) -> None:
        tournament = SimpleNamespace(
            id=99,
            stages=[
                _group_stage(1, order=1),
                _group_stage(2, order=1),
                _group_stage(3, order=2),
            ],
        )
        session = SimpleNamespace()

        with (
            patch.object(
                tournament_service.AdminTournamentService,
                "_stage_has_encounters",
                AsyncMock(return_value=False),
            ),
            patch.object(tournament_service, "request_bracket_job", AsyncMock()) as job,
        ):
            await tournament_service.tournament_service._maybe_auto_start_group_stage(
                session, tournament, target_status=LIVE
            )

        started = [call.kwargs["stage_id"] for call in job.await_args_list]
        self.assertEqual([1, 2], started)
        self.assertEqual({"activate_and_generate"}, {call.kwargs["operation"] for call in job.await_args_list})

    async def test_an_already_active_division_does_not_drag_its_phase_siblings_along(self) -> None:
        """One division live and mid-play, the other still Draft: the live one is
        the tournament's answer for "which stage is running", and re-generating
        its Draft sibling behind the organizer's back is not this hook's job."""
        tournament = SimpleNamespace(
            id=99,
            stages=[_group_stage(1, order=1, is_active=True), _group_stage(2, order=1)],
        )
        session = SimpleNamespace()

        with (
            patch.object(
                tournament_service.AdminTournamentService,
                "_stage_has_encounters",
                AsyncMock(return_value=True),
            ),
            patch.object(tournament_service, "request_bracket_job", AsyncMock()) as job,
        ):
            await tournament_service.tournament_service._maybe_auto_start_group_stage(
                session, tournament, target_status=LIVE
            )

        job.assert_not_awaited()
