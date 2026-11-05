"""The ExportPlan `export_registered` hands to the shared orchestrator.

This path is the third caller of the shared materialization sequence, and it
differs from the other two in exactly two settings. Both are safety properties that
a copy-paste from `draft/export.py` would silently drop, so both are asserted on the
plan itself rather than inferred from behaviour:

* `guard_standings=True` — refuse rather than destroy a live bracket;
* `on_unresolved="error"` — never write an under-sized roster silently.

The third property has no flag: with no complete teams the orchestrator must not be
entered at all, so no standings guard and no transaction happen for a no-op.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase, mock

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent
for path in (str(SERVICE_ROOT), str(BACKEND_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


from shared import models  # noqa: E402
from shared.domain.roster_shape import RosterShape  # noqa: E402
from src.services import registered_teams  # noqa: E402
from src.services.team_export import ExportOutcome, ExportPlan  # noqa: E402
from src.services.team_export.materialization import MaterializationTeam  # noqa: E402
from src.services.team_export.registered import RegisteredExportPayload, SkippedTeam  # noqa: E402

SHAPE = RosterShape(entries=(("tank", 1), ("damage", 2), ("support", 2)))


class _Result:
    """Mimics the ``session.execute(...)`` result shape ``BaseRepository.get`` expects."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def unique(self) -> _Result:
        return self

    def scalars(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._value


class _Session:
    """Answers only the tournament lookup ``export_registered`` starts with, via
    ``TournamentRepository.get`` (which issues ``session.execute``, not
    ``session.get``, so this module still needs no repository-boundary exemption).
    """

    def __init__(self, tournament: object | None) -> None:
        self.tournament = tournament

    async def execute(self, statement: Any) -> _Result:
        return _Result(self.tournament)


def _tournament() -> models.Tournament:
    tournament = models.Tournament(name="T", slug="t", workspace_id=3)
    tournament.id = 7
    return tournament


def _payload_with_one_team() -> RegisteredExportPayload:
    source = models.RegistrationTeam(tournament_id=7, name="Alpha", status="complete")
    source.id = 11
    return RegisteredExportPayload(
        teams=[MaterializationTeam(balancer_name="Alpha")],
        prior_team_ids=[99],
        source_teams=[source],
    )


class PlanWiringTests(IsolatedAsyncioTestCase):
    async def _captured_plan(self, payload: RegisteredExportPayload) -> ExportPlan:
        captured: list[ExportPlan] = []

        async def _run(session: Any, plan: ExportPlan) -> ExportOutcome:
            captured.append(plan)
            return ExportOutcome(removed_teams=1, imported_teams=1)

        with (
            mock.patch.object(registered_teams, "build_registered_export", return_value=payload),
            mock.patch.object(registered_teams, "tournament_slot_shape", return_value=SHAPE),
            mock.patch.object(registered_teams, "require_forming", mock.AsyncMock()),
            mock.patch.object(registered_teams.team_materialization, "run", side_effect=_run),
            mock.patch.object(registered_teams, "stage_export_invalidation", mock.AsyncMock()),
        ):
            await registered_teams.registered_teams_service.export_registered(
                _Session(_tournament()), 7, 70, actor_user_id=1
            )  # type: ignore[arg-type]
        self.assertEqual(1, len(captured))
        return captured[0]

    async def test_standings_are_guarded(self) -> None:
        """The balancer and draft exports re-export destructively by design; doing
        that here would silently invalidate a bracket already built on these teams."""
        plan = await self._captured_plan(_payload_with_one_team())
        self.assertIs(True, plan.guard_standings)

    async def test_unresolved_members_are_an_error_not_a_skip(self) -> None:
        """Registered members arrive pre-resolved, so a resolution failure is a bug.
        `"skip"` would drop the member and materialize an under-sized team with
        nothing raised anywhere."""
        plan = await self._captured_plan(_payload_with_one_team())
        self.assertEqual("error", plan.on_unresolved)

    async def test_the_plan_names_the_formation_node(self) -> None:
        plan = await self._captured_plan(_payload_with_one_team())
        self.assertEqual(70, plan.formation_node_id)

    async def test_the_prior_export_is_replaced_not_duplicated(self) -> None:
        plan = await self._captured_plan(_payload_with_one_team())
        self.assertEqual([99], list(plan.prior_team_ids))

    async def test_all_three_hooks_are_supplied(self) -> None:
        """Missing `unlink` leaves stale `exported_team_id` back-links pointing at
        deleted rows; missing `on_failure` leaves the source silently un-stamped."""
        plan = await self._captured_plan(_payload_with_one_team())
        self.assertIsNotNone(plan.unlink)
        self.assertIsNotNone(plan.finalize)
        self.assertIsNotNone(plan.on_failure)


class NoOpExportTests(IsolatedAsyncioTestCase):
    async def test_nothing_to_export_does_not_enter_the_orchestrator(self) -> None:
        """A no-op must not take the standings guard or open a transaction — an
        organizer pressing export early should get a report, not a refusal."""
        payload = RegisteredExportPayload(skipped=[SkippedTeam(team_id=4, name="Beta", code="team_incomplete")])
        runner = mock.AsyncMock()

        with (
            mock.patch.object(registered_teams, "build_registered_export", return_value=payload),
            mock.patch.object(registered_teams, "tournament_slot_shape", return_value=SHAPE),
            mock.patch.object(registered_teams, "require_forming", mock.AsyncMock()),
            mock.patch.object(registered_teams.team_materialization, "run", runner),
        ):
            result = await registered_teams.registered_teams_service.export_registered(
                _Session(_tournament()), 7, 70, actor_user_id=1
            )  # type: ignore[arg-type]

        runner.assert_not_awaited()
        self.assertEqual(0, result.imported_teams)
        self.assertEqual(["team_incomplete"], [item.code for item in result.skipped])

    async def test_skipped_teams_are_reported_alongside_a_real_export(self) -> None:
        """The people in an incomplete team must be told. Dropping the report
        when *some* teams exported is the easy mistake."""
        payload = _payload_with_one_team()
        payload.skipped.append(SkippedTeam(team_id=4, name="Beta", code="team_incomplete"))

        async def _run(session: Any, plan: ExportPlan) -> ExportOutcome:
            return ExportOutcome(removed_teams=0, imported_teams=1)

        with (
            mock.patch.object(registered_teams, "build_registered_export", return_value=payload),
            mock.patch.object(registered_teams, "tournament_slot_shape", return_value=SHAPE),
            mock.patch.object(registered_teams, "require_forming", mock.AsyncMock()),
            mock.patch.object(registered_teams.team_materialization, "run", side_effect=_run),
            mock.patch.object(registered_teams, "stage_export_invalidation", mock.AsyncMock()),
        ):
            result = await registered_teams.registered_teams_service.export_registered(
                _Session(_tournament()), 7, 70, actor_user_id=1
            )  # type: ignore[arg-type]

        self.assertEqual(1, result.imported_teams)
        self.assertEqual(["team_incomplete"], [item.code for item in result.skipped])

    async def test_a_missing_tournament_is_a_404(self) -> None:
        with self.assertRaises(Exception) as caught:
            await registered_teams.registered_teams_service.export_registered(_Session(None), 7, 70, actor_user_id=1)  # type: ignore[arg-type]
        self.assertEqual(404, getattr(caught.exception, "status_code", None))
