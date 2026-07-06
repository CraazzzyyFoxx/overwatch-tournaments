from __future__ import annotations

import typing
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core.pagination import PaginationSortParams, PaginationSortSearchParams
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

    async def all(
        self,
        session: AsyncSession,
        params: PaginationSortSearchParams,
    ) -> tuple[Sequence[models.Hero], int]:
        """Paginated heroes — applies sort + search via `params`."""
        return await self.get_all(session, params)

    async def playtime(
        self,
        session: AsyncSession,
        *,
        user_id: int | typing.Literal["all"] | None = "all",
        tournament_id: int | None = None,
        workspace_id: int | None = None,
    ) -> Sequence[tuple[models.Hero, float]]:
        """Aggregated per-hero playtime share.

        Returns rows of `(Hero, playtime_share)` where the share is normalized
        across all returned heroes. Filters:

        - ``user_id``: a specific user id, or ``"all"`` / ``None`` for everyone.
        - ``tournament_id``: restrict to one tournament.
        - ``workspace_id``: restrict to one workspace.

        The caller is responsible for any sorting/pagination on the result —
        the dataset is intrinsically small (at most one row per hero).
        """
        narrow_to_user = user_id is not None and user_id != "all"

        playtime_filters = [
            models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
            models.MatchStatistics.value > 60,
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.isnot(None),
        ]
        if narrow_to_user:
            playtime_filters.append(models.MatchStatistics.user_id == user_id)

        playtime_cte = (
            sa.select(
                models.MatchStatistics.hero_id,
                sa.func.sum(models.MatchStatistics.value).label("playtime"),
            )
            .where(sa.and_(*playtime_filters))
            .group_by(models.MatchStatistics.hero_id)
        )

        if tournament_id is not None:
            playtime_cte = (
                playtime_cte.join(models.Match, models.Match.id == models.MatchStatistics.match_id)
                .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
                .where(models.Encounter.tournament_id == tournament_id)
            )

        if workspace_id is not None:
            if tournament_id is None:
                playtime_cte = playtime_cte.join(models.Match, models.Match.id == models.MatchStatistics.match_id).join(
                    models.Encounter, models.Encounter.id == models.Match.encounter_id
                )
            playtime_cte = playtime_cte.join(
                models.Tournament, models.Tournament.id == models.Encounter.tournament_id
            ).where(models.Tournament.workspace_id == workspace_id)

        playtime_cte = playtime_cte.cte("playtime_cte")

        overall_playtime = (
            sa.select(sa.func.sum(playtime_cte.c.playtime).label("total_playtime")).select_from(playtime_cte)
        ).scalar_subquery()

        query = (
            sa.select(
                models.Hero,
                (sa.func.sum(playtime_cte.c.playtime) / overall_playtime).label("playtime"),
            )
            .select_from(models.Hero)
            .join(playtime_cte, models.Hero.id == playtime_cte.c.hero_id)
            .group_by(models.Hero.id)
        )

        result = await session.execute(query)
        return result.all()  # type: ignore[return-value]


class GamemodeRepository(BaseRepository[models.Gamemode]):
    def __init__(self) -> None:
        super().__init__(models.Gamemode)

    async def get_by_name(self, session: AsyncSession, name: str) -> models.Gamemode | None:
        return await self.get_by(session, name=name)

    async def get_with_maps(self, session: AsyncSession, gamemode_id: int) -> models.Gamemode | None:
        return await self.get(session, gamemode_id, options=[selectinload(models.Gamemode.maps)])

    async def all(
        self,
        session: AsyncSession,
        params: PaginationSortSearchParams,
        *,
        with_maps: bool = False,
    ) -> tuple[Sequence[models.Gamemode], int]:
        """Paginated gamemodes — optionally eager-loads `Gamemode.maps`."""
        options = [selectinload(models.Gamemode.maps)] if with_maps else None
        return await self.get_all(session, params, options=options)


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
        with_gamemode: bool = False,
    ) -> models.Map | None:
        query = (
            sa.select(models.Map).join(models.Gamemode).where(models.Map.name == name, models.Gamemode.name == gamemode)
        )
        if with_gamemode:
            query = query.options(selectinload(models.Map.gamemode))
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def all(
        self,
        session: AsyncSession,
        params: PaginationSortParams | PaginationSortSearchParams,
        *,
        with_gamemode: bool = False,
    ) -> tuple[Sequence[models.Map], int]:
        """Paginated maps — optionally eager-loads `Map.gamemode`."""
        options = [selectinload(models.Map.gamemode)] if with_gamemode else None
        return await self.get_all(session, params, options=options)
