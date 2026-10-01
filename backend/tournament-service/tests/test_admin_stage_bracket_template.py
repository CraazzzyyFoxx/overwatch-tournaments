"""A stage's custom bracket template: storage, the guards around editing it, and
every generation path reading it back.

The template is the drawing the admin made; once it is stored it REPLACES the
format's generator everywhere a bracket shape is produced -- planned rounds, the
preview and the real generation -- so the whole point is that those three agree
with it and with each other. Editing it is refused once matches exist (the shape
they were built from cannot change under them), and a template whose seed counts
no longer match the stage's refuses to generate rather than silently dropping or
inventing teams.

Does not touch a real database: ``get_stage``, ``_load_team_names`` and the
encounter count are patched directly (the pattern of
``test_admin_stage_bracket_preview.py``).
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

stage_service = importlib.import_module("src.services.admin.stage")
enums = importlib.import_module("shared.core.enums")
errors = importlib.import_module("shared.core.errors")

from shared.services.bracket.template import BracketTemplate  # noqa: E402
from tests._stage_regulation import stage_regulation  # noqa: E402
from tests.test_bracket_template import _sketch  # noqa: E402

service = stage_service.stage_service
schemas = stage_service.schemas
HTTPException = errors.BaseAPIException


def _input(team_id: int | None, slot: int) -> SimpleNamespace:
    return SimpleNamespace(team_id=team_id, slot=slot)


def _item(item_id: int, inputs: list[SimpleNamespace], *, order: int = 0, item_type=None) -> SimpleNamespace:
    return SimpleNamespace(id=item_id, order=order, inputs=inputs, type=item_type)


def _stage(*, upper: int = 4, lower: int = 4, template: dict | None = None, **overrides) -> SimpleNamespace:
    """A double elimination stage with ``upper``/``lower`` teams wired in."""
    items = [
        _item(
            1,
            [_input(team_id, team_id) for team_id in range(1, upper + 1)],
            order=0,
            item_type=enums.StageItemType.BRACKET_UPPER,
        ),
        _item(
            2,
            [_input(team_id, team_id - upper) for team_id in range(upper + 1, upper + lower + 1)],
            order=1,
            item_type=enums.StageItemType.BRACKET_LOWER,
        ),
    ]
    fields = {
        "id": 5,
        "tournament_id": 1,
        "stage_type": enums.StageType.DOUBLE_ELIMINATION,
        "items": items,
        "bracket_template": template,
    }
    fields.update(overrides)
    return SimpleNamespace(**{**stage_regulation(), **fields})


def _rows_result(rows: list[tuple]):
    result = Mock()
    result.all.return_value = rows
    return result


def _session() -> SimpleNamespace:
    """Enough session for the stage row lock these paths take."""
    return SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))


class SetBracketTemplateTests(IsolatedAsyncioTestCase):
    async def test_refuses_to_edit_a_bracket_that_already_has_matches(self) -> None:
        stage = _stage()
        template = BracketTemplate.model_validate(_sketch())

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service.encounter_repo, "count", AsyncMock(return_value=10)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await service.set_bracket_template(_session(), 5, template)

        self.assertEqual(409, ctx.exception.status_code)
        self.assertEqual(
            "This stage already has generated matches. Delete them first to edit the bracket.",
            ctx.exception.detail,
        )
        self.assertIsNone(stage.bracket_template)

    async def test_an_invalid_template_comes_back_as_422_problems(self) -> None:
        raw = _sketch()
        raw["matches"][0]["round"] = 0
        stage = _stage()

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service.encounter_repo, "count", AsyncMock(return_value=0)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await service.set_bracket_template(_session(), 5, BracketTemplate.model_validate(raw))

        self.assertEqual(422, ctx.exception.status_code)
        self.assertEqual("invalid_bracket_template", ctx.exception.detail["code"])
        self.assertEqual("bracket template has 1 problem(s)", ctx.exception.detail["message"])
        self.assertEqual(
            [
                {
                    "match_id": 0,
                    "slot": None,
                    "code": "zero_round",
                    "message": "Round 0 does not exist: upper rounds are positive, lower rounds negative",
                }
            ],
            ctx.exception.detail["problems"],
        )
        self.assertIsNone(stage.bracket_template)

    async def test_a_valid_template_is_stored_and_read_back_as_custom(self) -> None:
        stage = _stage()
        template = BracketTemplate.model_validate(_sketch())

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service.encounter_repo, "count", AsyncMock(return_value=0)),
            patch.object(service, "_finish_structure_write", AsyncMock()) as finish,
        ):
            read = await service.set_bracket_template(_session(), 5, template)

        self.assertEqual(template.model_dump(mode="json"), stage.bracket_template)
        self.assertTrue(read["custom"])
        self.assertEqual(template.model_dump(mode="json"), read["template"])
        self.assertEqual({"upper": 4, "lower": 4}, read["seeds"])
        finish.assert_awaited_once()

    async def test_only_bracket_stages_have_a_layout(self) -> None:
        stage = _stage(stage_type=enums.StageType.SWISS)

        with patch.object(service, "get_stage", AsyncMock(return_value=stage)):
            with self.assertRaises(HTTPException) as ctx:
                await service.get_bracket_template(SimpleNamespace(), 5)

        self.assertEqual(400, ctx.exception.status_code)


class ClearBracketTemplateTests(IsolatedAsyncioTestCase):
    async def test_clearing_falls_back_to_the_generated_bracket(self) -> None:
        stage = _stage(template=BracketTemplate.model_validate(_sketch()).model_dump(mode="json"))

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service.encounter_repo, "count", AsyncMock(return_value=0)),
            patch.object(service, "_finish_structure_write", AsyncMock()),
        ):
            read = await service.clear_bracket_template(_session(), 5)

        self.assertIsNone(stage.bracket_template)
        self.assertFalse(read["custom"])
        # Still a drawable template -- the one the format generates for 4+4.
        self.assertEqual(4, read["template"]["upper_seeds"])
        self.assertEqual(4, read["template"]["lower_seeds"])
        self.assertEqual(10, len(read["template"]["matches"]))


class PlannedRoundsFromTemplateTests(IsolatedAsyncioTestCase):
    async def test_the_stored_template_decides_the_rounds(self) -> None:
        # No seeds wired and nothing upstream to project from: the format's own
        # generator has nothing to offer, and the stored drawing still does.
        stage = _stage(template=BracketTemplate.model_validate(_sketch()).model_dump(mode="json"), items=[])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service, "_preceding_group_stage", AsyncMock(return_value=None)),
        ):
            rounds = await service.get_planned_rounds(session, 5)

        self.assertEqual([-4, -3, -2, -1, 1, 2, 3], rounds)


class BracketPreviewFromTemplateTests(IsolatedAsyncioTestCase):
    async def test_the_preview_draws_the_stored_template(self) -> None:
        stage = _stage(template=BracketTemplate.model_validate(_sketch()).model_dump(mode="json"))
        names = {team_id: f"Team {team_id}" for team_id in range(1, 9)}

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service, "_load_team_names", AsyncMock(return_value=names)),
        ):
            preview = await service.get_bracket_preview(SimpleNamespace(), 5)

        matches = preview["matches"]
        self.assertEqual(10, len(matches))
        cross_drop = next(match for match in matches if match["local_id"] == 6)
        self.assertEqual(
            [
                {"local_id": 4, "role": "winner", "slot": "home"},
                {"local_id": 2, "role": "loser", "slot": "away"},
            ],
            cross_drop["sources"],
        )

    async def test_seeds_that_do_not_fit_the_template_draw_it_all_tbd(self) -> None:
        stage = _stage(lower=2, template=BracketTemplate.model_validate(_sketch()).model_dump(mode="json"))

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service, "_load_team_names", AsyncMock(return_value={})),
        ):
            preview = await service.get_bracket_preview(SimpleNamespace(), 5)

        self.assertEqual(10, len(preview["matches"]))
        for match in preview["matches"]:
            self.assertIsNone(match["home_team_id"])
            self.assertIsNone(match["away_team_id"])


class GenerateThroughTemplateTests(IsolatedAsyncioTestCase):
    async def test_generation_refuses_seeds_the_template_does_not_fit(self) -> None:
        stage = _stage(lower=6, template=BracketTemplate.model_validate(_sketch()).model_dump(mode="json"))

        with patch.object(service, "_load_team_names", AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as ctx:
                await service._generate_bracket_encounters(_session(), stage, {})

        self.assertEqual(409, ctx.exception.status_code)
        self.assertEqual(
            "Custom bracket expects 4+4 seeds, stage has 4+6. Edit or reset the custom bracket.",
            ctx.exception.detail,
        )

    async def test_generation_persists_exactly_the_templates_pairings_and_edges(self) -> None:
        # Not the pairing the generator draws for 4 upper seeds (U1vU4, U2vU3):
        # the drawing is what gets built, seed for seed.
        raw = _sketch()
        raw["matches"][0]["away"] = {"seed": "U3"}
        raw["matches"][1]["away"] = {"seed": "U4"}
        stage = _stage(template=BracketTemplate.model_validate(raw).model_dump(mode="json"))
        persisted: dict = {}

        async def _capture(session, stage_, skeleton, item_id, *, team_names_by_id, lb_stage_item_id=None):
            persisted["skeleton"] = skeleton
            return []

        with (
            patch.object(service, "_load_team_names", AsyncMock(return_value={})),
            patch.object(service, "_create_encounters_from_skeleton", AsyncMock(side_effect=_capture)),
        ):
            await service._generate_bracket_encounters(_session(), stage, {})

        skeleton = persisted["skeleton"]
        self.assertEqual(
            [(1, 3), (2, 4), (None, None), (5, 8), (6, 7)],
            [(p.home_team_id, p.away_team_id) for p in skeleton.pairings[:5]],
        )
        self.assertEqual([1, 1, 2, -1, -1, -2, -2, -3, -4, 3], [p.round_number for p in skeleton.pairings])
        self.assertIn(
            ("loser", 1, 5, "away"),
            [(e.role, e.source_local_id, e.target_local_id, e.target_slot) for e in skeleton.advancement_edges],
        )


class UpdateStageWithTemplateTests(IsolatedAsyncioTestCase):
    async def test_the_format_cannot_change_under_a_custom_bracket(self) -> None:
        stage = _stage(template=BracketTemplate.model_validate(_sketch()).model_dump(mode="json"))

        with patch.object(service, "get_stage", AsyncMock(return_value=stage)):
            with self.assertRaises(HTTPException) as ctx:
                await service.update_stage(
                    SimpleNamespace(),
                    5,
                    schemas.StageUpdate(stage_type=enums.StageType.SINGLE_ELIMINATION),
                )

        self.assertEqual(409, ctx.exception.status_code)
        self.assertEqual("Reset the custom bracket before changing the format", ctx.exception.detail)
