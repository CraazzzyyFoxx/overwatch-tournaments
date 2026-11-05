"""``rpc.tournament.flow_node_transition``: permission, the 409 mapping and the committed result."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from shared.core import enums
from src.rpc import _helpers as rpc_helpers
from src.rpc import flow
from tests._flow_case import FlowCase
from tests._rpc_fakes import CapturingBroker, make_identity


class FlowNodeTransitionRpcTests(FlowCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        broker = CapturingBroker()
        flow.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.handler = broker.handlers["rpc.tournament.flow_node_transition"]

    async def _ask(self, node_id: int | str, status: str, identity: dict) -> dict:
        data = {"id": str(node_id), "payload": {"status": status}, "identity": identity}
        with patch.object(rpc_helpers.db, "async_session_maker", self.Session):
            return await self.handler(data, None)

    def _granted(self, action: str) -> dict:
        grant = {
            "workspace_id": self.workspace_id,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "tournament", "action": action}],
        }
        return make_identity(workspaces=[grant])

    async def test_needs_tournament_update(self) -> None:
        reg = await self.node("registration")
        reply = await self._ask(reg, "open", self._granted("read"))
        self.assertEqual(("forbidden", False), (reply["error"]["code"], reply["ok"]))
        self.assertEqual("draft", await self.node_status(reg))

    async def test_moves_the_node_commits_and_answers_the_node_read(self) -> None:
        reg = await self.node("registration")
        reply = await self._ask(reg, "open", self._granted("update"))
        self.assertTrue(reply["ok"], reply)
        self.assertEqual((reg, "open"), (reply["data"]["id"], reply["data"]["status"]))
        self.assertEqual("open", await self.node_status(reg))
        self.assertEqual(enums.TournamentStatus.LIVE, await self.tournament_status())

    async def test_a_refused_move_is_a_conflict_and_changes_nothing(self) -> None:
        reg = await self.node("registration")
        reply = await self._ask(reg, "closed", self._granted("update"))
        self.assertEqual(("conflict", False), (reply["error"]["code"], reply["ok"]))
        self.assertEqual("draft", await self.node_status(reg))

    async def test_an_unknown_node_is_not_found(self) -> None:
        reply = await self._ask(0, "open", self._granted("update"))
        self.assertEqual(("not_found", False), (reply["error"]["code"], reply["ok"]))
