"""``recompute_flows.py``: the post-deploy backfill of flow results (spec §14)."""

from __future__ import annotations

import importlib

import sqlalchemy as sa

from shared.models.tournament.flow import FlowNode, FlowNodeResult
from shared.models.tournament.standings import Standing
from tests._encounter_layer import EncounterLayerCase

recompute_flows = importlib.import_module("recompute_flows")


class RecomputeFlowsCliTests(EncounterLayerCase):
    async def test_recompute_all_writes_results_once(self) -> None:
        async with self.Session() as s:
            node = FlowNode(
                tournament_id=self.tournament_id, kind="stage", name="Playoff", status="live", stage_id=self.stage_id
            )
            s.add_all(
                [
                    node,
                    Standing(
                        tournament_id=self.tournament_id,
                        stage_id=self.stage_id,
                        stage_item_id=self.item_id,
                        team_id=self.teams[0],
                        position=1,
                        matches=1,
                        points=1,
                    ),
                ]
            )
            await s.commit()
        self.assertEqual(
            {self.tournament_id: 1}, await recompute_flows.recompute_all(self.Session, tournament_id=self.tournament_id)
        )
        self.assertEqual(
            {self.tournament_id: 0}, await recompute_flows.recompute_all(self.Session, tournament_id=self.tournament_id)
        )
        async with self.Session() as s:
            self.assertEqual(
                [self.teams[0]],
                list(await s.scalars(sa.select(FlowNodeResult.team_id).where(FlowNodeResult.node_id == node.id))),
            )
