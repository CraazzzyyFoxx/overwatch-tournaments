"""``recompute_flows.py``: the post-deploy backfill of flow results (spec §14)."""

from __future__ import annotations

import importlib
from unittest import mock

import sqlalchemy as sa

from shared.core import enums
from shared.models.tournament.flow import FlowNode, FlowNodeResult
from shared.models.tournament.standings import Standing
from shared.models.tournament.tournament import Tournament
from tests._encounter_layer import EncounterLayerCase

recompute_flows = importlib.import_module("recompute_flows")


class RecomputeFlowsCliTests(EncounterLayerCase):
    async def test_recompute_all_writes_results_once(self) -> None:
        async with self.Session() as s:
            node = await s.scalar(sa.select(FlowNode).where(FlowNode.stage_id == self.stage_id))
            node.status = "live"
            s.add_all(
                [
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
            ({self.tournament_id: 1}, {}),
            await recompute_flows.recompute_all(self.Session, tournament_id=self.tournament_id),
        )
        self.assertEqual(
            ({self.tournament_id: 0}, {}),
            await recompute_flows.recompute_all(self.Session, tournament_id=self.tournament_id),
        )
        async with self.Session() as s:
            self.assertEqual(
                [self.teams[0]],
                list(await s.scalars(sa.select(FlowNodeResult.team_id).where(FlowNodeResult.node_id == node.id))),
            )

    async def test_a_failing_tournament_is_reported_and_the_rest_still_run(self) -> None:
        async with self.Session() as s:
            other = Tournament(
                workspace_id=self.workspace_id, name="other", slug="other", status=enums.TournamentStatus.LIVE
            )
            s.add(other)
            await s.flush()
            other_id = other.id
            s.add_all(
                [
                    FlowNode(tournament_id=self.tournament_id, kind="registration", name="R", status="draft"),
                    FlowNode(tournament_id=other_id, kind="registration", name="R", status="draft"),
                ]
            )
            await s.commit()
        real = recompute_flows.flow_engine.recompute

        async def recompute(session, tid):
            if tid == self.tournament_id:
                raise ValueError("cycle")
            return await real(session, tid)

        with mock.patch.object(recompute_flows.flow_engine, "recompute", recompute):
            changed, failed = await recompute_flows.recompute_all(self.Session)
        self.assertEqual([self.tournament_id], list(failed))
        self.assertIn(other_id, changed)
        self.assertNotIn(self.tournament_id, changed)
