"""An operator-triggered recompute on an unverified workspace must not run inline.

``run_evaluation`` is the only place the trust tier is checked. A ``manual`` or
``rule_version_bump`` run for an ``unverified`` workspace gets a ``queued``
``EvaluationRun`` row plus one message on ``achievement_evaluate.deferred`` — and
evaluates nothing. Everything else (``parse_complete`` at any tier, ``verified``
and ``trusted`` at any trigger) stays inline, because deferring those would
either stall ingestion or punish the workspaces someone already vouched for.

These are fakes, not a database: the assertions are about which branch runs and
what it publishes, and the surrounding suite (``test_scrim_achievement_isolation``)
already covers the evaluation body against real SQL.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

achievement = importlib.import_module("shared.models.achievements.achievement")
messaging_config = importlib.import_module("shared.messaging.config")
runner = importlib.import_module("src.services.achievement.engine.runner")

WORKSPACE_ID = 7


class _Savepoint:
    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


class _FakeSession:
    """Just enough session for the two branches: a workspace lookup and commits."""

    def __init__(self, workspace: object | None) -> None:
        self._workspace = workspace
        self.commits = 0
        self.added: list[object] = []

    async def get(self, _model, _pk):  # noqa: ANN001, ANN202
        return self._workspace

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    def begin_nested(self) -> _Savepoint:
        return _Savepoint()


class _FakeRunsRepo:
    def __init__(self) -> None:
        self.created: list[achievement.EvaluationRun] = []

    async def create(self, _session, run):  # noqa: ANN001, ANN202
        self.created.append(run)
        return run

    async def get(self, _session, run_id):  # noqa: ANN001, ANN202
        return next((run for run in self.created if run.id == run_id), None)


def _rule() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        slug="captain",
        enabled=True,
        condition_tree={"type": "is_captain"},
        depends_on=["tournament.encounter"],
        min_tournament_id=None,
        grain="user_tournament",
    )


class _RunnerTestCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.runs_repo = _FakeRunsRepo()
        self.service = runner.AchievementEvaluationRunnerService(runs_repo=self.runs_repo)
        self.published: list[tuple[dict, object]] = []
        self.evaluated: list[str] = []
        self.diffed: list[str] = []

        async def _publish(_broker, message, queue, **_kwargs):  # noqa: ANN001, ANN003, ANN202
            self.published.append((message, queue))

        async def _get_rules(_session, _workspace_id, _rule_ids):  # noqa: ANN001, ANN202
            return [_rule()]

        async def _evaluate(_session, _condition, _context):  # noqa: ANN001, ANN202
            self.evaluated.append("evaluate")
            return set()

        async def _diff_and_apply(_session, rule, _results, _run_id, **_kwargs):  # noqa: ANN001, ANN003, ANN202
            self.diffed.append(rule.slug)
            return SimpleNamespace(to_insert=[], to_delete=[])

        async def _resolve_grid(_session, _workspace_id, _tournament):  # noqa: ANN001, ANN202
            return None

        for target, replacement in (
            ("publish_message", _publish),
            ("_get_rules", _get_rules),
            ("evaluate", _evaluate),
            ("diff_and_apply", _diff_and_apply),
            ("_resolve_grid", _resolve_grid),
            ("require_broker", lambda *_a, **_kw: object()),
        ):
            patcher = patch.object(runner, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _session(self, verification_status: str) -> _FakeSession:
        return _FakeSession(SimpleNamespace(id=WORKSPACE_ID, verification_status=verification_status))

    async def _run(self, session: _FakeSession, trigger, **kwargs):  # noqa: ANN001, ANN003, ANN202
        return await self.service.run_evaluation(session, WORKSPACE_ID, trigger, **kwargs)

    def _assert_deferred(self, run) -> None:  # noqa: ANN001
        self.assertEqual(achievement.EvaluationRunStatus.queued, run.status)
        self.assertEqual([], self.evaluated)
        self.assertEqual([], self.diffed)
        self.assertEqual(1, len(self.published))
        message, queue = self.published[0]
        self.assertIs(messaging_config.ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE, queue)
        self.assertEqual(run.id, message["run_id"])
        self.assertEqual(WORKSPACE_ID, message["workspace_id"])

    def _assert_inline(self, run) -> None:  # noqa: ANN001
        self.assertEqual(achievement.EvaluationRunStatus.done, run.status)
        self.assertEqual(["evaluate"], self.evaluated)
        self.assertEqual(["captain"], self.diffed)
        self.assertEqual([], self.published)


class DeferralTests(_RunnerTestCase):
    async def test_manual_run_on_an_unverified_workspace_is_queued(self) -> None:
        run = await self._run(self._session("unverified"), achievement.EvaluationRunTrigger.manual, rule_ids=[1])

        self._assert_deferred(run)
        self.assertEqual([1], self.published[0][0]["rule_ids"])

    async def test_rule_version_bump_on_an_unverified_workspace_is_queued(self) -> None:
        run = await self._run(self._session("unverified"), achievement.EvaluationRunTrigger.rule_version_bump)

        self._assert_deferred(run)

    async def test_parse_complete_stays_inline_on_an_unverified_workspace(self) -> None:
        """Ingestion must not depend on anyone verifying the workspace."""
        run = await self._run(self._session("unverified"), achievement.EvaluationRunTrigger.parse_complete)

        self._assert_inline(run)

    async def test_manual_run_on_a_verified_workspace_stays_inline(self) -> None:
        run = await self._run(self._session("verified"), achievement.EvaluationRunTrigger.manual)

        self._assert_inline(run)

    async def test_manual_run_on_a_trusted_workspace_stays_inline(self) -> None:
        run = await self._run(self._session("trusted"), achievement.EvaluationRunTrigger.manual)

        self._assert_inline(run)


class ResumeTests(_RunnerTestCase):
    """The deferred consumer finishes the queued row instead of opening a new one."""

    async def test_resume_runs_the_same_row_without_re_gating(self) -> None:
        session = self._session("unverified")
        queued = await self._run(session, achievement.EvaluationRunTrigger.manual, rule_ids=[1])
        event = runner.AchievementEvaluateEvent.model_validate(self.published[0][0])

        resumed = await self.service.resume_queued_run(session, event)

        self.assertIs(queued, resumed)
        self.assertEqual(achievement.EvaluationRunStatus.done, resumed.status)
        self.assertEqual(["evaluate"], self.evaluated)
        # Still one publish (the original deferral) and one run row: the resume
        # path must not re-enter the tier gate and re-queue itself.
        self.assertEqual(1, len(self.published))
        self.assertEqual(1, len(self.runs_repo.created))

    async def test_resume_skips_a_run_that_already_finished(self) -> None:
        session = self._session("unverified")
        queued = await self._run(session, achievement.EvaluationRunTrigger.manual)
        queued.status = achievement.EvaluationRunStatus.done
        event = runner.AchievementEvaluateEvent.model_validate(self.published[0][0])

        await self.service.resume_queued_run(session, event)

        self.assertEqual([], self.evaluated)

    async def test_resume_drops_a_message_for_a_missing_run(self) -> None:
        event = runner.AchievementEvaluateEvent(
            workspace_id=WORKSPACE_ID,
            changed_tables=[],
            run_id="00000000-0000-0000-0000-0000000000ff",
        )

        self.assertIsNone(await self.service.resume_queued_run(self._session("unverified"), event))
