"""Generating FFA lobbies: one lobby per group that has none yet.

A lobby is not a bracket -- nothing here goes through ``generate_bracket``, so
these tests pin the seating (input slot order), the ``best_of`` the stage
configures, the 2..100 size guard and the "nothing left to generate" refusal.
The last test pins the other half of task 6: a bracket can qualify teams out of
an ``ffa_league`` stage, which the group-source guard used to reject.
"""

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
errors = importlib.import_module("shared.core.errors")
stage_service = importlib.import_module("src.services.admin.stage")
stage_base = importlib.import_module("src.services.admin.stage.base")
stage_generation = importlib.import_module("src.services.admin.stage.generation")
ffa_module = importlib.import_module("src.services.encounter.ffa")

from shared import models  # noqa: E402
from shared.models.encounter import Encounter  # noqa: E402
from shared.models.tournament.bracket_encounter import BracketEncounter  # noqa: E402
from shared.services.encounter.participants import active_teams  # noqa: E402
from tests._encounter_layer import EncounterLayerCase  # noqa: E402
from tests._stage_regulation import stage_regulation  # noqa: E402

HTTPException = errors.BaseAPIException


def _rows_result(rows: list[tuple]) -> SimpleNamespace:
    """Mimics ``Result.all()`` for the ``(stage_item_id, count)`` group-by."""
    return SimpleNamespace(all=lambda: rows)


def _input(slot: int, team_id: int) -> SimpleNamespace:
    return SimpleNamespace(slot=slot, team_id=team_id, input_type=enums.StageItemInputType.FINAL)


def _item(item_id: int, name: str, *, order: int = 0, team_ids: list[int] | None = None) -> SimpleNamespace:
    # Inputs deliberately out of slot order: seating must follow ``slot``.
    inputs = [_input(slot, team_id) for slot, team_id in enumerate(team_ids or [], 1)]
    return SimpleNamespace(id=item_id, name=name, order=order, type=None, inputs=list(reversed(inputs)))


def _ffa_stage(items: list[SimpleNamespace], **regulation) -> SimpleNamespace:
    return SimpleNamespace(
        **stage_regulation(**regulation),
        id=77,
        tournament_id=1,
        stage_type=enums.StageType.FFA_LEAGUE,
        items=items,
        is_published=False,
    )


def _session(rows: list[tuple]) -> SimpleNamespace:
    return SimpleNamespace(
        execute=AsyncMock(return_value=_rows_result(rows)),
        add=Mock(),
        flush=AsyncMock(),
    )


class FfaLobbyGenerationTests(IsolatedAsyncioTestCase):
    async def test_generates_one_lobby_for_the_group_that_has_none(self) -> None:
        """Group A already has its lobby; only Group B is generated, seated in
        input-slot order, with the stage's configured ``best_of``."""
        item_a = _item(1, "Group A", order=0, team_ids=[10, 20])
        item_b = _item(2, "Group B", order=1, team_ids=[30, 40, 50])
        stage = _ffa_stage([item_a, item_b], best_of_default=5)
        session = _session([(1, 1)])
        lobby = SimpleNamespace(id=901)

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(
                stage_generation.ffa_encounter_service, "create_lobby", AsyncMock(return_value=lobby)
            ) as create,
            patch.object(stage_base, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            result = await stage_service.stage_service.generate_encounters(session, 77, commit=False)

        self.assertEqual([lobby], result)
        create.assert_awaited_once()
        self.assertIs(item_b, create.await_args.args[2])
        self.assertEqual([30, 40, 50], list(create.await_args.args[3]))
        self.assertEqual(5, create.await_args.kwargs["games"])

    async def test_rejects_when_every_group_already_has_a_lobby(self) -> None:
        stage = _ffa_stage([_item(1, "Group A", team_ids=[10, 20]), _item(2, "Group B", order=1, team_ids=[30, 40])])
        session = _session([(1, 1), (2, 1)])

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_generation.ffa_encounter_service, "create_lobby", AsyncMock()) as create,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await stage_service.stage_service.generate_encounters(session, 77, commit=False)

        self.assertEqual(409, ctx.exception.status_code)
        create.assert_not_awaited()

    async def test_rejects_a_group_of_one_team(self) -> None:
        stage = _ffa_stage([_item(1, "Group A", team_ids=[10])])
        session = _session([])

        with patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)):
            with self.assertRaises(HTTPException) as ctx:
                await stage_service.stage_service.generate_encounters(session, 77, commit=False)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertEqual(["ffa_lobby_size"], [err.code for err in ctx.exception.detail])

    async def test_rejects_a_group_over_the_lobby_cap(self) -> None:
        stage = _ffa_stage([_item(1, "Group A", team_ids=list(range(1, 102)))])
        session = _session([])

        with patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)):
            with self.assertRaises(HTTPException) as ctx:
                await stage_service.stage_service.generate_encounters(session, 77, commit=False)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertEqual(["ffa_lobby_size"], [err.code for err in ctx.exception.detail])


class FfaLobbyCreationTests(EncounterLayerCase):
    """``create_lobby`` writes the lobby the rest of the layer reads: a card of
    N seats under the stage's points rule, with its bracket coordinate."""

    async def test_create_lobby_seats_participants_and_sizes_the_card(self) -> None:
        async with self.Session() as s:
            stage = await s.get_one(models.Stage, self.stage_id)
            item = await s.get_one(models.StageItem, self.item_id)
            teams = [self.teams[2], self.teams[0], self.teams[1]]

            lobby = await ffa_module.ffa_encounter_service.create_lobby(
                s, stage, item, teams, games=5, names={team: f"n{team}" for team in teams}
            )
            await s.commit()

            row = await s.get_one(Encounter, lobby.id)
            position = await s.get_one(BracketEncounter, lobby.id)
            seats = await active_teams(s, lobby.id)

        self.assertEqual((3, 5, "A"), (row.slot_count, row.best_of, row.name))
        self.assertEqual(stage.scoring_rule_id, row.scoring_rule_id)
        self.assertEqual(enums.EncounterStatus.OPEN, row.status)
        self.assertEqual((self.stage_id, self.item_id), (position.stage_id, position.stage_item_id))
        # The slot is the seed: teams arrive in seed order.
        self.assertEqual(
            [(1, teams[0], 1), (2, teams[1], 2), (3, teams[2], 3)],
            [(seat.slot, seat.team_id, seat.seed) for seat in seats],
        )
        self.assertEqual([f"n{team}" for team in teams], [seat.name for seat in seats])

    async def test_a_lobby_of_one_team_is_refused(self) -> None:
        async with self.Session() as s:
            stage = await s.get_one(models.Stage, self.stage_id)
            item = await s.get_one(models.StageItem, self.item_id)
            with self.assertRaises(HTTPException) as ctx:
                await ffa_module.ffa_encounter_service.create_lobby(s, stage, item, [self.teams[0]], games=3)

        self.assertEqual(400, ctx.exception.status_code)


class FfaAsQualifyingSourceTests(IsolatedAsyncioTestCase):
    async def test_wire_from_groups_accepts_an_ffa_league_source(self) -> None:
        source = SimpleNamespace(
            id=1,
            tournament_id=99,
            stage_type=enums.StageType.FFA_LEAGUE,
            items=[SimpleNamespace(id=100, name="A", order=0, inputs=[])],
        )
        target = SimpleNamespace(
            id=2,
            tournament_id=99,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            bracket_template=None,
            items=[
                SimpleNamespace(id=200, name="Playoffs", type=enums.StageItemType.BRACKET_UPPER, order=0, inputs=[])
            ],
        )
        added_inputs: list = []
        session = SimpleNamespace(add=Mock(side_effect=added_inputs.append), commit=AsyncMock(), flush=AsyncMock())

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(side_effect=[target, source, target])),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            await stage_service.stage_service.wire_from_groups(
                session,
                target_stage_id=target.id,
                source_stage_id=source.id,
                top=2,
            )

        self.assertEqual(
            [(1, 100, 1), (2, 100, 2)],
            [(i.slot, i.source_stage_item_id, i.source_position) for i in added_inputs],
        )
