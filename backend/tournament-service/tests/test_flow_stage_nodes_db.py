"""A stage node and its Stage are created and deleted by one graph save (spec §6.4, §13.1; P5 Decision 1)."""

from __future__ import annotations

import pydantic
import sqlalchemy as sa

from shared.core import enums
from shared.models.tournament.flow import FlowNode
from shared.models.tournament.stage import Stage
from src.schemas.admin.stage import StageCreate
from src.schemas.flow import FlowChanges, FlowEdgeUpsert, FlowNodeUpsert
from src.services.flow.service import flow_service
from tests._flow_case import FlowCase


class StageNodeSaveTests(FlowCase):
    async def _apply(self, changes: FlowChanges):
        async with self.Session() as s:
            read = await flow_service.apply_changes(s, self.tournament_id, changes, actor=self.actor)
            await s.commit()
            return read

    async def _issue_codes(self, changes: FlowChanges) -> list[str]:
        async with self.Session() as s:
            plan = await flow_service.plan_changes(s, self.tournament_id, changes)
        return [i.code for i in plan.issues]

    async def test_a_new_stage_node_creates_its_stage_in_the_same_save(self) -> None:
        formation = await self.node("formation", config={"mode": "manual"})
        read = await self._apply(
            FlowChanges(
                nodes=[
                    FlowNodeUpsert(
                        ref="g",
                        kind="stage",
                        name="Groups",
                        stage=StageCreate(name="Groups", stage_type=enums.StageType.ROUND_ROBIN, order=2),
                    )
                ],
                edges=[FlowEdgeUpsert(source=formation, source_port="teams", target="g", target_port="participants")],
            )
        )
        node = next(n for n in read.nodes if n.kind == "stage")
        async with self.Session() as s:
            stage = await s.get(Stage, node.stage_id)
        self.assertEqual(
            ("Groups", enums.StageType.ROUND_ROBIN, 2, self.tournament_id),
            (stage.name, stage.stage_type, stage.order, stage.tournament_id),
        )
        self.assertEqual([(formation, node.id)], [(e.source_node_id, e.target_node_id) for e in read.edges])

    def test_a_stage_payload_on_another_kind_is_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError) as caught:
            FlowNodeUpsert(
                ref="f",
                kind="filter",
                name="F",
                config={"mode": "top", "n": 2},
                stage=StageCreate(name="X", stage_type=enums.StageType.ROUND_ROBIN),
            )
        self.assertEqual("flow_node_stage_misplaced", caught.exception.errors()[0]["type"])

    async def test_a_new_stage_node_without_a_payload_stays_refused(self) -> None:
        codes = await self._issue_codes(FlowChanges(nodes=[FlowNodeUpsert(ref="s", kind="stage", name="S")]))
        self.assertIn("stage_node_managed_by_stage", codes)

    async def test_deleting_a_draft_stage_node_deletes_its_stage(self) -> None:
        stage_id, node_id = await self.stage(name="Old")
        await self._apply(FlowChanges(delete_node_ids=[node_id]))
        async with self.Session() as s:
            self.assertIsNone(await s.get(Stage, stage_id))
            self.assertIsNone(await s.get(FlowNode, node_id))

    async def test_deleting_a_live_stage_node_is_frozen_and_keeps_the_stage(self) -> None:
        stage_id, node_id = await self.stage(name="Running")
        async with self.Session() as s:
            await s.execute(sa.update(FlowNode).where(FlowNode.id == node_id).values(status="live"))
            await s.commit()
        self.assertIn("node_frozen", await self._issue_codes(FlowChanges(delete_node_ids=[node_id])))
        async with self.Session() as s:
            self.assertIsNotNone(await s.get(Stage, stage_id))

    async def test_renaming_a_saved_stage_node_renames_its_stage(self) -> None:
        stage_id, node_id = await self.stage(name="Old")
        await self._apply(FlowChanges(nodes=[FlowNodeUpsert(id=node_id, kind="stage", name="Playoff")]))
        async with self.Session() as s:
            self.assertEqual("Playoff", (await s.get(Stage, stage_id)).name)
            self.assertEqual("Playoff", (await s.get(FlowNode, node_id)).name)
