"""``rpc.tournament.flow_apply``: permission, the audit row, the commit and the error mapping."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from shared import models
from src.rpc import _helpers as rpc_helpers
from src.rpc import flow
from tests._flow_case import FlowCase
from tests._rpc_fakes import CapturingBroker, make_identity


class FlowApplyRpcTests(FlowCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        broker = CapturingBroker()
        flow.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.handler = broker.handlers["rpc.tournament.flow_apply"]

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:  # the audit journal has no FK, so the workspace delete leaves its rows
            await s.execute(
                sa.delete(models.AuditLog).where(
                    models.AuditLog.action == "tournament.flow_apply", models.AuditLog.entity_id == self.tournament_id
                )
            )
            await s.commit()
        await super().asyncTearDown()

    async def _ask(self, payload: dict, action: str) -> dict:
        grant = {
            "workspace_id": self.workspace_id,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "tournament", "action": action}],
        }
        data = {"id": str(self.tournament_id), "payload": payload, "identity": make_identity(workspaces=[grant])}
        with patch.object(rpc_helpers.db, "async_session_maker", self.Session):
            return await self.handler(data, None)

    async def _audit_count(self) -> int:
        async with self.Session() as s:
            return await s.scalar(
                sa.select(sa.func.count())
                .select_from(models.AuditLog)
                .where(
                    models.AuditLog.action == "tournament.flow_apply", models.AuditLog.entity_id == self.tournament_id
                )
            )

    async def test_needs_tournament_update(self) -> None:
        reply = await self._ask({"nodes": [{"ref": "r", "kind": "registration", "name": "R"}]}, "read")
        self.assertEqual(("forbidden", False), (reply["error"]["code"], reply["ok"]))
        self.assertEqual(0, await self._audit_count())

    async def test_commits_the_graph_audits_and_answers_the_admin_read(self) -> None:
        reply = await self._ask({"nodes": [{"ref": "r", "kind": "registration", "name": "Day 3"}]}, "update")
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(["Day 3"], [n["name"] for n in reply["data"]["nodes"]])
        self.assertIn("catalogue", reply["data"])
        self.assertEqual(1, await self._audit_count())

    async def test_a_frozen_node_is_a_conflict_and_changes_nothing(self) -> None:
        reg = await self.node("registration", "open")
        reply = await self._ask({"delete_node_ids": [reg]}, "update")
        self.assertEqual(("conflict", False), (reply["error"]["code"], reply["ok"]))
        self.assertEqual("open", await self.node_status(reg))
        self.assertEqual(0, await self._audit_count())
