from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.repository.base import BaseRepository


class HeroRepository(BaseRepository[models.Hero]):
    def __init__(self) -> None:
        super().__init__(models.Hero)

    async def get_by_name(self, session: AsyncSession, name: str) -> models.Hero | None:
        return await self.get_by(session, name=name)

    async def list_by_role(
        self,
        session: AsyncSession,
        role: str | None = None,
    ) -> Sequence[models.Hero]:
        query = sa.select(models.Hero)
        if role is not None:
            query = query.where(models.Hero.type == role)
        result = await session.execute(query.order_by(models.Hero.name.asc()))
        return result.scalars().all()


class GamemodeRepository(BaseRepository[models.Gamemode]):
    def __init__(self) -> None:
        super().__init__(models.Gamemode)

    async def get_by_name(self, session: AsyncSession, name: str) -> models.Gamemode | None:
        return await self.get_by(session, name=name)


class MapRepository(BaseRepository[models.Map]):
    def __init__(self) -> None:
        super().__init__(models.Map)

    async def get_with_gamemode(self, session: AsyncSession, map_id: int) -> models.Map | None:
        return await self.get(session, map_id, options=[selectinload(models.Map.gamemode)])

    async def get_by_name(
        self,
        session: AsyncSession,
        name: str,
        *,
        with_gamemode: bool = False,
    ) -> models.Map | None:
        options = [selectinload(models.Map.gamemode)] if with_gamemode else None
        return await self.get_by(session, options=options, name=name)

    async def get_by_name_and_gamemode(
        self,
        session: AsyncSession,
        *,
        name: str,
        gamemode: str,
    ) -> models.Map | None:
        result = await session.execute(
            sa.select(models.Map)
            .join(models.Gamemode)
            .where(models.Map.name == name, models.Gamemode.name == gamemode)
        )
        return result.scalar_one_or_none()
