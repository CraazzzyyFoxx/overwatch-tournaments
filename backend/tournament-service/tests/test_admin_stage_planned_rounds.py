"""`get_planned_rounds` must offer the round numbers a bracket stage actually
has, or will have -- never the linear `1..max_rounds` guess the round picker
used before this, which double elimination's negative lower-bracket rounds
(and single elimination's team-count-dependent round count) can silently
disagree with.

Does not touch a real database: `get_stage` is patched directly (the
established pattern in this test suite, see `test_admin_stage_merge.py`), and
`session.execute` is mocked only for the distinct-encounter-rounds query
`get_planned_rounds` runs itself.
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


def _rows_result(rows: list[tuple]):
    result = Mock()
    result.all.return_value = rows
    return result


def _input(team_id: int | None, slot: int) -> SimpleNamespace:
    return SimpleNamespace(team_id=team_id, slot=slot)


def _item(
    item_id: int,
    inputs: list[SimpleNamespace],
    order: int = 0,
    item_type=enums.StageItemType.SINGLE_BRACKET,
) -> SimpleNamespace:
    return SimpleNamespace(id=item_id, order=order, inputs=inputs, type=item_type)


def _stage(stage_type, items: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(id=5, stage_type=stage_type, items=items, bracket_template=None)


class GetPlannedRoundsTests(IsolatedAsyncioTestCase):
    async def test_returns_existing_rounds_once_the_bracket_is_built(self) -> None:
        stage = _stage(enums.StageType.DOUBLE_ELIMINATION, [])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([(1,), (-2,), (2,)])))

        with patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)

        # Ground truth once encounters exist: sorted, never re-predicted.
        self.assertEqual([-2, 1, 2], rounds)

    async def test_predicts_double_elimination_rounds_from_planned_team_inputs(self) -> None:
        inputs = [_input(team_id, team_id) for team_id in range(1, 9)]
        stage = _stage(enums.StageType.DOUBLE_ELIMINATION, [_item(1, inputs)])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)

        self.assertEqual([-4, -3, -2, -1, 1, 2, 3, 4], rounds)

    async def test_includes_still_tentative_inputs_in_the_predicted_team_count(self) -> None:
        # `_collect_item_team_ids` only checks `team_id is not None`; a
        # TENTATIVE input (not yet resolved to FINAL) still counts.
        inputs = [
            _input(1, 1),
            _input(2, 2),
            _input(None, 3),
            _input(3, 4),
            _input(4, 5),
        ]
        stage = _stage(enums.StageType.SINGLE_ELIMINATION, [_item(1, inputs)])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)

        self.assertEqual([1, 2], rounds)  # 4 known teams -> 2 rounds

    async def test_predicts_nothing_for_a_non_bracket_stage_type(self) -> None:
        stage = _stage(enums.StageType.SWISS, [_item(1, [_input(1, 1), _input(2, 2)])])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)

        self.assertEqual([], rounds)

    async def test_predicts_nothing_with_fewer_than_two_teams_wired_in(self) -> None:
        stage = _stage(enums.StageType.SINGLE_ELIMINATION, [_item(1, [_input(1, 1)])])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_preceding_group_stage", AsyncMock(return_value=None)),
        ):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)

        self.assertEqual([], rounds)

    async def test_projects_rounds_from_the_preceding_group_stage(self) -> None:
        # An unseeded double elimination playoff: no teams are wired yet, so the
        # rounds are projected from the group stage that will seed it --
        # `advance_count` (4) per group × 2 groups = 8 teams, of which 2 per group
        # start upper: a 4-team upper bracket and 4 lower-bracket seeds. Matches
        # the rounds `generate_encounters` will build once the groups finish.
        stage = _stage(enums.StageType.DOUBLE_ELIMINATION, [_item(1, [])])
        source = SimpleNamespace(
            id=4,
            advance_count=4,
            advance_upper_count=2,
            items=[_item(10, []), _item(11, [])],
        )
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
        ):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)

        self.assertEqual([-4, -3, -2, -1, 1, 2, 3], rounds)

    async def test_projects_an_odd_advance_count_split_per_group_not_per_bracket(self) -> None:
        # 3 advance from each of 2 groups into a playoff with a separate Lower
        # bracket item. The wiring splits EACH group's 3 (2 up, 1 down), so the
        # upper bracket gets 4 and the lower 2 -- not the 3/3 a split of the
        # 6-team total would give, which is a differently shaped bracket.
        stage = _stage(
            enums.StageType.DOUBLE_ELIMINATION,
            [
                _item(1, [], order=0, item_type=enums.StageItemType.BRACKET_UPPER),
                _item(2, [], order=1, item_type=enums.StageItemType.BRACKET_LOWER),
            ],
        )
        source = SimpleNamespace(id=4, advance_count=3, advance_upper_count=2, items=[_item(10, []), _item(11, [])])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
        ):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)
            projected = await stage_service.stage_service._projected_bracket_seed_counts(session, stage)

        self.assertEqual((4, 2), projected)
        self.assertEqual([-4, -3, -2, -1, 1, 2, 3], rounds)

    async def test_single_elimination_target_ignores_the_sources_upper_split(self) -> None:
        # Only a double elimination has a lower bracket: a single elimination
        # playoff takes all 2 × 6 advancing teams as upper seeds, even though the
        # source splits 2 of each group's 6 into an upper band.
        stage = _stage(enums.StageType.SINGLE_ELIMINATION, [_item(1, [])])
        source = SimpleNamespace(id=4, advance_count=6, advance_upper_count=2, items=[_item(10, []), _item(11, [])])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
        ):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)
            projected = await stage_service.stage_service._projected_bracket_seed_counts(session, stage)

        self.assertEqual((12, 0), projected)
        self.assertEqual([1, 2, 3, 4], rounds)
