"""Skip-mode advisories survive each export RPC's response mapping."""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from shared.core.enums import DraftAutopickStrategy, DraftFormat, DraftPoolSource, DraftStatus
from shared.domain.roster_shape import RosterShape
from shared.models.draft import DraftSession
from src import schemas
from src.rpc import admin, binary, draft
from src.services.team_export import ExportOutcome, MaterializationResult


class ExportAdvisoryWireTests(IsolatedAsyncioTestCase):
    async def _call(self, module, subject, patches):
        handlers = {}
        broker = MagicMock()
        broker.subscriber.side_effect = lambda name: lambda fn: handlers.setdefault(name, fn)
        module.register(broker, MagicMock())
        session = AsyncMock()

        async def envelope(logger, operation, op, **kwargs):
            response = await op(session)
            return response.model_dump(mode="json") if hasattr(response, "model_dump") else response

        with ExitStack() as stack:
            for name, value in patches.items():
                stack.enter_context(patch.object(module, name, value))
            stack.enter_context(patch.object(module.c, "envelope", envelope))
            stack.enter_context(patch.object(module.c, "active_actor", return_value=SimpleNamespace(id=1)))
            stack.enter_context(patch.object(module, "ensure_workspace_permission"))
            stack.enter_context(patch.object(module.c, "require_admin_panel"))
            return await handlers[subject]({"id": 1, "tournament_id": 2, "query": {"formation_node_id": ["9"]}}, None)

    async def test_balance_export_returns_named_advisories(self):
        advisories = ["Alpha: skipped Missing#1234 (not found)", "Alpha: team_format_violation: starters_out_of_range"]
        body = await self._call(
            admin,
            "rpc.balancer.admin.balance_export",
            {
                "_get_balance_workspace_id": AsyncMock(return_value=3),
                "quota": SimpleNamespace(charge=AsyncMock()),
                "balancer_admin_service": SimpleNamespace(
                    export_balance=AsyncMock(return_value=(SimpleNamespace(id=1, tournament_id=2), 0, 1, advisories))
                ),
            },
        )
        self.assertEqual(body["advisories"], advisories)
        self.assertEqual(body["imported_teams"], 1)

    async def test_team_import_returns_named_advisories(self):
        advisories = ["Alpha: skipped Duplicate#1234 (already in tournament)"]
        body = await self._call(
            binary,
            "rpc.balancer.admin.teams_import",
            {
                "_get_tournament_workspace_id": AsyncMock(return_value=3),
                "require_formation_node": AsyncMock(),
                "quota": SimpleNamespace(charge=AsyncMock()),
                "_decode_and_parse": lambda data: {"data": {"teams": []}},
                "team_service": SimpleNamespace(
                    import_teams=AsyncMock(
                        return_value=ExportOutcome(materialization=MaterializationResult(advisories=advisories))
                    )
                ),
            },
        )
        self.assertEqual(body["advisories"], advisories)

    async def test_draft_export_returns_named_advisories(self):
        advisories = ["Alpha: team_format_violation: starters_out_of_range"]
        row = DraftSession(
            id=1,
            tournament_id=2,
            workspace_id=3,
            status=DraftStatus.COMPLETED.value,
            format=DraftFormat.SNAKE.value,
            rounds=4,
            pick_time_seconds=45,
            overtime_seconds=0,
            pool_source=DraftPoolSource.BALANCER_BALANCE.value,
            autopick_strategy=DraftAutopickStrategy.BEST_FIT.value,
            allow_admin_override=True,
            settings_json={},
            version=1,
            export_status="success",
        )
        read = schemas.DraftSessionRead.from_session(
            row, shape=RosterShape(entries=(("flex", 5),)), discipline="overwatch"
        )
        body = await self._call(
            draft,
            "rpc.balancer.draft.export",
            {
                "_get_tournament_workspace_id": AsyncMock(return_value=3),
                "lifecycle_service": SimpleNamespace(get_session=AsyncMock(return_value=row)),
                "export_service": SimpleNamespace(export=AsyncMock(return_value=(row, 0, 1, advisories))),
                "board_service": SimpleNamespace(session_read=AsyncMock(return_value=read)),
            },
        )
        self.assertEqual(body["advisories"], advisories)
        self.assertEqual(body["export_status"], "success")
