"""The flow engine keeps ``participant_result`` in step with a finished tournament's leaderboard (spec §4.7). Needs the
test Postgres."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import sqlalchemy as sa

from shared.core import enums
from shared.models.identity.user import User
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament.flow import FlowEdge, FlowNode
from shared.models.tournament.participant_result import ParticipantResult
from shared.models.tournament.stage import Stage
from shared.models.tournament.standings import Standing
from shared.models.tournament.team import Player
from shared.models.tournament.tournament import Tournament
from src.services.flow.engine import flow_engine
from tests._encounter_layer import EncounterLayerCase


class FlowParticipantResultDbTests(EncounterLayerCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            stage = Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name="Groups",
                stage_type=enums.StageType.ROUND_ROBIN,
                order=5,
            )
            s.add(stage)
            await s.flush()
            stage_node = FlowNode(
                tournament_id=self.tournament_id, kind="stage", name="Groups", status="completed", stage_id=stage.id
            )
            board = FlowNode(tournament_id=self.tournament_id, kind="leaderboard", name="Final", status="pending")
            s.add_all([stage_node, board])
            await s.flush()
            s.add(
                FlowEdge(
                    tournament_id=self.tournament_id,
                    source_node_id=stage_node.id,
                    source_port="ranking",
                    target_node_id=board.id,
                    target_port="ranking",
                )
            )
            users = [User(name=f"{self.workspace_id}-{i}") for i in range(2)]
            s.add_all(users)
            await s.flush()
            self.addAsyncCleanup(self._drop_users, [u.id for u in users])
            members = [WorkspaceMember(workspace_id=self.workspace_id, player_id=u.id) for u in users]
            s.add_all(members)
            await s.flush()
            self.members = [m.id for m in members]
            for member, team in zip(self.members, self.teams, strict=False):
                s.add(
                    Player(
                        tournament_id=self.tournament_id,
                        team_id=team,
                        workspace_member_id=member,
                        name=f"p{member}",
                        rank=3000,
                    )
                )
            await s.execute(sa.update(Tournament).where(Tournament.id == self.tournament_id).values(is_finished=True))
            self.stage_id_of_groups = stage.id
            await s.commit()
        await self._standings(6.0, 3.0)

    async def _drop_users(self, ids: list[int]) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(User).where(User.id.in_(ids)))
            await s.commit()

    async def _standings(self, first: float, second: float) -> None:
        """Team 0 and team 1 ranked by their points."""
        async with self.Session() as s:
            await s.execute(sa.delete(Standing).where(Standing.stage_id == self.stage_id_of_groups))
            for team, points in zip(self.teams, (first, second), strict=False):
                s.add(
                    Standing(
                        tournament_id=self.tournament_id,
                        stage_id=self.stage_id_of_groups,
                        team_id=team,
                        position=1 if points == max(first, second) else 2,
                        matches=1,
                        points=points,
                    )
                )
            await s.commit()

    async def _recompute(self) -> bool:
        async with self.Session() as s:
            report = await flow_engine.recompute(s, self.tournament_id)
            await s.commit()
            return report.changed

    async def _placements(self) -> dict[int, int | None]:
        async with self.Session() as s:
            rows = await s.execute(
                sa.select(ParticipantResult.workspace_member_id, ParticipantResult.placement).where(
                    ParticipantResult.tournament_id == self.tournament_id
                )
            )
            return dict(rows.all())

    async def test_engine_rewrites_results_when_the_leaderboard_moves(self) -> None:
        await self._recompute()
        self.assertEqual({self.members[0]: 1, self.members[1]: 2}, await self._placements())

        await self._standings(3.0, 6.0)
        await self._recompute()
        self.assertEqual({self.members[0]: 2, self.members[1]: 1}, await self._placements())

        with patch("src.services.flow.engine.write_participant_results", new=AsyncMock()) as writer:
            self.assertFalse(await self._recompute())
        self.assertEqual(0, writer.await_count)
