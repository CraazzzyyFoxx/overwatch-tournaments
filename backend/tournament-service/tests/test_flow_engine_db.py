"""FlowEngine.recompute on the test Postgres (spec §5.1-5.3 outputs, §5.4 filter state, §8.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from shared.core import enums
from shared.models.balancer.balance import BalancerBalance, BalancerTeam
from shared.models.registration.registration import Registration
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.player_standing import PlayerStanding
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.standings import Standing
from shared.models.tournament.team import Team
from shared.testing.factories import add_entry
from shared.tests.encounter_writer_case import EncounterWriterCase
from src.services.flow.engine import flow_engine

T0 = datetime(2026, 11, 1, tzinfo=UTC)


class FlowEngineTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        t, ids = self.ids["t"], self.ids
        async with self.Session() as s:
            stage = Stage(
                tournament_id=t,
                scoring_rule_id=ids["rule"],
                name="Groups",
                stage_type=enums.StageType.ROUND_ROBIN,
                order=0,
            )
            s.add(stage)
            await s.flush()
            a = StageItem(stage_id=stage.id, name="A", type=enums.StageItemType.GROUP, order=0)
            b = StageItem(stage_id=stage.id, name="B", type=enums.StageItemType.GROUP, order=1)
            s.add_all([a, b])
            await s.flush()
            self.stage_id, self.a, self.b = stage.id, a.id, b.id
            for team, item, position, points in (
                ("team0", a, 1, 6.0),
                ("team1", a, 2, 3.0),
                ("team2", b, 1, 6.0),
                ("team3", b, 2, 0.0),
            ):
                s.add(
                    Standing(
                        tournament_id=t,
                        stage_id=stage.id,
                        stage_item_id=item.id,
                        team_id=ids[team],
                        position=position,
                        matches=2,
                        points=points,
                    )
                )
            registrations = [
                Registration(tournament_id=t, workspace_member_id=ids[m]) for m in ("m0", "m1", "m2", "m3")
            ]
            registrations.append(Registration(tournament_id=t, workspace_member_id=None))
            s.add_all(registrations)
            await s.flush()
            self.reg = self._node("registration", "Registration", "open")
            self.form = self._node("formation", "Teams", "completed", {"mode": "balancer"})
            self.stage = self._node("stage", "Groups", "live", stage_id=stage.id)
            self.top = self._node(
                "filter", "Top 1 per group", "pending", {"mode": "per_item_top", "n": 1, "per_item": {}}
            )
            s.add_all([self.reg, self.form, self.stage, self.top])
            await s.flush()
            for registration, fields in zip(
                registrations,
                (
                    {"status": "approved", "reviewed_at": T0 + timedelta(hours=2)},
                    {"status": "approved", "reviewed_at": T0 + timedelta(hours=1)},
                    {"status": "pending"},
                    {"status": "approved", "checked_in": True},
                    {"status": "approved"},
                ),
                strict=True,
            ):
                await add_entry(s, self.reg.id, registration.id, **fields)
            s.add_all(
                [
                    self._edge(self.reg, "participants", self.form, "players"),
                    self._edge(self.form, "teams", self.stage, "participants"),
                    self._edge(self.stage, "ranking", self.top, "ranking"),
                ]
            )
            await s.commit()

    def _node(self, kind, name, status, config=None, **kw) -> FlowNode:
        return FlowNode(tournament_id=self.ids["t"], kind=kind, name=name, status=status, config=config or {}, **kw)

    def _edge(self, source, source_port, target, target_port) -> FlowEdge:
        return FlowEdge(
            tournament_id=self.ids["t"],
            source_node_id=source.id,
            source_port=source_port,
            target_node_id=target.id,
            target_port=target_port,
        )

    async def _recompute(self):
        async with self.Session() as s:
            report = await flow_engine.recompute(s, self.ids["t"])
            await s.commit()
            return report

    async def _results(self, node: FlowNode) -> list[tuple]:
        async with self.Session() as s:
            rows = await s.execute(
                sa.select(
                    FlowNodeResult.rank,
                    FlowNodeResult.workspace_member_id,
                    FlowNodeResult.team_id,
                    FlowNodeResult.item_rank,
                    FlowNodeResult.state,
                )
                .where(FlowNodeResult.node_id == node.id)
                .order_by(FlowNodeResult.rank)
            )
            return [tuple(r) for r in rows]

    async def _set(self, node: FlowNode, **values) -> None:
        async with self.Session() as s:
            await s.execute(sa.update(FlowNode).where(FlowNode.id == node.id).values(**values))
            await s.commit()

    async def _status(self, node: FlowNode) -> str:
        async with self.Session() as s:
            return await s.scalar(sa.select(FlowNode.status).where(FlowNode.id == node.id))

    async def test_registration_emits_approved_members_by_approval_time(self) -> None:
        await self._recompute()
        m = self.ids
        self.assertEqual(
            [
                (1, m["m1"], None, None, "tentative"),
                (2, m["m0"], None, None, "tentative"),
                (3, m["m3"], None, None, "tentative"),
            ],
            await self._results(self.reg),
        )

    async def test_a_checked_in_closed_registration_is_final_and_keeps_only_checked_in(self) -> None:
        await self._set(self.reg, config={"check_in": True}, status="closed")
        await self._recompute()
        self.assertEqual([(1, self.ids["m3"], None, None, "final")], await self._results(self.reg))

    async def test_formation_emits_the_tournaments_teams(self) -> None:
        await self._recompute()
        expected = [(i + 1, None, self.ids[f"team{i}"], None, "final") for i in range(4)]
        self.assertEqual(expected, await self._results(self.form))

    async def test_formation_emits_its_own_and_tournament_wide_teams_in_balance_order(self) -> None:
        ids = self.ids
        async with self.Session() as s:
            other = self._node("formation", "Other", "forming", {"mode": "manual"})
            s.add(other)
            await s.flush()
            for team, node in (("team0", self.form.id), ("team1", self.form.id), ("team2", other.id), ("team3", None)):
                await s.execute(sa.update(Team).where(Team.id == ids[team]).values(formation_node_id=node))
            balance = BalancerBalance(tournament_id=ids["t"], formation_node_id=self.form.id, result_json={})
            s.add(balance)
            await s.flush()
            s.add_all(
                BalancerTeam(
                    balance_id=balance.id,
                    name=team,
                    balancer_name=team,
                    avg_sr=2000,
                    total_sr=4000,
                    sort_order=order,
                    exported_team_id=ids[team],
                )
                for order, team in enumerate(("team1", "team0"))
            )
            await s.commit()
        await self._recompute()
        rows = await self._results(self.form)
        # The balance's order first, the node-less team after it, the other formation's team not at all.
        self.assertEqual([ids["team1"], ids["team0"], ids["team3"]], [row[2] for row in rows])

    async def test_stage_ranking_feeds_a_per_group_filter_until_the_stage_completes(self) -> None:
        await self._recompute()
        ids = self.ids
        self.assertEqual(
            [
                (1, None, ids["team0"], 1, "tentative"),
                (2, None, ids["team2"], 1, "tentative"),
                (3, None, ids["team1"], 2, "tentative"),
                (4, None, ids["team3"], 2, "tentative"),
            ],
            await self._results(self.stage),
        )
        self.assertEqual([ids["team0"], ids["team2"]], [r[2] for r in await self._results(self.top)])
        self.assertEqual("tentative", await self._status(self.top))

        await self._set(self.stage, status="completed")
        await self._recompute()
        self.assertEqual(
            ("final", {"final"}), (await self._status(self.top), {r[4] for r in await self._results(self.top)})
        )

    async def test_recompute_is_stable_and_updates_rows_in_place(self) -> None:
        self.assertTrue((await self._recompute()).changed)

        async def ids_by_team():
            async with self.Session() as s:
                return dict(
                    (
                        await s.execute(
                            sa.select(FlowNodeResult.team_id, FlowNodeResult.id).where(
                                FlowNodeResult.node_id == self.stage.id
                            )
                        )
                    ).all()
                )

        before = await ids_by_team()
        self.assertFalse((await self._recompute()).changed)
        async with self.Session() as s:
            await s.execute(sa.update(Standing).where(Standing.team_id == self.ids["team0"]).values(position=2))
            await s.execute(sa.update(Standing).where(Standing.team_id == self.ids["team1"]).values(position=1))
            await s.commit()
        self.assertIn(self.stage.id, (await self._recompute()).changed_node_ids)
        self.assertEqual(before, await ids_by_team(), "rows are updated in place, never re-inserted")

    async def test_individual_swiss_ranks_qualified_players_first(self) -> None:
        t, m = self.ids["t"], self.ids
        async with self.Session() as s:
            swiss = Stage(
                tournament_id=t,
                scoring_rule_id=m["rule"],
                name="Swiss",
                stage_type=enums.StageType.INDIVIDUAL_SWISS,
                order=1,
            )
            s.add(swiss)
            await s.flush()
            s.add_all(
                [
                    PlayerStanding(
                        tournament_id=t,
                        stage_id=swiss.id,
                        workspace_member_id=m["m2"],
                        display_name="c",
                        role="dps",
                        start_rank=1,
                        rank=1,
                        points=5,
                        position=1,
                        is_qualified=False,
                    ),
                    PlayerStanding(
                        tournament_id=t,
                        stage_id=swiss.id,
                        workspace_member_id=m["m1"],
                        display_name="b",
                        role="dps",
                        start_rank=1,
                        rank=1,
                        points=4,
                        position=2,
                        is_qualified=True,
                    ),
                    PlayerStanding(
                        tournament_id=t,
                        stage_id=swiss.id,
                        workspace_member_id=m["m0"],
                        display_name="a",
                        role="tank",
                        start_rank=1,
                        rank=1,
                        points=3,
                        position=1,
                        is_qualified=True,
                    ),
                ]
            )
            node = self._node("stage", "Swiss", "live", stage_id=swiss.id)
            s.add(node)
            await s.commit()
        await self._recompute()
        self.assertEqual([m["m0"], m["m1"], m["m2"]], [r[1] for r in await self._results(node)])

    async def test_a_filter_whose_input_has_no_rows_is_pending(self) -> None:
        async with self.Session() as s:
            empty = Stage(
                tournament_id=self.ids["t"],
                scoring_rule_id=self.ids["rule"],
                name="Empty",
                stage_type=enums.StageType.ROUND_ROBIN,
                order=1,
            )
            s.add(empty)
            await s.flush()
            node = self._node("stage", "Empty", "draft", stage_id=empty.id)
            top = self._node("filter", "Top 1", "pending", {"mode": "top", "n": 1})
            s.add_all([node, top])
            await s.flush()
            s.add(self._edge(node, "ranking", top, "ranking"))
            await s.commit()
        await self._recompute()
        self.assertEqual(("pending", []), (await self._status(top), await self._results(top)))

    async def test_a_team_listed_twice_in_a_stage_appears_once(self) -> None:
        async with self.Session() as s:
            s.add(
                Standing(
                    tournament_id=self.ids["t"],
                    stage_id=self.stage_id,
                    stage_item_id=self.b,
                    team_id=self.ids["team0"],
                    position=3,
                    matches=1,
                    points=0,
                )
            )
            await s.commit()
        await self._recompute()
        teams = [r[2] for r in await self._results(self.stage)]
        self.assertEqual((4, 1), (len(teams), teams.count(self.ids["team0"])))

    async def test_a_result_without_a_breakdown_is_stored_as_sql_null(self) -> None:
        await self._recompute()
        async with self.Session() as s:
            rows = sa.select(sa.func.count()).where(FlowNodeResult.node_id == self.reg.id)
            total = await s.scalar(rows)
            stored = await s.scalar(rows.where(FlowNodeResult.breakdown.is_(None)))
        self.assertGreater(total, 0)
        self.assertEqual(total, stored)
