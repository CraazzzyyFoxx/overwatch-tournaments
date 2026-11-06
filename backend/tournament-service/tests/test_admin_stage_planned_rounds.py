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
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


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


def _result_rows(upper: int, lower: int) -> list[SimpleNamespace]:
    """Flow input rows: ``upper`` plain ones and ``lower`` flagged as lower-bracket starters."""
    return [SimpleNamespace(breakdown=None)] * upper + [SimpleNamespace(breakdown={"bracket": "lower"})] * lower


def _input_rows(rows: list[SimpleNamespace]) -> AsyncMock:
    """What `_stage_input_rows` answers: the stage's node (unused here) and its input rows."""
    return AsyncMock(return_value=(None, rows))


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

    async def test_skips_inputs_without_a_team_in_the_predicted_team_count(self) -> None:
        # `_collect_item_team_ids` only checks `team_id is not None`; an input
        # without a team does not count.
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
            patch.object(stage_service.stage_service, "_stage_input_rows", _input_rows([])),
        ):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)

        self.assertEqual([], rounds)

    async def test_projects_rounds_from_the_flow_input_rows(self) -> None:
        # An unseeded double elimination playoff: no teams are seated yet, so the
        # rounds are projected from the result rows wired into it -- 8 rows, 4 of
        # them lower starters: a 4-team upper bracket and 4 lower-bracket seeds.
        # Matches the rounds `generate_encounters` will build once the groups finish.
        stage = _stage(enums.StageType.DOUBLE_ELIMINATION, [_item(1, [])])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_stage_input_rows", _input_rows(_result_rows(4, 4))),
        ):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)

        self.assertEqual([-4, -3, -2, -1, 1, 2, 3], rounds)

    async def test_projects_an_uneven_split_from_the_lower_flags(self) -> None:
        # 6 rows, 2 flagged lower, into a playoff with a separate Lower bracket
        # item: the upper bracket gets 4 and the lower 2 -- not the 3/3 a split
        # of the total would give, which is a differently shaped bracket.
        stage = _stage(
            enums.StageType.DOUBLE_ELIMINATION,
            [
                _item(1, [], order=0, item_type=enums.StageItemType.BRACKET_UPPER),
                _item(2, [], order=1, item_type=enums.StageItemType.BRACKET_LOWER),
            ],
        )
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_stage_input_rows", _input_rows(_result_rows(4, 2))),
        ):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)
            projected = await stage_service.stage_service._projected_bracket_seed_counts(session, stage)

        self.assertEqual((4, 2), projected)
        self.assertEqual([-4, -3, -2, -1, 1, 2, 3], rounds)

    async def test_single_elimination_target_ignores_the_lower_flags(self) -> None:
        # Only a double elimination has a lower bracket: a single elimination
        # playoff takes all 12 rows as upper seeds, flagged lower or not.
        stage = _stage(enums.StageType.SINGLE_ELIMINATION, [_item(1, [])])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])))

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_stage_input_rows", _input_rows(_result_rows(2, 10))),
        ):
            rounds = await stage_service.stage_service.get_planned_rounds(session, 5)
            projected = await stage_service.stage_service._projected_bracket_seed_counts(session, stage)

        self.assertEqual((12, 0), projected)
        self.assertEqual([1, 2, 3, 4], rounds)
