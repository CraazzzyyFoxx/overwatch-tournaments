"""The two flow reads (spec §6.1 catalogue, §8 results) and their gates."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from shared.core import enums
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.stage import Stage
from shared.models.tournament.tournament import Tournament
from shared.tests.encounter_writer_case import EncounterWriterCase
from src.rpc import _helpers as rpc_helpers
from src.rpc import flow
from tests._rpc_fakes import CapturingBroker, make_identity


class FlowReadRpcTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        broker = CapturingBroker()
        flow.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.public, self.admin = broker.handlers["rpc.tournament.get_flow"], broker.handlers["rpc.tournament.flow_get"]
        t = self.ids["t"]
        async with self.Session() as s:
            stage = Stage(
                tournament_id=t,
                scoring_rule_id=self.ids["rule"],
                name="Main",
                stage_type=enums.StageType.ROUND_ROBIN,
                order=0,
            )
            s.add(stage)
            await s.flush()
            reg = FlowNode(tournament_id=t, kind="registration", name="Registration", status="closed", config={})
            form = FlowNode(
                tournament_id=t, kind="formation", name="Teams", status="completed", config={"mode": "balancer"}
            )
            main = FlowNode(tournament_id=t, kind="stage", name="Main", status="live", config={}, stage_id=stage.id)
            s.add_all([reg, form, main])
            await s.flush()
            s.add_all(
                [
                    FlowEdge(
                        tournament_id=t,
                        source_node_id=reg.id,
                        source_port="participants",
                        target_node_id=form.id,
                        target_port="players",
                    ),
                    FlowEdge(
                        tournament_id=t,
                        source_node_id=form.id,
                        source_port="teams",
                        target_node_id=main.id,
                        target_port="participants",
                    ),
                    FlowNodeResult(node_id=form.id, port="teams", rank=1, team_id=self.ids["team0"], state="final"),
                ]
            )
            await s.commit()
            self.form_id, self.main_id = form.id, main.id

    async def _ask(self, handler, identity=None) -> dict:
        data = {"id": str(self.ids["t"])}
        if identity is not None:
            data["identity"] = identity
        with patch.object(rpc_helpers.db, "async_session_maker", self.Session):
            return await handler(data, None)

    async def test_the_public_read_returns_the_graph_with_ports_and_results(self) -> None:
        reply = await self._ask(self.public)
        self.assertTrue(reply["ok"], reply)
        data = reply["data"]
        self.assertEqual(["registration", "formation", "stage"], [n["kind"] for n in data["nodes"]])
        main = data["nodes"][2]
        self.assertEqual(
            [("participants", "in", "teams"), ("ranking", "out", "teams")],
            [(p["name"], p["direction"], p["unit"]) for p in main["ports"]],
        )
        self.assertEqual(2, len(data["edges"]))
        self.assertEqual(
            [(self.form_id, "teams", 1, self.ids["team0"], "final")],
            [(r["node_id"], r["port"], r["rank"], r["team_id"], r["state"]) for r in data["results"]],
        )

    async def test_a_hidden_tournament_is_not_found_for_an_anonymous_viewer(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.update(Tournament).where(Tournament.id == self.ids["t"]).values(is_hidden=True))
            await s.commit()
        reply = await self._ask(self.public)
        self.assertEqual(("not_found", False), (reply["error"]["code"], reply["ok"]))

    async def test_the_admin_read_needs_tournament_read_and_adds_issues_and_catalogue(self) -> None:
        denied = await self._ask(self.admin, make_identity())
        self.assertEqual(("forbidden", False), (denied["error"]["code"], denied["ok"]))

        grant = [
            {
                "workspace_id": self.ids["ws"],
                "rbac_roles": [],
                "rbac_permissions": [{"resource": "tournament", "action": "read"}],
            }
        ]
        reply = await self._ask(self.admin, make_identity(workspaces=grant))
        self.assertTrue(reply["ok"], reply)
        self.assertEqual([], reply["data"]["issues"])
        self.assertEqual([k.value for k in enums.FlowNodeKind], [c["kind"] for c in reply["data"]["catalogue"]])
        split = next(c for c in reply["data"]["catalogue"] if c["kind"] == "split")
        self.assertEqual(
            [("bucket", True, "input")], [(p["name"], p["repeated"], p["unit_rule"]) for p in split["outputs"]]
        )
