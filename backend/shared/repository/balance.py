from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.repository.base import BaseRepository


class BalancerTournamentConfigRepository(BaseRepository[models.BalancerTournamentConfig]):
    def __init__(self) -> None:
        super().__init__(models.BalancerTournamentConfig)

    async def get_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.BalancerTournamentConfig | None:
        return await self.get_by(session, tournament_id=tournament_id)


class WorkspaceBalancerConfigRepository(BaseRepository[models.WorkspaceBalancerConfig]):
    def __init__(self) -> None:
        super().__init__(models.WorkspaceBalancerConfig)

    async def get_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> models.WorkspaceBalancerConfig | None:
        return await self.get_by(session, workspace_id=workspace_id)


class UserBalancerConfigRepository(BaseRepository[models.UserBalancerConfig]):
    def __init__(self) -> None:
        super().__init__(models.UserBalancerConfig)

    async def get_by_user(
        self,
        session: AsyncSession,
        user_id: int,
    ) -> models.UserBalancerConfig | None:
        return await self.get_by(session, user_id=user_id)


class BalancerBalanceRepository(BaseRepository[models.BalancerBalance]):
    def __init__(self) -> None:
        super().__init__(models.BalancerBalance)

    async def get_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        with_teams: bool = True,
    ) -> models.BalancerBalance | None:
        query = self.select().where(self.model.tournament_id == tournament_id)
        if with_teams:
            query = query.options(selectinload(self.model.teams))
        return await session.scalar(query)

    async def get_for_export(self, session: AsyncSession, balance_id: int) -> models.BalancerBalance | None:
        return await self.get(
            session,
            balance_id,
            options=[selectinload(self.model.teams), selectinload(self.model.variants)],
        )

    async def get_workspace_id(self, session: AsyncSession, balance_id: int) -> int | None:
        return await session.scalar(
            sa.select(sa.func.coalesce(self.model.workspace_id, models.Tournament.workspace_id))
            .join(models.Tournament, models.Tournament.id == self.model.tournament_id)
            .where(self.model.id == balance_id)
        )


class BalancerTeamRepository(BaseRepository[models.BalancerTeam]):
    def __init__(self) -> None:
        super().__init__(models.BalancerTeam)

    async def list_for_balance(self, session: AsyncSession, balance_id: int) -> Sequence[models.BalancerTeam]:
        result = await session.scalars(self.select().where(self.model.balance_id == balance_id))
        return result.all()

    async def delete_for_balance(self, session: AsyncSession, balance_id: int) -> None:
        await session.execute(sa.delete(self.model).where(self.model.balance_id == balance_id))


class BalancerBalanceVariantRepository(BaseRepository[models.BalancerBalanceVariant]):
    def __init__(self) -> None:
        super().__init__(models.BalancerBalanceVariant)

    async def delete_for_balance(self, session: AsyncSession, balance_id: int) -> None:
        await session.execute(sa.delete(self.model).where(self.model.balance_id == balance_id))


class BalancerTeamSlotRepository(BaseRepository[models.BalancerTeamSlot]):
    def __init__(self) -> None:
        super().__init__(models.BalancerTeamSlot)
