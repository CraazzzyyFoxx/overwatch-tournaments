"""Public flow reads carry display names for the participants of their results (Table tab, §13.2)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from shared.models.identity.user import User
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament.flow import FlowNodeResult
from shared.models.tournament.team import Team
from src.services.flow.service import flow_service
from tests._flow_case import FlowCase


class ParticipantNamesTests(FlowCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        tag = uuid.uuid4().hex[:8]
        async with self.Session() as s:
            named, plain = User(name=f"named-{tag}"), User(name=f"plain-{tag}")
            s.add_all([named, plain])
            await s.flush()
            self.addAsyncCleanup(self._drop_users, [named.id, plain.id])
            m1 = WorkspaceMember(workspace_id=self.workspace_id, player_id=named.id, display_name="Shown Name")
            m2 = WorkspaceMember(workspace_id=self.workspace_id, player_id=plain.id)
            team = Team(tournament_id=self.tournament_id, name="Red", balancer_name="Red")
            s.add_all([m1, m2, team])
            await s.flush()
            self.m1, self.m2, self.team, self.plain_name = m1.id, m2.id, team.id, plain.name
            await s.commit()
        board = await self.node("leaderboard", "tentative")
        teams = await self.node("filter", "tentative", config={"mode": "top", "n": 1})
        async with self.Session() as s:
            s.add_all(
                [
                    FlowNodeResult(
                        node_id=board, port="ranking", rank=1, workspace_member_id=self.m1, state="tentative"
                    ),
                    FlowNodeResult(
                        node_id=board, port="ranking", rank=2, workspace_member_id=self.m2, state="tentative"
                    ),
                    FlowNodeResult(node_id=teams, port="passed", rank=1, team_id=self.team, state="tentative"),
                ]
            )
            await s.commit()

    async def _drop_users(self, ids: list[int]) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(User).where(User.id.in_(ids)))
            await s.commit()

    async def test_members_use_display_name_then_user_name_and_teams_their_name(self) -> None:
        async with self.Session() as s:
            read = await flow_service.get_read(s, self.tournament_id)
        self.assertEqual(
            [(self.m1, None, "Shown Name"), (self.m2, None, self.plain_name), (None, self.team, "Red")],
            [(p.workspace_member_id, p.team_id, p.name) for p in read.participants],
        )

    async def test_the_admin_read_carries_the_same_names(self) -> None:
        async with self.Session() as s:
            read = await flow_service.get_admin_read(s, self.tournament_id)
        self.assertEqual(3, len(read.participants))
