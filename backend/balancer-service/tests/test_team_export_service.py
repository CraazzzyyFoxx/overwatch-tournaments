"""Transaction-control tests for ``TeamMaterializationService``.

Unlike most of ``shared/tests``, these use a recording fake session rather than a
real engine: the claims under test are *ordering and transaction control* — did
the rollback happen before the failure stamp, was commit called exactly once —
which is precisely what a fake can falsify and what SQL execution cannot show.

The regression that motivates the failure test is real. ``export_balance`` deletes
the previous ``Standing``/``Player``/``Team`` rows with no intervening commit, and
its old ``except`` branch stamped ``export_status='failed'`` and committed — which
flushed those pending DELETEs, leaving a tournament with its teams gone and no
replacements. The orchestrator must roll back *first*, then stamp in a fresh
transaction.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.core.errors import ApiHTTPException  # noqa: E402
from src.services.team_export import service as service_module  # noqa: E402
from src.services.team_export.materialization import (  # noqa: E402
    MaterializationMember,
    MaterializationResult,
    MaterializationTeam,
)
from src.services.team_export.service import ExportPlan, TeamMaterializationService  # noqa: E402


class _FakeSession:
    """Records the ops the orchestrator performs, in order."""

    def __init__(self, *, standing_probe: object | None = None, backfill: list[object] | None = None) -> None:
        self.ops: list[str] = []
        self._standing_probe = standing_probe
        self._backfill = backfill or []

    async def execute(self, statement: object) -> Mock:
        self.ops.append(type(statement).__name__.lower())
        return Mock()

    async def scalar(self, statement: object) -> object | None:
        self.ops.append("scalar")
        return self._standing_probe

    async def scalars(self, statement: object) -> Mock:
        self.ops.append("scalars")
        result = Mock()
        result.all.return_value = self._backfill
        return result

    async def flush(self) -> None:
        self.ops.append("flush")

    async def commit(self) -> None:
        self.ops.append("commit")

    async def rollback(self) -> None:
        self.ops.append("rollback")

    async def get(self, model: object, pk: object) -> None:
        self.ops.append("get")
        return None


def _plan(**overrides: object) -> ExportPlan:
    defaults: dict[str, object] = {
        "tournament_id": 7,
        "formation_node_id": 70,
        "teams": [
            MaterializationTeam(
                balancer_name="Alpha#1234",
                members=(MaterializationMember(name="Alpha#1234", rank=3000, slot_code="tank"),),
            )
        ],
    }
    defaults.update(overrides)
    return ExportPlan(**defaults)  # type: ignore[arg-type]


class TeamMaterializationServiceTests(IsolatedAsyncioTestCase):
    async def test_success_commits_exactly_once_after_finalize(self) -> None:
        session = _FakeSession()
        finalized: list[object] = []

        async def finalize(inner: object, by_name: object) -> None:
            session.ops.append("finalize")
            finalized.append(by_name)

        plan = _plan(prior_team_ids=[11, 12], finalize=finalize, unlink=lambda: session.ops.append("unlink"))

        with patch.object(service_module, "materialize_teams", AsyncMock(return_value=MaterializationResult())):
            outcome = await TeamMaterializationService().run(session, plan)  # type: ignore[arg-type]

        # Three deletes (Standing, Player, Team) -> unlink -> flush -> backfill
        # -> finalize -> exactly one commit, and never a rollback.
        self.assertEqual(
            ["delete", "delete", "delete", "unlink", "flush", "scalars", "finalize", "commit"],
            session.ops,
        )
        self.assertEqual(1, session.ops.count("commit"))
        self.assertNotIn("rollback", session.ops)
        self.assertEqual(2, outcome.removed_teams)
        self.assertEqual(1, outcome.imported_teams)
        self.assertEqual(1, len(finalized))

    async def test_failure_rolls_back_before_stamping_and_never_commits_the_deletes(self) -> None:
        session = _FakeSession()
        stamped: list[BaseException] = []

        async def on_failure(inner: object, exc: BaseException) -> None:
            session.ops.append("stamp")
            stamped.append(exc)

        plan = _plan(prior_team_ids=[11], on_failure=on_failure)
        boom = RuntimeError("writer exploded")

        with patch.object(service_module, "materialize_teams", AsyncMock(side_effect=boom)):
            with self.assertRaises(RuntimeError) as caught:
                await TeamMaterializationService().run(session, plan)  # type: ignore[arg-type]

        self.assertIs(boom, caught.exception)
        self.assertIs(boom, stamped[0])
        # The rollback MUST precede the stamp, and the only commit in the whole
        # sequence is the one that persists the failure stamp — so the pending
        # DELETEs are discarded rather than committed.
        self.assertEqual(
            ["delete", "delete", "delete", "flush", "rollback", "stamp", "commit"],
            session.ops,
        )
        self.assertLess(session.ops.index("rollback"), session.ops.index("stamp"))
        self.assertEqual(1, session.ops.count("commit"))

    async def test_failure_without_a_stamp_hook_still_rolls_back(self) -> None:
        session = _FakeSession()
        with patch.object(service_module, "materialize_teams", AsyncMock(side_effect=RuntimeError("boom"))):
            with self.assertRaises(RuntimeError):
                await TeamMaterializationService().run(session, _plan(prior_team_ids=[5]))  # type: ignore[arg-type]

        self.assertIn("rollback", session.ops)
        self.assertNotIn("commit", session.ops)

    async def test_guard_refuses_when_foreign_standings_exist(self) -> None:
        session = _FakeSession(standing_probe=1)
        plan = _plan(prior_team_ids=[11], guard_standings=True)

        with patch.object(service_module, "materialize_teams", AsyncMock()) as writer:
            with self.assertRaises(ApiHTTPException) as caught:
                await TeamMaterializationService().run(session, plan)  # type: ignore[arg-type]

        self.assertEqual(409, caught.exception.status_code)
        writer.assert_not_awaited()
        # Refused before any destructive statement ran.
        self.assertNotIn("delete", session.ops)
        self.assertIn("rollback", session.ops)

    async def test_guard_allows_when_no_foreign_standings(self) -> None:
        session = _FakeSession(standing_probe=None)
        plan = _plan(guard_standings=True)

        with patch.object(service_module, "materialize_teams", AsyncMock(return_value=MaterializationResult())):
            outcome = await TeamMaterializationService().run(session, plan)  # type: ignore[arg-type]

        self.assertEqual(0, outcome.removed_teams)
        self.assertIn("commit", session.ops)
        self.assertNotIn("delete", session.ops)

    async def test_no_prior_export_skips_the_destructive_phase(self) -> None:
        session = _FakeSession()
        with patch.object(service_module, "materialize_teams", AsyncMock(return_value=MaterializationResult())):
            await TeamMaterializationService().run(session, _plan())  # type: ignore[arg-type]

        self.assertNotIn("delete", session.ops)
        self.assertNotIn("flush", session.ops)
        self.assertEqual(["scalars", "commit"], session.ops)
