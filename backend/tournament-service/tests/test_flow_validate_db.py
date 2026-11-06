"""Dry-run validation of a flow diff (P5 Decision 2) and the typed config seeds (Decision 3)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from shared.core import enums
from shared.models.tournament.flow import FlowNode
from src import schemas
from src.rpc import _helpers as rpc_helpers
from src.rpc import flow
from src.schemas.flow import FlowChanges, FlowEdgeUpsert, FlowNodeUpsert
from src.services.flow.service import flow_service
from tests._flow_case import FlowCase
from tests._rpc_fakes import CapturingBroker, make_identity


class ValidateChangesTests(FlowCase):
    async def _validate(self, changes: FlowChanges):
        async with self.Session() as s:
            return await flow_service.validate_changes(s, self.tournament_id, changes)

    async def _node_count(self) -> int:
        async with self.Session() as s:
            return await s.scalar(
                sa.select(sa.func.count()).select_from(FlowNode).where(FlowNode.tournament_id == self.tournament_id)
            )

    async def test_validate_maps_new_nodes_to_refs_and_writes_nothing(self) -> None:
        formation = await self.node("formation", config={"mode": "manual"})
        before = await self._node_count()
        result = await self._validate(
            FlowChanges(
                nodes=[
                    FlowNodeUpsert(
                        ref="g",
                        kind="stage",
                        name="Groups",
                        stage=schemas.StageCreate(name="Groups", stage_type=enums.StageType.ROUND_ROBIN),
                    )
                ],
                edges=[FlowEdgeUpsert(source=formation, source_port="teams", target="g", target_port="participants")],
            )
        )
        self.assertEqual({"g": -1}, result.ref_ids)
        self.assertEqual([-1], result.new_edge_ids)
        self.assertEqual([], [i.code for i in result.issues if i.severity == "error"])
        ports = {p.node_id: [(x.name, x.direction, x.unit) for x in p.ports] for p in result.ports}
        self.assertEqual([("participants", "in", "teams"), ("ranking", "out", "teams")], ports[-1])
        self.assertIn(formation, ports)
        self.assertEqual(before, await self._node_count())

    async def test_validate_names_the_new_edge_of_a_unit_mismatch(self) -> None:
        registration = await self.node("registration")
        result = await self._validate(
            FlowChanges(
                nodes=[
                    FlowNodeUpsert(
                        ref="g",
                        kind="stage",
                        name="Groups",
                        stage=schemas.StageCreate(name="Groups", stage_type=enums.StageType.ROUND_ROBIN),
                    )
                ],
                edges=[
                    FlowEdgeUpsert(
                        source=registration, source_port="participants", target="g", target_port="participants"
                    )
                ],
            )
        )
        self.assertIn(("unit_mismatch", -1), [(i.code, i.edge_id) for i in result.issues])

    async def test_validate_reports_frozen_node_without_writing(self) -> None:
        registration = await self.node("registration", "open")
        result = await self._validate(FlowChanges(delete_node_ids=[registration]))
        self.assertIn(("node_frozen", registration), [(i.code, i.node_id) for i in result.issues])
        self.assertEqual("open", await self.node_status(registration))

    async def test_admin_read_carries_the_config_seeds(self) -> None:
        async with self.Session() as s:
            read = await flow_service.get_admin_read(s, self.tournament_id)
        seeds = read.config_defaults
        self.assertEqual(
            ("manual", "top", 1, "sum_all", "stage_points", "Bucket 1"),
            (
                seeds.formation.mode,
                seeds.filter.mode,
                seeds.filter.n,
                seeds.aggregate.mode,
                seeds.aggregate.score.preset,
                seeds.split.buckets[0].name,
            ),
        )

    async def test_the_route_needs_tournament_update(self) -> None:
        broker = CapturingBroker()
        flow.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        handler = broker.handlers["rpc.tournament.flow_validate"]

        def grant(action: str) -> list[dict]:
            return [
                {
                    "workspace_id": self.workspace_id,
                    "rbac_roles": [],
                    "rbac_permissions": [{"resource": "tournament", "action": action}],
                }
            ]

        data = {"id": str(self.tournament_id), "payload": {"nodes": [], "edges": []}}
        with patch.object(rpc_helpers.db, "async_session_maker", self.Session):
            denied = await handler({**data, "identity": make_identity(workspaces=grant("read"))}, None)
            allowed = await handler({**data, "identity": make_identity(workspaces=grant("update"))}, None)
        self.assertEqual(("forbidden", False), (denied["error"]["code"], denied["ok"]))
        self.assertTrue(allowed["ok"], allowed)
        self.assertEqual({}, allowed["data"]["ref_ids"])
