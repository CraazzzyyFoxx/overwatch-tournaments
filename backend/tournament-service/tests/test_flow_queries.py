"""Graph reads of ``shared.services.flow_queries`` over a real Postgres."""

from __future__ import annotations

import sqlalchemy as sa

from shared import models
from shared.services import flow_queries
from tests._flow_case import FlowCase


class FlowQueriesTests(FlowCase):
    async def _members(self, count: int) -> list[int]:
        async with self.Session() as s:
            users = [models.User(name=f"{self.tag}-{i}") for i in range(count)]
            s.add_all(users)
            await s.flush()
            members = [models.WorkspaceMember(workspace_id=self.workspace_id, player_id=u.id) for u in users]
            s.add_all(members)
            await s.commit()
        user_ids = [u.id for u in users]
        self.addAsyncCleanup(self._drop_users, user_ids)
        return [m.id for m in members]

    async def _drop_users(self, user_ids: list[int]) -> None:
        async with self.Session() as s:
            # The workspace (and with it the members) goes in asyncTearDown, which runs first.
            await s.execute(sa.delete(models.User).where(models.User.id.in_(user_ids)))
            await s.commit()

    async def _result(self, node_id: int, port: str, rank: int, *, member: int | None = None, team: int | None = None):
        async with self.Session() as s:
            s.add(
                models.FlowNodeResult(
                    node_id=node_id, port=port, rank=rank, workspace_member_id=member, team_id=team, state="final"
                )
            )
            await s.commit()

    async def test_input_members_follow_edge_then_rank_and_expand_teams_substitutes_last(self) -> None:
        m = await self._members(5)
        source_a = await self.node("registration", "closed")
        source_b = await self.node("formation", "completed", config={"mode": "manual"})
        target = (await self.stage())[1]
        async with self.Session() as s:
            team = models.Team(tournament_id=self.tournament_id, name="T", balancer_name="T")
            s.add(team)
            await s.flush()
            s.add_all(
                models.Player(
                    name=f"p{i}",
                    tournament_id=self.tournament_id,
                    workspace_member_id=m[i],
                    team_id=team.id,
                    is_substitution=is_sub,
                )
                for i, is_sub in ((2, True), (3, False))
            )
            await s.commit()
            team_id = team.id
        await self.edge(source_a, "participants", target, "participants")
        await self.edge(source_b, "teams", target, "participants")
        # Second-ranked first on purpose; m[0] reappears under the team and must not repeat.
        await self._result(source_a, "participants", 2, member=m[1])
        await self._result(source_a, "participants", 1, member=m[0])
        await self._result(source_b, "teams", 1, team=team_id)
        async with self.Session() as s:
            await s.execute(
                sa.insert(models.Player).values(
                    name="dup", tournament_id=self.tournament_id, workspace_member_id=m[0], team_id=team_id
                )
            )
            got = await flow_queries.input_member_ids(s, target)
        self.assertEqual([m[0], m[1], m[3], m[2]], got)

    async def test_upstream_registration_nodes_through_a_chain_newest_first(self) -> None:
        first = await self.node("registration")
        second = await self.node("registration")
        form = await self.node("formation", config={"mode": "manual"})
        stage_node = (await self.stage())[1]
        await self.edge(first, "participants", form, "players")
        await self.edge(second, "participants", form, "players")
        await self.edge(form, "teams", stage_node, "participants")
        async with self.Session() as s:
            self.assertEqual([second, first], await flow_queries.upstream_registration_node_ids(s, stage_node))
            self.assertEqual([], await flow_queries.upstream_registration_node_ids(s, first))

    async def test_downstream_started_looks_through_pure_nodes_and_ignores_draft(self) -> None:
        reg = await self.node("registration", "closed")
        merge = await self.node("merge", "pending")
        stage_node = (await self.stage())[1]
        await self.edge(reg, "participants", merge, "inputs")
        await self.edge(merge, "merged", stage_node, "participants")
        async with self.Session() as s:
            self.assertFalse(await flow_queries.downstream_lifecycle_started(s, reg))
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == stage_node).values(status="ready"))
            self.assertTrue(await flow_queries.downstream_lifecycle_started(s, reg))
            self.assertFalse(await flow_queries.downstream_lifecycle_started(s, stage_node))

    async def test_stage_node_status_correlates_on_the_stage_id(self) -> None:
        stage_id, stage_node = await self.stage()
        async with self.Session() as s:
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == stage_node).values(status="live"))
            got = await s.scalar(
                sa.select(flow_queries.stage_node_status(models.Stage.id)).where(models.Stage.id == stage_id)
            )
        self.assertEqual("live", got)
