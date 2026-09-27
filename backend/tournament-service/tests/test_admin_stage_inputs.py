"""Stage inputs, re-seeding and regulation edits keep their invariants.

Four defects are pinned here.

A Swiss stage allowed as many rounds as a full circle was silently generated as
a complete round robin -- and for an ODD field the shortcut fired a round early,
handing out more rounds than the configured maximum.

Re-seeding only ever added or overwrote the slots it was given: shrinking the
advance from top-2 to top-1 left the second-place inputs behind, and a preserved
TENTATIVE input was collided with rather than skipped, because the free slot was
found once and then counted up from.

Creating a stage input checked none of the invariants editing one checks, so an
input the update endpoint refuses could be created outright.

And ``update_stage`` was a plain field write: the format of a stage that already
had matches could be flipped under them, and an unusable ``scoring`` blob passed
the schema and only exploded later inside the points adder.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

import pydantic

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

stage_service = importlib.import_module("src.services.admin.stage")
stage_common = importlib.import_module("src.services.admin.stage_common")
schemas = importlib.import_module("src.schemas")
enums = importlib.import_module("shared.core.enums")

from tests._stage_regulation import stage_regulation  # noqa: E402

service = stage_service.stage_service


def _input(*, slot: int, input_type, team_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=slot,
        slot=slot,
        stage_item_id=200,
        input_type=input_type,
        team_id=team_id,
        source_stage_item_id=100 if input_type == enums.StageItemInputType.TENTATIVE else None,
        source_position=slot if input_type == enums.StageItemInputType.TENTATIVE else None,
    )


class SwissRoundRobinShortcutTests(IsolatedAsyncioTestCase):
    """Item 5: the shortcut may only fire for a genuinely full circle."""

    def setUp(self) -> None:
        self.session = SimpleNamespace()
        self.recorded = AsyncMock()
        patches = (
            patch.object(stage_service, "record_swiss_bye", self.recorded),
            patch.object(stage_service, "clear_swiss_byes", AsyncMock()),
            patch.object(stage_service, "clear_swiss_scope_stopped", AsyncMock()),
            patch.object(stage_service, "mark_swiss_scope_stopped", AsyncMock()),
            patch.object(stage_service, "swiss_bye_team_ids", AsyncMock(return_value=[])),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _stage(self, *, max_rounds: int) -> SimpleNamespace:
        return SimpleNamespace(
            id=1,
            tournament_id=99,
            stage_type=enums.StageType.SWISS,
            max_rounds=max_rounds,
        )

    async def _skeleton(self, *, teams: int, max_rounds: int):
        stage = self._stage(max_rounds=max_rounds)
        with patch.object(
            service,
            "_get_swiss_generation_context",
            AsyncMock(return_value=(None, None, 1)),
        ):
            return await service._generate_stage_skeleton(
                self.session,
                stage,
                list(range(1, teams + 1)),
                200,
            )

    async def test_odd_field_one_round_short_stays_swiss(self) -> None:
        """5 teams need 5 rounds for a full circle, not 4 -- so 4 is still Swiss."""
        skeleton = await self._skeleton(teams=5, max_rounds=4)

        # One Swiss round of 5 teams: two matches and a bye, not all 10 matches.
        self.assertEqual(2, len(skeleton.pairings))
        self.assertIsNotNone(skeleton.bye_team_id)
        self.assertEqual({1}, {pairing.round_number for pairing in skeleton.pairings})

    async def test_even_field_at_a_full_circle_takes_the_shortcut(self) -> None:
        skeleton = await self._skeleton(teams=6, max_rounds=5)

        # Whole round robin at once: 6 * 5 / 2 matches over 5 rounds.
        self.assertEqual(15, len(skeleton.pairings))
        self.assertEqual({1, 2, 3, 4, 5}, {pairing.round_number for pairing in skeleton.pairings})

    async def test_bye_is_recorded_against_the_round_it_happened_in(self) -> None:
        stage = self._stage(max_rounds=4)
        with patch.object(
            service,
            "_get_swiss_generation_context",
            AsyncMock(return_value=(None, None, 3)),
        ):
            await service._generate_stage_skeleton(self.session, stage, [1, 2, 3, 4, 5], 200)

        self.recorded.assert_awaited_once_with(self.session, 1, 200, 5, round_number=3)


class ApplySeedingTests(TestCase):
    """Item 14, first half: re-seeding replaces, it does not accumulate."""

    def test_shrinking_the_seeding_drops_the_tail(self) -> None:
        target_item = SimpleNamespace(
            id=200,
            inputs=[
                _input(slot=1, input_type=enums.StageItemInputType.TENTATIVE),
                _input(slot=2, input_type=enums.StageItemInputType.TENTATIVE),
                _input(slot=3, input_type=enums.StageItemInputType.TENTATIVE),
            ],
        )
        session = SimpleNamespace(add=Mock())

        stage_common._apply_seeding(session, [(100, 1), (101, 1)], target_item)

        self.assertEqual([1, 2], [inp.slot for inp in target_item.inputs])

    def test_manually_assigned_inputs_survive_the_tail_cut(self) -> None:
        target_item = SimpleNamespace(
            id=200,
            inputs=[
                _input(slot=1, input_type=enums.StageItemInputType.TENTATIVE),
                _input(slot=2, input_type=enums.StageItemInputType.FINAL, team_id=777),
            ],
        )
        session = SimpleNamespace(add=Mock())

        stage_common._apply_seeding(session, [(100, 1)], target_item)

        self.assertEqual([1, 2], [inp.slot for inp in target_item.inputs])
        self.assertEqual(777, target_item.inputs[1].team_id)


class SeedTeamsSlotTests(IsolatedAsyncioTestCase):
    """Item 14, second half: every assigned slot is checked for occupancy."""

    async def test_preserved_tentative_slot_is_skipped_not_collided_with(self) -> None:
        preserved = _input(slot=2, input_type=enums.StageItemInputType.TENTATIVE)
        stage = SimpleNamespace(
            id=1,
            tournament_id=99,
            stage_type=enums.StageType.ROUND_ROBIN,
            items=[SimpleNamespace(id=200, name="A", order=0, inputs=[preserved])],
        )
        teams = [
            SimpleNamespace(id=11, tournament_id=99, avg_sr=3000, total_sr=15000),
            SimpleNamespace(id=12, tournament_id=99, avg_sr=2000, total_sr=10000),
        ]
        added: list = []
        session = SimpleNamespace(
            add=Mock(side_effect=added.append),
            delete=AsyncMock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        with (
            patch.object(service, "get_stage", AsyncMock(side_effect=[stage, stage])),
            patch.object(service.team_repo, "bulk_get", AsyncMock(return_value=teams)),
            patch.object(service, "_publish_structure_changed", AsyncMock()),
            patch.object(stage_service, "enqueue_tournament_recalculation", AsyncMock()),
        ):
            await service.seed_teams(session, 1, [11, 12])

        self.assertEqual([1, 3], sorted(inp.slot for inp in added))
        self.assertNotIn(2, [inp.slot for inp in added])


class CreateStageItemInputTests(IsolatedAsyncioTestCase):
    """Item 15: creating an input enforces what editing one enforces."""

    def _stage_item(self) -> SimpleNamespace:
        return SimpleNamespace(
            id=200,
            stage_id=2,
            stage=SimpleNamespace(tournament_id=99),
        )

    async def test_duplicate_slot_is_refused(self) -> None:
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=_input(slot=1, input_type=enums.StageItemInputType.EMPTY)),
            commit=AsyncMock(),
        )
        data = schemas.StageItemInputCreate(slot=1)

        with (
            patch.object(service.stage_item_repo, "get", AsyncMock(return_value=self._stage_item())),
            self.assertRaises(Exception) as ctx,
        ):
            await service.create_stage_item_input(session, 200, data)

        self.assertEqual(409, ctx.exception.status_code)
        self.assertIn("Slot 1", str(ctx.exception.detail))

    async def test_team_from_another_tournament_is_refused(self) -> None:
        session = SimpleNamespace(scalar=AsyncMock(return_value=None), commit=AsyncMock())
        data = schemas.StageItemInputCreate(
            slot=1,
            input_type=enums.StageItemInputType.FINAL,
            team_id=55,
        )

        with (
            patch.object(service.stage_item_repo, "get", AsyncMock(return_value=self._stage_item())),
            patch.object(
                service.team_repo,
                "get",
                AsyncMock(return_value=SimpleNamespace(id=55, tournament_id=12345)),
            ),
            self.assertRaises(Exception) as ctx,
        ):
            await service.create_stage_item_input(session, 200, data)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("does not belong to this tournament", str(ctx.exception.detail))

    async def test_team_already_seeded_in_the_stage_is_refused(self) -> None:
        # Slot free, team valid, but the team already holds another slot.
        session = SimpleNamespace(
            scalar=AsyncMock(side_effect=[None, _input(slot=4, input_type=enums.StageItemInputType.FINAL)]),
            commit=AsyncMock(),
        )
        data = schemas.StageItemInputCreate(
            slot=1,
            input_type=enums.StageItemInputType.FINAL,
            team_id=55,
        )

        with (
            patch.object(service.stage_item_repo, "get", AsyncMock(return_value=self._stage_item())),
            patch.object(
                service.team_repo,
                "get",
                AsyncMock(return_value=SimpleNamespace(id=55, tournament_id=99)),
            ),
            self.assertRaises(Exception) as ctx,
        ):
            await service.create_stage_item_input(session, 200, data)

        self.assertEqual(409, ctx.exception.status_code)


class StageItemInputSchemaTests(TestCase):
    """Item 15: the shapes the schema must not let through."""

    def test_slot_is_one_based(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.StageItemInputCreate(slot=0)

    def test_empty_input_cannot_carry_a_team(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.StageItemInputCreate(slot=1, input_type=enums.StageItemInputType.EMPTY, team_id=7)

    def test_final_input_requires_a_team(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.StageItemInputCreate(slot=1, input_type=enums.StageItemInputType.FINAL)


class StageRegulationSchemaTests(TestCase):
    """Item 16: the regulation is validated, not merely carried."""

    def test_non_numeric_scoring_is_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.StageUpdate(scoring={"win": "broken"})

    def test_a_misspelled_scoring_key_is_refused_instead_of_silently_dropped(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.StageUpdate(scoring={"win": 3, "drew": 1})

    def test_unknown_grand_final_type_is_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.StageUpdate(de_grand_final_type="best_of_three")

    def test_every_grand_final_type_the_editor_sends_is_accepted(self) -> None:
        for value in ("no_reset", "with_reset"):
            self.assertEqual(value, schemas.StageUpdate(de_grand_final_type=value).de_grand_final_type)

    def test_an_explicit_null_for_a_non_nullable_field_is_refused(self) -> None:
        # These carry a default only so that an omitted field is left alone --
        # sending null must not write a NULL into a NOT NULL column.
        for field in ("de_grand_final_type", "seed_ranking", "best_of", "scoring", "ffa_scoring"):
            with self.subTest(field=field), self.assertRaises(pydantic.ValidationError):
                schemas.StageUpdate(**{field: None})

    def test_a_round_cannot_be_played_as_best_of_zero(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.StageUpdate(best_of={"default": 3, "by_round": {2: 0}})


class UpdateStageTests(IsolatedAsyncioTestCase):
    """Item 16: structural edits and how the regulation reaches the columns."""

    def _stage(self, **overrides) -> SimpleNamespace:
        return SimpleNamespace(
            **stage_regulation(**overrides),
            id=1,
            tournament_id=99,
            stage_type=enums.StageType.SWISS,
        )

    async def _update(self, stage, data) -> None:
        session = SimpleNamespace(commit=AsyncMock())
        with (
            patch.object(service, "get_stage", AsyncMock(side_effect=[stage, stage])),
            patch.object(service.encounter_repo, "count", AsyncMock(return_value=0)),
            patch.object(service, "_publish_structure_changed", AsyncMock()),
        ):
            await service.update_stage(session, 1, data)

    async def test_format_change_with_existing_matches_is_refused(self) -> None:
        stage = self._stage()
        session = SimpleNamespace(commit=AsyncMock())
        data = schemas.StageUpdate(stage_type=enums.StageType.SINGLE_ELIMINATION)

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service.encounter_repo, "count", AsyncMock(return_value=7)),
            self.assertRaises(Exception) as ctx,
        ):
            await service.update_stage(session, 1, data)

        self.assertEqual(409, ctx.exception.status_code)
        self.assertIn("7", str(ctx.exception.detail))
        self.assertEqual(enums.StageType.SWISS, stage.stage_type)

    async def test_format_change_without_matches_is_allowed(self) -> None:
        stage = self._stage()

        await self._update(stage, schemas.StageUpdate(stage_type=enums.StageType.SINGLE_ELIMINATION))

        self.assertEqual(enums.StageType.SINGLE_ELIMINATION, stage.stage_type)

    async def test_scoring_lands_on_the_columns_the_engine_reads(self) -> None:
        stage = self._stage()

        await self._update(stage, schemas.StageUpdate(scoring={"win": 2, "draw": 1, "loss": 0}))

        self.assertEqual((2, 1, 0), (stage.win_points, stage.draw_points, stage.loss_points))

    async def test_an_untouched_field_is_left_alone(self) -> None:
        stage = self._stage(swiss_bye_points=2.0)

        await self._update(stage, schemas.StageUpdate(name="Group stage"))

        self.assertEqual("Group stage", stage.name)
        self.assertEqual(2.0, stage.swiss_bye_points)

    async def test_a_kept_round_is_edited_in_place_not_recreated(self) -> None:
        # ``(stage_id, round)`` is the primary key: replacing the row would
        # insert the new one before deleting the old and collide on it.
        kept = stage_service.models.StageRoundBestOf(round=1, best_of=2)
        stage = self._stage()
        stage.round_best_of = [kept, stage_service.models.StageRoundBestOf(round=2, best_of=5)]

        await self._update(stage, schemas.StageUpdate(best_of={"default": 3, "by_round": {1: 5}, "final": 7}))

        self.assertEqual([kept], stage.round_best_of)
        self.assertEqual(5, kept.best_of)
        self.assertEqual(3, stage.best_of_default)
        self.assertEqual(7, stage.best_of_final)
