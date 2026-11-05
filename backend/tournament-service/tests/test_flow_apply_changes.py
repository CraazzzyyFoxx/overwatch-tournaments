"""``FlowService.apply_changes``: graph writes under the frozen-node rules (spec §6.4)."""

from __future__ import annotations

from shared.core.errors import ApiHTTPException
from src.schemas.flow import FlowChanges, FlowEdgeUpsert, FlowNodeUpsert
from src.services.flow.service import flow_service
from tests._flow_case import FlowCase


class ApplyChangesTests(FlowCase):
    async def _apply(self, changes: FlowChanges):
        async with self.Session() as s:
            read = await flow_service.apply_changes(s, self.tournament_id, changes, actor=self.actor)
            await s.commit()
            return read

    async def _refusal(self, changes: FlowChanges) -> tuple[int, str]:
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as caught:
                await flow_service.apply_changes(s, self.tournament_id, changes, actor=self.actor)
        return caught.exception.status_code, caught.exception.detail[0]["code"]

    async def test_new_registration_and_formation_with_edge_by_ref(self) -> None:
        read = await self._apply(
            FlowChanges(
                nodes=[
                    FlowNodeUpsert(ref="r", kind="registration", name="Day 3"),
                    FlowNodeUpsert(ref="f", kind="formation", name="Teams 3", config={"mode": "balancer"}),
                ],
                edges=[FlowEdgeUpsert(source="r", source_port="participants", target="f", target_port="players")],
            )
        )
        self.assertEqual({("registration", "draft"), ("formation", "draft")}, {(n.kind, n.status) for n in read.nodes})
        self.assertEqual(1, len(read.edges))

    async def test_reconfiguring_a_started_formation_is_node_frozen(self) -> None:
        form = await self.node("formation", "forming", config={"mode": "draft"})
        self.assertEqual(
            (409, "node_frozen"),
            await self._refusal(
                FlowChanges(nodes=[FlowNodeUpsert(id=form, kind="formation", name="F", config={"mode": "manual"})])
            ),
        )

    async def test_intake_settings_of_a_started_registration_stay_editable(self) -> None:
        reg = await self.node("registration", "open")
        read = await self._apply(
            FlowChanges(nodes=[FlowNodeUpsert(id=reg, kind="registration", name="R", config={"auto_approve": True})])
        )
        self.assertEqual({"auto_approve": True}, next(n for n in read.nodes if n.id == reg).config)

    async def test_an_upsert_without_a_position_keeps_the_canvas_position(self) -> None:
        reg = await self.node("registration")
        await self._apply(
            FlowChanges(nodes=[FlowNodeUpsert(id=reg, kind="registration", name="R", position_x=40.0, position_y=8.0)])
        )
        read = await self._apply(FlowChanges(nodes=[FlowNodeUpsert(id=reg, kind="registration", name="Renamed")]))
        node = next(n for n in read.nodes if n.id == reg)
        self.assertEqual(("Renamed", 40.0, 8.0), (node.name, node.position_x, node.position_y))

    async def test_pure_node_frozen_once_downstream_lifecycle_started(self) -> None:
        reg = await self.node("registration", "closed")
        flt = await self.node("filter", "final", config={"mode": "top", "n": 4})
        form = await self.node("formation", "forming", config={"mode": "draft"})
        await self.edge(reg, "participants", flt, "ranking")
        await self.edge(flt, "passed", form, "players")
        self.assertEqual((409, "node_frozen"), await self._refusal(FlowChanges(delete_node_ids=[flt])))

    async def test_appending_a_node_after_a_started_one_is_allowed(self) -> None:
        reg = await self.node("registration", "open")
        read = await self._apply(
            FlowChanges(
                nodes=[FlowNodeUpsert(ref="f", kind="formation", name="Day 2 teams", config={"mode": "manual"})],
                edges=[FlowEdgeUpsert(source=reg, source_port="participants", target="f", target_port="players")],
            )
        )
        self.assertEqual(2, len(read.nodes))

    async def test_invalid_graph_is_422_flow_invalid(self) -> None:
        self.assertEqual(
            (422, "flow_invalid"),
            await self._refusal(
                FlowChanges(
                    nodes=[FlowNodeUpsert(ref="r", kind="registration", name="R")],
                    edges=[FlowEdgeUpsert(source="r", source_port="nope", target="r", target_port="players")],
                )
            ),
        )

    async def test_stage_nodes_are_created_by_stages_only(self) -> None:
        status_code, _ = await self._refusal(FlowChanges(nodes=[FlowNodeUpsert(ref="s", kind="stage", name="S")]))
        self.assertEqual(422, status_code)

    async def test_renaming_and_moving_a_started_node_is_allowed(self) -> None:
        reg = await self.node("registration", "open")
        read = await self._apply(
            FlowChanges(nodes=[FlowNodeUpsert(id=reg, kind="registration", name="Renamed", position_x=40.0)])
        )
        self.assertEqual([("Renamed", 40.0)], [(n.name, n.position_x) for n in read.nodes])

    async def test_cutting_the_input_of_a_started_node_is_node_frozen(self) -> None:
        reg = await self.node("registration", "closed")
        form = await self.node("formation", "forming", config={"mode": "draft"})
        wire = await self.edge(reg, "participants", form, "players")
        self.assertEqual((409, "node_frozen"), await self._refusal(FlowChanges(delete_edge_ids=[wire])))

    async def test_new_pure_node_is_pending_and_deleting_a_draft_node_drops_its_edges(self) -> None:
        reg = await self.node("registration")
        form = await self.node("formation", config={"mode": "manual"})
        await self.edge(reg, "participants", form, "players")
        read = await self._apply(
            FlowChanges(
                nodes=[FlowNodeUpsert(ref="f", kind="filter", name="Top", config={"mode": "top", "n": 3})],
                edges=[FlowEdgeUpsert(source=reg, source_port="participants", target="f", target_port="ranking")],
                delete_node_ids=[form],
            )
        )
        self.assertEqual({("registration", "draft"), ("filter", "pending")}, {(n.kind, n.status) for n in read.nodes})
        self.assertEqual(1, len(read.edges))

    async def test_unknown_node_id_is_not_found(self) -> None:
        self.assertEqual(
            (404, "flow_node_not_found"),
            await self._refusal(FlowChanges(nodes=[FlowNodeUpsert(id=2**31 - 1, kind="registration", name="R")])),
        )

    async def test_invalid_config_is_named_once_with_the_temporary_node_id(self) -> None:
        async with self.Session() as s:
            plan = await flow_service.plan_changes(
                s,
                self.tournament_id,
                FlowChanges(nodes=[FlowNodeUpsert(ref="r", kind="registration", name="R", config={"bogus": 1})]),
            )
        self.assertEqual(
            [("invalid_node_config", -1)], [(i.code, i.node_id) for i in plan.issues if i.severity == "error"]
        )
        self.assertEqual({"r": -1}, plan.ref_ids)

    async def test_an_edge_can_be_repointed_off_a_node_deleted_in_the_same_request(self) -> None:
        reg = await self.node("registration")
        gone = await self.node("formation", config={"mode": "manual"})
        kept = await self.node("formation", config={"mode": "manual"})
        wire = await self.edge(reg, "participants", gone, "players")
        read = await self._apply(
            FlowChanges(
                edges=[
                    FlowEdgeUpsert(id=wire, source=reg, source_port="participants", target=kept, target_port="players")
                ],
                delete_node_ids=[gone],
            )
        )
        self.assertEqual([(wire, reg, kept)], [(e.id, e.source_node_id, e.target_node_id) for e in read.edges])
        self.assertEqual({reg, kept}, {n.id for n in read.nodes})

    async def test_a_kind_change_restarts_the_node_in_the_new_kinds_lifecycle(self) -> None:
        pure = await self.node("filter", "final", config={"mode": "top", "n": 4})
        lifecycle = await self.node("formation", "draft", config={"mode": "manual"})
        read = await self._apply(
            FlowChanges(
                nodes=[
                    FlowNodeUpsert(id=pure, kind="formation", name="F", config={"mode": "manual"}),
                    FlowNodeUpsert(id=lifecycle, kind="filter", name="T", config={"mode": "top", "n": 2}),
                ]
            )
        )
        self.assertEqual(
            {pure: ("formation", "draft"), lifecycle: ("filter", "pending")},
            {n.id: (n.kind, n.status) for n in read.nodes},
        )

    async def test_a_kind_change_of_a_started_node_is_node_frozen(self) -> None:
        form = await self.node("formation", "forming", config={"mode": "manual"})
        self.assertEqual(
            (409, "node_frozen"),
            await self._refusal(
                FlowChanges(nodes=[FlowNodeUpsert(id=form, kind="filter", name="T", config={"mode": "top", "n": 2})])
            ),
        )

    async def test_intake_settings_freeze_once_a_downstream_lifecycle_node_left_draft(self) -> None:
        reg = await self.node("registration", "closed")
        form = await self.node("formation", "forming", config={"mode": "balancer"})
        await self.edge(reg, "participants", form, "players")
        self.assertEqual(
            (409, "node_frozen"),
            await self._refusal(
                FlowChanges(nodes=[FlowNodeUpsert(id=reg, kind="registration", name="R", config={"check_in": True})])
            ),
        )
