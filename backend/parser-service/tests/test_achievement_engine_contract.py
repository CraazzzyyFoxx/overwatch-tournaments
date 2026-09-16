"""Regression for achievement evaluation contracts: grain, slice, NOT, run status.

Uses the SQLite fixture from ``test_scrim_achievement_isolation``. Differ writes
are patched in runner tests so the PostgreSQL-only ON CONFLICT insert is not
required to assert persist-slice behaviour.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT), str(Path(__file__).resolve().parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import test_scrim_achievement_isolation as _scrim  # noqa: E402
from test_scrim_achievement_isolation import (  # noqa: E402
    IS_CAPTAIN_RULE,
    LATER_TOURNAMENT_ID,
    REAL_AWAY_USER,
    REAL_HOME_USER,
    REAL_TOURNAMENT_ID,
    WORKSPACE_ID,
    _EngineTestCase,
)

from shared.models.achievements.achievement import (  # noqa: E402
    EvaluationRunStatus,
    EvaluationRunTrigger,
)
from shared.services.division_grid.normalization import DivisionGridNormalizationError  # noqa: E402
from src.services.achievement.engine.differ import DiffResult, EvaluationSlice  # noqa: E402

evaluator = _scrim.evaluator
runner = _scrim.runner

NON_CAPTAIN_USER = 104
SUBSTITUTE_USER = 105
TOURNAMENT_COUNT_RULE = {"type": "tournament_count", "params": {"op": ">=", "value": 1}}
BAD_STANDING_RULE = {"type": "standing_record", "params": {"field": "not_a_field", "op": "==", "value": 0}}
DIV_SPAN_RULE = {"type": "div_span", "params": {"op": ">=", "value": 1}}


class _CaptureDiffer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, set[tuple[int, ...]], EvaluationSlice | None]] = []

    async def __call__(self, session, rule, new_results, run_id, evaluation_slice=None):  # noqa: ANN001
        self.calls.append((rule.slug, set(new_results), evaluation_slice))
        return DiffResult(to_insert=[{"key": key} for key in new_results], to_delete=[])


class EvaluatorGrainTests(_EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db.tournament(REAL_TOURNAMENT_ID, name="Real", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        self.real = self.db.rostered_tournament(REAL_TOURNAMENT_ID)
        self.db.player(
            REAL_TOURNAMENT_ID,
            self.real["home"],
            self.db.member(NON_CAPTAIN_USER),
            name="bench",
        )
        self.db.player(
            REAL_TOURNAMENT_ID,
            self.real["home"],
            self.db.member(SUBSTITUTE_USER),
            name="sub",
            is_substitution=True,
        )
        self.db.session.commit()

    async def test_not_is_captain_complements_tournament_keys(self) -> None:
        result = await evaluator.evaluate(
            self.db.shim,
            {"NOT": IS_CAPTAIN_RULE},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertTrue(result)
        self.assertTrue(all(len(key) == 2 for key in result))
        self.assertIn((NON_CAPTAIN_USER, REAL_TOURNAMENT_ID), result)
        self.assertNotIn((REAL_HOME_USER, REAL_TOURNAMENT_ID), result)
        self.assertNotIn((REAL_AWAY_USER, REAL_TOURNAMENT_ID), result)
        # Substitutes are outside the roster universe, like ``match_win``.
        self.assertNotIn((SUBSTITUTE_USER, REAL_TOURNAMENT_ID), result)

    async def test_mixed_and_raises_when_both_sides_match(self) -> None:
        with self.assertRaises(evaluator.GrainMismatchError):
            await evaluator.evaluate(
                self.db.shim,
                {"AND": [IS_CAPTAIN_RULE, {"type": "match_win"}]},
                await self.context(REAL_TOURNAMENT_ID),
            )


class RunnerSliceAndStatusTests(_EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db.tournament(REAL_TOURNAMENT_ID, name="Real", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.tournament(LATER_TOURNAMENT_ID, name="Later", is_hidden=False, start=datetime(2026, 2, 1, tzinfo=UTC))
        self.db.rostered_tournament(REAL_TOURNAMENT_ID)
        self.db.rostered_tournament(LATER_TOURNAMENT_ID)
        self.db.session.commit()

    async def test_user_grain_rule_is_not_sliced_on_tournament_run(self) -> None:
        self.db.rule(
            1,
            "played-once",
            TOURNAMENT_COUNT_RULE,
            [],
            grain="user",
            scope="global",
            category="overall",
        )
        self.db.rule(2, "captain", IS_CAPTAIN_RULE, [])
        self.db.session.commit()
        capture = _CaptureDiffer()
        with patch.object(runner, "diff_and_apply", capture):
            run = await runner.run_evaluation(
                self.db.shim,
                WORKSPACE_ID,
                EvaluationRunTrigger.parse_complete,
                tournament_id=REAL_TOURNAMENT_ID,
            )

        self.assertEqual(EvaluationRunStatus.done, run.status)
        by_slug = {slug: (results, slice_) for slug, results, slice_ in capture.calls}
        global_results, global_slice = by_slug["played-once"]
        self.assertIsNone(global_slice)
        self.assertIn((REAL_HOME_USER,), global_results)
        self.assertIn((REAL_AWAY_USER,), global_results)
        _, captain_slice = by_slug["captain"]
        self.assertIsNotNone(captain_slice)
        self.assertEqual(REAL_TOURNAMENT_ID, captain_slice.tournament_id)

    async def test_failed_rule_marks_run_partial(self) -> None:
        self.db.rule(1, "captain", IS_CAPTAIN_RULE, [])
        self.db.rule(2, "bad-standing", BAD_STANDING_RULE, [])
        self.db.session.commit()
        capture = _CaptureDiffer()
        with patch.object(runner, "diff_and_apply", capture):
            run = await runner.run_evaluation(
                self.db.shim,
                WORKSPACE_ID,
                EvaluationRunTrigger.parse_complete,
                tournament_id=REAL_TOURNAMENT_ID,
            )

        self.assertEqual(EvaluationRunStatus.partial, run.status)
        self.assertEqual(1, run.rules_evaluated)
        self.assertIsNotNone(run.error_message)
        self.assertIn("bad-standing", run.error_message)
        self.assertEqual(["captain"], [slug for slug, _results, _slice in capture.calls])

    async def test_min_tournament_id_does_not_short_circuit_a_user_grain_rule(self) -> None:
        # An older tournament's parse must not empty a workspace-wide rule: the
        # trigger tournament is irrelevant to ``user``-grain results, and with no
        # persist slice an empty diff would delete every stored row.
        self.db.rule(
            1,
            "played-once",
            TOURNAMENT_COUNT_RULE,
            [],
            grain="user",
            scope="global",
            category="overall",
            min_tournament_id=LATER_TOURNAMENT_ID,
        )
        self.db.session.commit()
        capture = _CaptureDiffer()
        with patch.object(runner, "diff_and_apply", capture):
            run = await runner.run_evaluation(
                self.db.shim,
                WORKSPACE_ID,
                EvaluationRunTrigger.parse_complete,
                tournament_id=REAL_TOURNAMENT_ID,
            )

        self.assertEqual(EvaluationRunStatus.done, run.status)
        [(_slug, results, slice_)] = capture.calls
        self.assertIsNone(slice_)
        self.assertEqual({(REAL_HOME_USER,), (REAL_AWAY_USER,)}, results)

    async def test_user_grain_division_rule_gets_normalizer_on_tournament_run(self) -> None:
        self.db.rule(1, "climb", DIV_SPAN_RULE, [], grain="user", scope="global", category="division")
        self.db.session.commit()
        sentinel = object()
        seen: dict[str, object] = {}

        async def build_normalizer(session, workspace_id):  # noqa: ANN001
            seen["workspace_id"] = workspace_id
            return sentinel

        async def spy_evaluate(session, tree, context):  # noqa: ANN001
            seen["context"] = context
            return set()

        with (
            patch.object(runner, "diff_and_apply", _CaptureDiffer()),
            patch.object(runner, "build_workspace_division_grid_normalizer", build_normalizer),
            patch.object(runner, "evaluate", spy_evaluate),
        ):
            run = await runner.run_evaluation(
                self.db.shim,
                WORKSPACE_ID,
                EvaluationRunTrigger.parse_complete,
                tournament_id=REAL_TOURNAMENT_ID,
            )

        self.assertEqual(EvaluationRunStatus.done, run.status)
        self.assertEqual(WORKSPACE_ID, seen["workspace_id"])
        context = seen["context"]
        self.assertIsNone(context.tournament)
        self.assertIs(sentinel, context.normalizer)

    async def test_missing_grid_mapping_fails_only_the_division_rules(self) -> None:
        # An incomplete division-grid mapping must not abort the run: the other
        # rules are evaluated, the division rules are reported once each, and the
        # normalizer is attempted once, not per rule.
        self.db.rule(1, "captain", IS_CAPTAIN_RULE, [])
        self.db.rule(2, "climb", DIV_SPAN_RULE, [], grain="user", scope="global", category="division")
        self.db.rule(3, "climb-more", DIV_SPAN_RULE, [], grain="user", scope="global", category="division")
        self.db.session.commit()
        attempts = 0

        async def build_normalizer(session, workspace_id):  # noqa: ANN001
            nonlocal attempts
            attempts += 1
            raise DivisionGridNormalizationError("Missing division grid mappings to normalized base version 19: [20]")

        capture = _CaptureDiffer()
        with (
            patch.object(runner, "diff_and_apply", capture),
            patch.object(runner, "build_workspace_division_grid_normalizer", build_normalizer),
        ):
            run = await runner.run_evaluation(
                self.db.shim,
                WORKSPACE_ID,
                EvaluationRunTrigger.parse_complete,
                tournament_id=REAL_TOURNAMENT_ID,
            )

        self.assertEqual(EvaluationRunStatus.partial, run.status)
        self.assertEqual(1, run.rules_evaluated)
        self.assertEqual(1, attempts)
        self.assertEqual(["captain"], [slug for slug, _results, _slice in capture.calls])
        self.assertIn("climb: Missing division grid mappings", run.error_message)
        self.assertIn("climb-more: Missing division grid mappings", run.error_message)
