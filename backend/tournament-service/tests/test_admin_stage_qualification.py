"""Qualification is frozen deliberately, not accidentally.

Two defects are pinned here.

``activate_stage`` used to read ``standings[position - 1]`` straight out of the
table, so a boundary the standings themselves marked as unresolved
(``tie_group``) got decided by the technical ``team_id`` fallback -- an
automatic qualification nobody adjudicated.

And once activation turned an input FINAL, a later correction of the group
result was invisible to it: the playoff kept the team that no longer qualified,
with neither an automatic re-qualification nor a refusal of the correction.
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

stage_service = importlib.import_module("src.services.admin.stage")
enums = importlib.import_module("shared.core.enums")

service = stage_service.stage_service


class _Result:
    """The two shapes ``AsyncSession.execute`` results are consumed in here."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> list:
        return self._rows

    def all(self) -> list:
        return self._rows


def _session(results: list) -> SimpleNamespace:
    return SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(rows) for rows in results]),
        scalar=AsyncMock(return_value=None),
        commit=AsyncMock(),
        flush=AsyncMock(),
    )


def _standing(*, stage_item_id: int, position: int, team_id: int, tie_group: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        stage_item_id=stage_item_id,
        position=position,
        team_id=team_id,
        tie_group=tie_group,
    )


def _tentative(*, slot: int, source_position: int) -> SimpleNamespace:
    return SimpleNamespace(
        slot=slot,
        stage_item_id=200,
        input_type=enums.StageItemInputType.TENTATIVE,
        team_id=None,
        source_stage_item_id=100,
        source_position=source_position,
    )


def _final(*, team_id: int, source_position: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        slot=1,
        stage_item_id=200,
        input_type=enums.StageItemInputType.FINAL,
        team_id=team_id,
        source_stage_item_id=100,
        source_position=source_position,
    )


def _playoff(inputs: list) -> SimpleNamespace:
    return SimpleNamespace(
        id=2,
        tournament_id=99,
        order=1,
        stage_type=enums.StageType.SINGLE_ELIMINATION,
        is_active=False,
        is_published=False,
        items=[SimpleNamespace(id=200, name="Playoffs", order=0, inputs=inputs)],
    )


def _encounter(*, home_team_id: int, away_team_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=500,
        stage_id=2,
        stage_item_id=200,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        name="A vs B",
        status=enums.EncounterStatus.OPEN,
        home_score=0,
        away_score=0,
        result_status=enums.EncounterResultStatus.NONE,
    )


class QualificationBoundaryTieTests(IsolatedAsyncioTestCase):
    """Item 9: a tie the standings could not break must not be broken by row order."""

    async def _activate(self, standings: list) -> SimpleNamespace:
        stage = _playoff([_tentative(slot=1, source_position=1)])
        # 1: the sibling-stage deactivation UPDATE, 2: the standings SELECT.
        session = _session([[], standings])
        with patch.object(service, "_publish_structure_changed", AsyncMock()):
            await service.activate_stage(session, stage.id, stage=stage)
        return stage

    async def test_unresolved_tie_at_the_boundary_refuses_activation(self) -> None:
        standings = [
            _standing(stage_item_id=100, position=1, team_id=1, tie_group=1),
            _standing(stage_item_id=100, position=2, team_id=2, tie_group=1),
        ]
        with self.assertRaises(Exception) as ctx:
            await self._activate(standings)

        self.assertEqual(409, ctx.exception.status_code)
        self.assertIn("unresolved tie at qualification boundary", str(ctx.exception.detail))
        # Names what the admin has to go and fix.
        self.assertIn("100", str(ctx.exception.detail))
        self.assertIn("position 1", str(ctx.exception.detail))

    async def test_distinct_tie_groups_resolve_normally(self) -> None:
        standings = [
            _standing(stage_item_id=100, position=1, team_id=7, tie_group=1),
            _standing(stage_item_id=100, position=2, team_id=8, tie_group=2),
        ]
        stage = await self._activate(standings)

        inp = stage.items[0].inputs[0]
        self.assertEqual(7, inp.team_id)
        self.assertEqual(enums.StageItemInputType.FINAL, inp.input_type)

    async def test_tie_below_the_last_standing_is_not_a_boundary(self) -> None:
        """Nothing follows the last row, so there is no boundary to be tied across."""
        standings = [
            _standing(stage_item_id=100, position=1, team_id=5, tie_group=None),
            _standing(stage_item_id=100, position=2, team_id=6, tie_group=3),
        ]
        stage = _playoff([_tentative(slot=1, source_position=2)])
        session = _session([[], standings])
        with patch.object(service, "_publish_structure_changed", AsyncMock()):
            await service.activate_stage(session, stage.id, stage=stage)

        self.assertEqual(6, stage.items[0].inputs[0].team_id)


class DownstreamRequalificationTests(IsolatedAsyncioTestCase):
    """Item 10: a corrected group result re-qualifies an untouched playoff."""

    async def test_untouched_downstream_is_requalified(self) -> None:
        inp = _final(team_id=1)
        stage = _playoff([inp])
        encounter = _encounter(home_team_id=1, away_team_id=2)
        session = _session(
            [
                # standings for the source item: team 3 now holds position 1
                [
                    _standing(stage_item_id=100, position=1, team_id=3, tie_group=None),
                    _standing(stage_item_id=100, position=2, team_id=1, tie_group=None),
                ],
                [],  # no touched stage items
                [encounter],  # the encounter holding the outgoing team
                [(3, "Charlie"), (2, "Bravo")],  # team names
            ]
        )
        sync = AsyncMock()
        with (
            patch.object(service, "get_stages_by_tournament", AsyncMock(return_value=[stage])),
            patch.object(
                stage_service.pick_ban_session_service,
                "sync_all_pick_ban_sessions_after_team_change",
                sync,
            ),
        ):
            applied = await service.requalify_downstream_inputs(session, 99)

        self.assertEqual(1, applied)
        self.assertEqual(3, inp.team_id)
        self.assertEqual(3, encounter.home_team_id)
        self.assertEqual("Charlie vs Bravo", encounter.name)
        sync.assert_awaited_once()

    async def test_swapped_seeds_move_simultaneously(self) -> None:
        """1st and 2nd trade places: slot-by-slot replacement would send the
        second rename through the first one's result and leave A vs A."""
        first = _final(team_id=1, source_position=1)
        second = _final(team_id=2, source_position=2)
        second.slot = 2
        stage = _playoff([first, second])
        encounter = _encounter(home_team_id=1, away_team_id=2)
        session = _session(
            [
                [
                    _standing(stage_item_id=100, position=1, team_id=2, tie_group=None),
                    _standing(stage_item_id=100, position=2, team_id=1, tie_group=None),
                ],
                [],  # no touched stage items
                [encounter],  # one query for the whole item
                [(1, "Alpha"), (2, "Bravo")],
            ]
        )
        with (
            patch.object(service, "get_stages_by_tournament", AsyncMock(return_value=[stage])),
            patch.object(
                stage_service.pick_ban_session_service,
                "sync_all_pick_ban_sessions_after_team_change",
                AsyncMock(),
            ),
        ):
            applied = await service.requalify_downstream_inputs(session, 99)

        self.assertEqual(2, applied)
        self.assertEqual((2, 1), (first.team_id, second.team_id))
        self.assertEqual((2, 1), (encounter.home_team_id, encounter.away_team_id))
        self.assertEqual("Bravo vs Alpha", encounter.name)

    async def test_started_downstream_is_left_alone(self) -> None:
        inp = _final(team_id=1)
        stage = _playoff([inp])
        session = _session(
            [
                [
                    _standing(stage_item_id=100, position=1, team_id=3, tie_group=None),
                    _standing(stage_item_id=100, position=2, team_id=1, tie_group=None),
                ],
                [200],  # stage item 200 has been touched
            ]
        )
        with patch.object(service, "get_stages_by_tournament", AsyncMock(return_value=[stage])):
            applied = await service.requalify_downstream_inputs(session, 99)

        self.assertEqual(0, applied)
        self.assertEqual(1, inp.team_id)

    async def test_unresolved_tie_is_not_requalified_either(self) -> None:
        inp = _final(team_id=1)
        stage = _playoff([inp])
        session = _session(
            [
                [
                    _standing(stage_item_id=100, position=1, team_id=3, tie_group=4),
                    _standing(stage_item_id=100, position=2, team_id=1, tie_group=4),
                ],
            ]
        )
        with patch.object(service, "get_stages_by_tournament", AsyncMock(return_value=[stage])):
            applied = await service.requalify_downstream_inputs(session, 99)

        self.assertEqual(0, applied)
        self.assertEqual(1, inp.team_id)


class SourceCorrectionGuardTests(IsolatedAsyncioTestCase):
    """Item 10, other half: refuse what re-qualification can no longer repair."""

    async def test_started_downstream_blocks_the_correction(self) -> None:
        session = _session([[200], [200]])
        with self.assertRaises(Exception) as ctx:
            await service.assert_source_correction_allowed(session, _encounter(home_team_id=1, away_team_id=2))

        self.assertEqual(409, ctx.exception.status_code)
        self.assertIn("downstream stage already in progress", str(ctx.exception.detail))

    async def test_untouched_downstream_allows_the_correction(self) -> None:
        session = _session([[200], []])
        await service.assert_source_correction_allowed(session, _encounter(home_team_id=1, away_team_id=2))

    async def test_no_downstream_inputs_short_circuits(self) -> None:
        session = _session([[]])
        await service.assert_source_correction_allowed(session, _encounter(home_team_id=1, away_team_id=2))
        self.assertEqual(1, session.execute.await_count)
