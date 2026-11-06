"""FlowNodeService.transition — the one writer of lifecycle node statuses (spec §5, §8.3, §9)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.enums import FlowNodeStatus as S
from shared.core.errors import ApiHTTPException
from shared.messaging.config import FLOW_NODE_STATE_CHANGED_ROUTING_KEY, TOURNAMENT_STATE_CHANGED_ROUTING_KEY
from src import schemas
from src.services.admin.tournament import tournament_service
from src.services.flow.lifecycle import flow_node_service
from src.services.tournament.flows import flows_service
from tests._flow_case import FlowCase
from tests._lol_grid import seed_lol_grid


class TransitionTests(FlowCase):
    async def _move(self, node_id: int, target: S) -> None:
        async with self.Session() as s:
            await flow_node_service.transition(s, node_id, target, actor=self.actor)
            await s.commit()

    async def _refused(self, node_id: int, target: S) -> str:
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as caught:
                await flow_node_service.transition(s, node_id, target, actor=self.actor)
        self.assertEqual(409, caught.exception.status_code)
        return caught.exception.detail[0]["code"]

    async def test_open_writes_status_started_at_and_derived_live(self) -> None:
        reg = await self.node("registration")
        await self._move(reg, S.OPEN)
        self.assertEqual("open", await self.node_status(reg))
        self.assertEqual(enums.TournamentStatus.LIVE, await self.tournament_status())
        async with self.Session() as s:
            started = await s.scalar(sa.select(models.FlowNode.started_at).where(models.FlowNode.id == reg))
        self.assertIsNotNone(started)

    async def test_matrix_refusal_is_invalid_node_transition(self) -> None:
        reg = await self.node("registration")
        self.assertEqual("invalid_node_transition", await self._refused(reg, S.CLOSED))

    async def test_formation_needs_final_input(self) -> None:
        reg = await self.node("registration", "open")
        form = await self.node("formation", config={"mode": "balancer"})
        await self.edge(reg, "participants", form, "players")
        self.assertEqual("input_not_final", await self._refused(form, S.FORMING))
        await self._move(reg, S.CLOSED)
        await self._move(form, S.FORMING)
        self.assertEqual("forming", await self.node_status(form))

    async def test_formation_completion_needs_teams(self) -> None:
        form = await self.node("formation", "forming", config={"mode": "manual"})
        self.assertEqual("formation_has_no_teams", await self._refused(form, S.COMPLETED))
        # A tournament-wide team (no formation node) is part of every formation's output (Decision 8).
        async with self.Session() as s:
            s.add(models.Team(name="T", balancer_name="T", tournament_id=self.tournament_id))
            await s.commit()
        await self._move(form, S.COMPLETED)
        self.assertEqual("completed", await self.node_status(form))

    async def test_reopening_formation_refused_once_downstream_started(self) -> None:
        stage_id, stage_node = await self.stage()
        # The formation is created after the stage: create_stage (Task 4) auto-wires only an existing single formation.
        form = await self.node("formation", "completed", config={"mode": "manual"})
        await self.edge(form, "teams", stage_node, "participants")
        async with self.Session() as s:
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == stage_node).values(status="ready"))
            await s.commit()
        self.assertEqual("downstream_started", await self._refused(form, S.FORMING))

    async def test_reopening_registration_refused_once_downstream_started(self) -> None:
        reg = await self.node("registration", "closed")
        form = await self.node("formation", "forming", config={"mode": "balancer"})
        await self.edge(reg, "participants", form, "players")
        self.assertEqual("downstream_started", await self._refused(reg, S.OPEN))

    async def test_completed_sink_completes_tournament_and_emits_both_events(self) -> None:
        stage_id, stage_node = await self.stage()
        async with self.Session() as s:
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == stage_node).values(status="live"))
            await s.execute(
                sa.update(models.Tournament)
                .where(models.Tournament.id == self.tournament_id)
                .values(status=enums.TournamentStatus.LIVE)
            )
            await s.commit()
        await self._move(stage_node, S.COMPLETED)
        self.assertEqual(enums.TournamentStatus.COMPLETED, await self.tournament_status())
        node_events = await self.outbox(FLOW_NODE_STATE_CHANGED_ROUTING_KEY)
        self.assertEqual(
            [(stage_node, "stage", "live", "completed")],
            [(e["node_id"], e["kind"], e["old_status"], e["new_status"]) for e in node_events],
        )
        state_events = await self.outbox(TOURNAMENT_STATE_CHANGED_ROUTING_KEY)
        self.assertEqual([("live", "completed")], [(e["old_status"], e["new_status"]) for e in state_events])
        async with self.Session() as s:
            finished = await s.scalar(
                sa.select(models.Tournament.is_finished).where(models.Tournament.id == self.tournament_id)
            )
        self.assertTrue(finished)

    async def test_no_tournament_event_when_derived_status_unchanged(self) -> None:
        a = await self.node("registration")
        b = await self.node("registration")
        await self._move(a, S.OPEN)
        await self._move(b, S.OPEN)
        self.assertEqual(1, len(await self.outbox(TOURNAMENT_STATE_CHANGED_ROUTING_KEY)))
        self.assertEqual(2, len(await self.outbox(FLOW_NODE_STATE_CHANGED_ROUTING_KEY)))

    async def test_moves_of_one_tournament_serialize_and_the_second_re_reads(self) -> None:
        reg = await self.node("registration", "closed")
        form = await self.node("formation", config={"mode": "balancer"})
        await self.edge(reg, "participants", form, "players")
        async with self.Session() as first, self.Session() as second:
            await flow_node_service.transition(first, reg, S.OPEN, actor=self.actor)
            # Without the tournament lock this passes its guard (the registration is still closed for it) and commits.
            blocked = asyncio.create_task(flow_node_service.transition(second, form, S.FORMING, actor=self.actor))
            done, _ = await asyncio.wait({blocked}, timeout=1)
            self.assertEqual(set(), done)
            await first.commit()
            with self.assertRaises(ApiHTTPException) as caught:
                await blocked
        self.assertEqual("input_not_final", caught.exception.detail[0]["code"])
        self.assertEqual("draft", await self.node_status(form))


class CreateTournamentFlowTests(FlowCase):
    async def test_new_tournament_gets_registration_to_formation(self) -> None:
        async with self.Session() as s:
            # An Overwatch workspace has no grid of its own; a League one is the cheapest to seed.
            grid_version_id = await seed_lol_grid(s, workspace_id=self.workspace_id, suffix=self.tag)
            created = await tournament_service.create_tournament(
                s,
                schemas.TournamentCreate(
                    workspace_id=self.workspace_id,
                    discipline="lol",
                    division_grid_version_id=grid_version_id,
                    name=f"{self.tag}-new",
                    team_formation="draft",
                    start_date=date(2026, 11, 5),
                    end_date=date(2026, 11, 6),
                ),
            )
            nodes = (
                await s.execute(
                    sa.select(models.FlowNode.kind, models.FlowNode.status, models.FlowNode.config)
                    .where(models.FlowNode.tournament_id == created.id)
                    .order_by(models.FlowNode.id)
                )
            ).all()
            edges = await s.scalar(
                sa.select(sa.func.count(models.FlowEdge.id)).where(models.FlowEdge.tournament_id == created.id)
            )
        self.assertEqual([("registration", "draft"), ("formation", "draft")], [(k, st) for k, st, _ in nodes])
        self.assertEqual("draft", nodes[1].config["mode"])
        self.assertEqual(1, edges)


class TournamentReadFlowNodesTests(FlowCase):
    async def test_flow_nodes_are_opt_in_lifecycle_and_leaderboard_only_with_their_schedule(self) -> None:
        reg = await self.node("registration", "open", name="Day 1")
        await self.node("filter", "pending", config={"mode": "top", "n": 2})
        board = await self.node("leaderboard", "pending")
        opens = datetime(2026, 11, 5, 10, tzinfo=UTC)
        async with self.Session() as s:
            s.add(models.FlowNodeSchedule(node_id=reg, phase="open", starts_at=opens))
            await s.commit()
        async with self.Session() as s:
            tournament = await s.get(models.Tournament, self.tournament_id)
            bare = await flows_service.to_pydantic(s, tournament, [])
            read = await flows_service.to_pydantic(s, tournament, ["flow_nodes"])
        self.assertEqual([], bare.flow_nodes)
        self.assertEqual(
            [(reg, "registration", "Day 1", "open"), (board, "leaderboard", "leaderboard", "pending")],
            [(n.id, n.kind, n.name, n.status) for n in read.flow_nodes],
        )
        self.assertEqual(
            [("open", opens, None)], [(e.phase, e.starts_at, e.ends_at) for e in read.flow_nodes[0].schedule]
        )

    async def test_a_formation_names_the_registration_nodes_feeding_it_newest_first(self) -> None:
        day1 = await self.node("registration", "closed", name="Day 1")
        day2 = await self.node("registration", "open", name="Day 2")
        teams = await self.node("formation", "draft", config={"mode": "balancer"})
        await self.edge(day1, "participants", teams, "players")
        await self.edge(day2, "participants", teams, "players")
        async with self.Session() as s:
            tournament = await s.get(models.Tournament, self.tournament_id)
            read = await flows_service.to_pydantic(s, tournament, ["flow_nodes"])
        self.assertEqual(
            {day1: [], day2: [], teams: [day2, day1]}, {n.id: n.pool_registration_node_ids for n in read.flow_nodes}
        )


class RegistrationOpenFilterTests(FlowCase):
    async def _listed(self) -> list[int]:
        params = schemas.TournamentPaginationSortSearchParams.from_query_params(
            schemas.TournamentPaginationSortSearchQueryParams(workspace_id=self.workspace_id, registration_open=True)
        )
        async with self.Session() as s:
            page = await flows_service.get_all(s, params)
        return [row.id for row in page.results]

    async def test_only_tournaments_with_an_open_or_check_in_registration_node_are_listed(self) -> None:
        reg = await self.node("registration", "draft")
        self.assertEqual([], await self._listed())
        for status in ("open", "check_in"):
            async with self.Session() as s:
                await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == reg).values(status=status))
                await s.commit()
            self.assertEqual([self.tournament_id], await self._listed(), status)
        async with self.Session() as s:
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == reg).values(status="closed"))
            await s.commit()
        self.assertEqual([], await self._listed())
