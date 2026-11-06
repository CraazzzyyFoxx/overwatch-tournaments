"""The aggregate node on the test Postgres: refused on save, computed by the engine, input state followed (spec §7.4)."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.stage import Stage
from shared.models.tournament.standings import Standing
from shared.models.tournament.tournament import Tournament
from src.schemas.flow import FlowChanges, FlowNodeUpsert
from src.services.flow.engine import flow_engine
from src.services.flow.service import flow_service
from tests._encounter_layer import EncounterLayerCase, add_encounter

DONE = datetime(2026, 1, 8, tzinfo=UTC)


class FlowAggregateDbTests(EncounterLayerCase):
    async def _stage(self, s, name: str, status: str, standings: list[tuple[int, int, float]], **standing) -> FlowNode:
        """A team stage with its node and ``(team index, position, points)`` standings."""
        stage = Stage(
            tournament_id=self.tournament_id,
            scoring_rule_id=self.rule_id,
            name=name,
            stage_type=enums.StageType.ROUND_ROBIN,
            order=5,
        )
        s.add(stage)
        await s.flush()
        node = FlowNode(
            tournament_id=self.tournament_id,
            kind="stage",
            name=name,
            status=status,
            stage_id=stage.id,
            completed_at=DONE if status == "completed" else None,
        )
        s.add(node)
        for team, position, points in standings:
            s.add(
                Standing(
                    tournament_id=self.tournament_id,
                    stage_id=stage.id,
                    team_id=self.teams[team],
                    position=position,
                    matches=2,
                    points=points,
                    **standing,
                )
            )
        await s.flush()
        return node

    def _node(self, kind: str, name: str, config: dict) -> FlowNode:
        return FlowNode(tournament_id=self.tournament_id, kind=kind, name=name, status="pending", config=config)

    def _edge(self, source: FlowNode, source_port: str, target: FlowNode, target_port: str) -> FlowEdge:
        return FlowEdge(
            tournament_id=self.tournament_id,
            source_node_id=source.id,
            source_port=source_port,
            target_node_id=target.id,
            target_port=target_port,
        )

    async def _recompute(self) -> None:
        async with self.Session() as s:
            await flow_engine.recompute(s, self.tournament_id)
            await s.commit()

    async def _ranking(self, node: FlowNode) -> list[tuple[int, float | None, str]]:
        async with self.Session() as s:
            rows = await s.execute(
                sa.select(FlowNodeResult.team_id, FlowNodeResult.score, FlowNodeResult.state)
                .where(FlowNodeResult.node_id == node.id, FlowNodeResult.port == "ranking")
                .order_by(FlowNodeResult.rank)
            )
            return [(self.teams.index(team_id), score, state) for team_id, score, state in rows]

    async def test_an_invalid_formula_is_refused_on_save(self) -> None:
        changes = FlowChanges(
            nodes=[
                FlowNodeUpsert(
                    ref="agg",
                    kind=enums.FlowNodeKind.AGGREGATE,
                    name="Season",
                    config={"unit": "players", "score": {"preset": "formula", "formula": "kills"}, "mode": "sum_all"},
                    position_x=0,
                    position_y=0,
                )
            ],
            edges=[],
            delete_node_ids=[],
            delete_edge_ids=[],
        )
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as caught:
                await flow_service.apply_changes(s, self.tournament_id, changes, actor=None)
        self.assertEqual(422, caught.exception.status_code)
        self.assertIn("ffa_formula_unknown_name", str(caught.exception.detail))
        async with self.Session() as s:
            count = await s.scalar(
                sa.select(sa.func.count()).select_from(FlowNode).where(FlowNode.kind == enums.FlowNodeKind.AGGREGATE)
            )
        self.assertEqual(0, count)

    async def test_engine_aggregates_two_stage_nodes_and_follows_input_state(self) -> None:
        async with self.Session() as s:
            first = await self._stage(s, "Day 1", "completed", [(0, 1, 6.0), (1, 2, 3.0)])
            second = await self._stage(s, "Day 2", "live", [(1, 1, 5.0), (0, 2, 1.0)])
            agg = self._node(
                "aggregate", "Season", {"unit": "teams", "score": {"preset": "stage_points"}, "mode": "sum_all"}
            )
            board = self._node("leaderboard", "Final", {})
            s.add_all([agg, board])
            await s.flush()
            s.add_all(
                [
                    self._edge(first, "ranking", agg, "inputs"),
                    self._edge(second, "ranking", agg, "inputs"),
                    self._edge(agg, "ranking", board, "ranking"),
                ]
            )
            await s.commit()

        await self._recompute()
        self.assertEqual([(1, 8.0, "tentative"), (0, 7.0, "tentative")], await self._ranking(agg))
        self.assertEqual("tentative", await self._node_status(agg))

        async with self.Session() as s:
            await s.execute(
                sa.update(FlowNode).where(FlowNode.id == second.id).values(status="completed", completed_at=DONE)
            )
            await s.commit()
        await self._recompute()
        self.assertEqual([(1, 8.0, "final"), (0, 7.0, "final")], await self._ranking(agg))
        self.assertEqual([(1, 8.0, "final"), (0, 7.0, "final")], await self._ranking(board))
        self.assertEqual("final", await self._node_status(agg))

    async def test_stage_rows_carry_their_metrics(self) -> None:
        async with self.Session() as s:
            node = await self._stage(
                s, "Groups", "live", [(0, 1, 6.0)], win=2, draw=0, lose=1, score_differential=3, buchholz=None
            )
            await s.commit()
        await self._recompute()
        async with self.Session() as s:
            breakdown = await s.scalar(sa.select(FlowNodeResult.breakdown).where(FlowNodeResult.node_id == node.id))
        self.assertEqual({"wins": 2, "draws": 0, "losses": 1, "map_diff": 3, "buchholz": 0, "ffa_score": 0}, breakdown)

    async def test_elimination_ties_share_a_place_and_unplayed_teams_rank_last(self) -> None:
        async with self.Session() as s:
            # Positions as an elimination table leaves them: two semi-final losers share 3rd, one seed never played.
            stage = await self._stage(s, "Playoff", "completed", [(0, 1, 0.0), (1, 3, 0.0), (2, 3, 0.0), (3, 0, 0.0)])
            agg = self._node(
                "aggregate",
                "Points",
                {
                    "unit": "teams",
                    "score": {"preset": "placement_table", "table": {"1": 10, "2": 6, "3": 3, "4": 1}},
                    "mode": "sum_all",
                },
            )
            s.add(agg)
            await s.flush()
            s.add(self._edge(stage, "ranking", agg, "inputs"))
            await s.commit()

        await self._recompute()

        async with self.Session() as s:
            rows = await s.execute(
                sa.select(FlowNodeResult.team_id, FlowNodeResult.tie_group)
                .where(FlowNodeResult.node_id == stage.id)
                .order_by(FlowNodeResult.rank)
            )
            ranked = [(self.teams.index(team_id), tie) for team_id, tie in rows]
        self.assertEqual([(0, None), (1, 2), (2, 2), (3, None)], ranked)
        # Both semi-final losers score the head place of their tie (2nd); the team that never played takes 4th.
        self.assertEqual(
            [(0, 10.0, "final"), (1, 6.0, "final"), (2, 6.0, "final"), (3, 1.0, "final")], await self._ranking(agg)
        )

    async def test_a_completed_stage_without_completed_at_is_ordered_by_its_latest_encounter(self) -> None:
        async with self.Session() as s:
            first = await self._stage(s, "Day 1", "completed", [(0, 1, 6.0), (1, 2, 3.0)])
            second = await self._stage(s, "Day 2", "completed", [(1, 1, 5.0), (0, 2, 1.0)])
            await s.execute(sa.update(FlowNode).where(FlowNode.id.in_([first.id, second.id])).values(completed_at=None))
            tournament = await s.get_one(Tournament, self.tournament_id)
            # Day 1 is the later edge's predecessor but the more recent in time.
            for node, ended in ((first, datetime(2026, 1, 15, tzinfo=UTC)), (second, datetime(2026, 1, 1, tzinfo=UTC))):
                await add_encounter(
                    s,
                    tournament,
                    self.rule_id,
                    teams=[self.teams[0], self.teams[1]],
                    stage_id=node.stage_id,
                    ended_at=ended,
                )
            agg = self._node(
                "aggregate",
                "Latest",
                {"unit": "teams", "score": {"preset": "stage_points"}, "mode": "sum_last_n", "n": 1},
            )
            s.add(agg)
            await s.flush()
            s.add_all([self._edge(first, "ranking", agg, "inputs"), self._edge(second, "ranking", agg, "inputs")])
            await s.commit()

        await self._recompute()

        self.assertEqual([(0, 6.0, "final"), (1, 3.0, "final")], await self._ranking(agg))

    async def _node_status(self, node: FlowNode) -> str:
        async with self.Session() as s:
            return await s.scalar(sa.select(FlowNode.status).where(FlowNode.id == node.id))
