"""A by-role aggregate on the test Postgres: each roster role ranks apart, through the leaderboard into
``participant_result``. Needs the test Postgres."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from shared.core import enums
from shared.models.identity.user import User
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.participant_result import ParticipantResult
from shared.models.tournament.player_role import PlayerRole
from shared.models.tournament.player_standing import PlayerStanding
from shared.models.tournament.stage import Stage
from shared.models.tournament.standings import Standing
from shared.models.tournament.team import Player
from shared.models.tournament.tournament import Tournament
from shared.repository.roles import CatalogRoleRepository
from src.services.flow.engine import flow_engine
from tests._encounter_layer import EncounterLayerCase

DONE = datetime(2026, 1, 8, tzinfo=UTC)
#: Day 1 seats teams 0-1, day 2 teams 2-3. ``(member, team index, role)``: member 0 tanks on day 1 and supports on day 2.
ROSTER = [(0, 0, "tank"), (1, 1, "tank"), (2, 1, "support"), (1, 2, "tank"), (3, 2, "support"), (0, 3, "support")]


class FlowByRoleDbTests(EncounterLayerCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            users = [User(name=f"{self.workspace_id}-role-{i}") for i in range(4)]
            s.add_all(users)
            await s.flush()
            self.addAsyncCleanup(self._drop_users, [u.id for u in users])
            members = [WorkspaceMember(workspace_id=self.workspace_id, player_id=u.id) for u in users]
            s.add_all(members)
            await s.flush()
            self.members = [m.id for m in members]
            roles = {
                code: await CatalogRoleRepository().resolve(
                    s, discipline="overwatch", workspace_id=self.workspace_id, dimension="player_role", code=code
                )
                for code in ("tank", "support")
            }
            for member, team, code in ROSTER:
                player = Player(
                    tournament_id=self.tournament_id,
                    team_id=self.teams[team],
                    workspace_member_id=self.members[member],
                    name=f"p{member}",
                    rank=3000,
                )
                s.add(player)
                await s.flush()
                role = roles[code]
                s.add(PlayerRole(player_id=player.id, dimension_id=role.dimension_id, role_id=role.id))

            days = [
                await self._stage(s, "Day 1", [(0, 6.0), (1, 3.0)]),
                await self._stage(s, "Day 2", [(2, 5.0), (3, 1.0)]),
            ]
            self.agg = FlowNode(
                tournament_id=self.tournament_id,
                kind="aggregate",
                name="Season",
                status="pending",
                config={"unit": "players", "score": {"preset": "stage_points"}, "mode": "sum_all", "by_role": True},
            )
            self.board = FlowNode(tournament_id=self.tournament_id, kind="leaderboard", name="Table", status="pending")
            s.add_all([self.agg, self.board])
            await s.flush()
            s.add_all(
                [
                    *(self._edge(day, "ranking", self.agg, "inputs") for day in days),
                    self._edge(self.agg, "ranking", self.board, "ranking"),
                ]
            )
            await s.execute(sa.update(Tournament).where(Tournament.id == self.tournament_id).values(is_finished=True))
            await s.commit()

    async def _stage(self, s, name: str, standings: list[tuple[int, float]]) -> FlowNode:
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
            status="completed",
            stage_id=stage.id,
            completed_at=DONE,
        )
        s.add(node)
        for position, (team, points) in enumerate(standings, 1):
            s.add(
                Standing(
                    tournament_id=self.tournament_id,
                    stage_id=stage.id,
                    team_id=self.teams[team],
                    position=position,
                    matches=1,
                    points=points,
                )
            )
        await s.flush()
        return node

    def _edge(self, source: FlowNode, source_port: str, target: FlowNode, target_port: str) -> FlowEdge:
        return FlowEdge(
            tournament_id=self.tournament_id,
            source_node_id=source.id,
            source_port=source_port,
            target_node_id=target.id,
            target_port=target_port,
        )

    async def _drop_users(self, ids: list[int]) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(User).where(User.id.in_(ids)))
            await s.commit()

    async def _rows(self, node: FlowNode) -> list[tuple[str | None, int, int, float]]:
        """``(role, rank, member index, score)`` in role, then rank order."""
        async with self.Session() as s:
            rows = await s.execute(
                sa.select(
                    FlowNodeResult.role, FlowNodeResult.rank, FlowNodeResult.workspace_member_id, FlowNodeResult.score
                )
                .where(FlowNodeResult.node_id == node.id, FlowNodeResult.port == "ranking")
                .order_by(FlowNodeResult.role, FlowNodeResult.rank)
            )
            return [(role, rank, self.members.index(member), score) for role, rank, member, score in rows]

    async def test_every_role_ranks_apart_and_a_member_keeps_their_best_role_place(self) -> None:
        async with self.Session() as s:
            await flow_engine.recompute(s, self.tournament_id)
            await s.commit()

        # Member 0: 6 as a tank on day 1, 1 as a support on day 2 -- two lines that never add up.
        expected = [
            ("support", 1, 3, 5.0),
            ("support", 2, 2, 3.0),
            ("support", 3, 0, 1.0),
            ("tank", 1, 1, 8.0),
            ("tank", 2, 0, 6.0),
        ]
        self.assertEqual(expected, await self._rows(self.agg))
        self.assertEqual(expected, await self._rows(self.board))

        async with self.Session() as s:
            [breakdown] = await s.scalars(
                sa.select(FlowNodeResult.breakdown).where(
                    FlowNodeResult.node_id == self.agg.id,
                    FlowNodeResult.workspace_member_id == self.members[0],
                    FlowNodeResult.role == "tank",
                )
            )
            placements = await s.execute(
                sa.select(
                    ParticipantResult.workspace_member_id, ParticipantResult.placement, ParticipantResult.field_size
                ).where(ParticipantResult.tournament_id == self.tournament_id)
            )
        self.assertEqual([("tank", self.teams[0])], [(e["role"], e["team_id"]) for e in breakdown])
        # Placement inside the member's best role, the field being that role's ranking.
        self.assertEqual(
            {(0, 2, 2), (1, 1, 2), (2, 2, 3), (3, 1, 3)},
            {(self.members.index(member), place, field) for member, place, field in placements},
        )

    async def test_an_individual_swiss_day_scores_the_role_its_standing_froze(self) -> None:
        async with self.Session() as s:
            stage = Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name="Day 3",
                stage_type=enums.StageType.INDIVIDUAL_SWISS,
                order=6,
            )
            s.add(stage)
            await s.flush()
            day = FlowNode(
                tournament_id=self.tournament_id,
                kind="stage",
                name="Day 3",
                status="completed",
                stage_id=stage.id,
                completed_at=DONE,
            )
            s.add(day)
            # Member 2 supports in the team days but tanks in this one.
            s.add(
                PlayerStanding(
                    tournament_id=self.tournament_id,
                    stage_id=stage.id,
                    workspace_member_id=self.members[2],
                    display_name="p2",
                    role="tank",
                    start_rank=3000,
                    rank=3000,
                    points=4.0,
                    position=1,
                )
            )
            await s.flush()
            s.add(self._edge(day, "ranking", self.agg, "inputs"))
            await s.commit()
        async with self.Session() as s:
            await flow_engine.recompute(s, self.tournament_id)
            await s.commit()

        rows = await self._rows(self.agg)
        self.assertEqual([(1, 8.0), (0, 6.0), (2, 4.0)], [(m, score) for role, _, m, score in rows if role == "tank"])
        self.assertIn(("support", 2, 2, 3.0), rows)
