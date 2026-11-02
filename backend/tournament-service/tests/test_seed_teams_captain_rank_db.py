"""``seed_teams(mode="captain_rank")``: seed 1 is the team whose captain's own roster row ranks highest."""

from __future__ import annotations

import sqlalchemy as sa

from shared.models.identity.user import User
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament.stage import StageItemInput
from shared.models.tournament.team import Player, Team
from src.services.admin.stage import stage_service
from tests._encounter_layer import EncounterLayerCase


class SeedByCaptainRankTests(EncounterLayerCase):
    async def _roster(self, team_id: int, captain_rank: int, teammate_rank: int) -> None:
        """A captain and a stronger-or-weaker teammate; only the captain's rank may count."""
        users: list[int] = []
        async with self.Session() as s:
            for kind, rank in (("captain", captain_rank), ("mate", teammate_rank)):
                user = User(name=f"seed-{team_id}-{kind}")
                s.add(user)
                await s.flush()
                users.append(user.id)
                member = WorkspaceMember(workspace_id=self.workspace_id, player_id=user.id)
                s.add(member)
                await s.flush()
                s.add(
                    Player(
                        name=user.name,
                        rank=rank,
                        tournament_id=self.tournament_id,
                        team_id=team_id,
                        workspace_member_id=member.id,
                    )
                )
                if kind == "captain":
                    await s.flush()
                    await s.execute(sa.update(Team).where(Team.id == team_id).values(captain_id=user.id))
            await s.commit()
        self.addAsyncCleanup(self._drop_users, users)

    async def _drop_users(self, users: list[int]) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(User).where(User.id.in_(users)))
            await s.commit()

    async def test_strongest_captain_takes_slot_one(self) -> None:
        a, b, c = self.teams[:3]
        # Team averages would put a first (its mate is rated 9000); the captains' own ranks put b, c, a.
        await self._roster(a, captain_rank=10, teammate_rank=9000)
        await self._roster(b, captain_rank=30, teammate_rank=1)
        await self._roster(c, captain_rank=20, teammate_rank=1)

        async with self.Session() as s:
            await stage_service.seed_teams(s, self.stage_id, [a, b, c], mode="captain_rank")

        async with self.Session() as s:
            slots = (
                (
                    await s.execute(
                        sa.select(StageItemInput.team_id)
                        .where(StageItemInput.stage_item_id == self.item_id)
                        .order_by(StageItemInput.slot)
                    )
                )
                .scalars()
                .all()
            )
        self.assertEqual([b, c, a], list(slots))
