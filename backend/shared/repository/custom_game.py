from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from shared import models
from shared.repository.base import BaseRepository


class CustomGameRepository(BaseRepository[models.CustomGame]):
    #: Leaves the solver document in the database. It is the one heavy column a
    #: mix has -- an entry per balance option, megabytes once balanced -- and only
    #: the detail read and the writes that edit it look at it. ``raiseload`` turns
    #: a stray read into an error instead of an implicit async lazy load.
    WITHOUT_BALANCE_RESULT = (defer(models.CustomGame.balance_result_json, raiseload=True),)

    def __init__(self) -> None:
        super().__init__(models.CustomGame)

    async def list_for_workspace(self, session: AsyncSession, workspace_id: int) -> Sequence[models.CustomGame]:
        """Every mix of the workspace, newest first, without ``balance_result_json``."""
        result = await session.scalars(
            self.select()
            .where(self.model.workspace_id == workspace_id)
            .options(*self.WITHOUT_BALANCE_RESULT)
            .order_by(self.model.id.desc())
        )
        return result.all()


class CustomGamePlayerRepository(BaseRepository[models.CustomGamePlayer]):
    def __init__(self) -> None:
        super().__init__(models.CustomGamePlayer)

    async def list_for_game(self, session: AsyncSession, custom_game_id: int) -> Sequence[models.CustomGamePlayer]:
        result = await session.scalars(
            self.select()
            .where(self.model.custom_game_id == custom_game_id)
            .order_by(self.model.sort_order, self.model.id)
        )
        return result.all()

    async def delete_for_game(self, session: AsyncSession, custom_game_id: int) -> None:
        for row in await self.list_for_game(session, custom_game_id):
            await self.delete(session, row)


class CustomGameCoHostRepository:
    async def user_ids_for_game(self, session: AsyncSession, custom_game_id: int) -> list[int]:
        result = await session.scalars(
            sa.select(models.CustomGameCoHost.user_id).where(models.CustomGameCoHost.custom_game_id == custom_game_id)
        )
        return list(result.all())

    async def add(self, session: AsyncSession, custom_game_id: int, user_id: int) -> None:
        session.add(models.CustomGameCoHost(custom_game_id=custom_game_id, user_id=user_id))
        await session.flush()

    async def remove(self, session: AsyncSession, custom_game_id: int, user_id: int) -> None:
        await session.execute(
            sa.delete(models.CustomGameCoHost).where(
                models.CustomGameCoHost.custom_game_id == custom_game_id,
                models.CustomGameCoHost.user_id == user_id,
            )
        )
        await session.flush()


class CustomGamePlayerRoleRepository:
    async def roles_for_players(
        self,
        session: AsyncSession,
        custom_game_player_ids: Sequence[int],
    ) -> dict[int, list[str]]:
        if not custom_game_player_ids:
            return {}
        result = await session.scalars(
            sa.select(models.CustomGamePlayerRole)
            .where(models.CustomGamePlayerRole.custom_game_player_id.in_(custom_game_player_ids))
            .order_by(
                models.CustomGamePlayerRole.custom_game_player_id,
                models.CustomGamePlayerRole.priority,
            )
        )
        grouped: dict[int, list[str]] = {}
        for row in result.all():
            grouped.setdefault(row.custom_game_player_id, []).append(row.role)
        return grouped

    async def replace_for_player(
        self,
        session: AsyncSession,
        custom_game_player_id: int,
        roles: Sequence[str],
    ) -> None:
        await session.execute(
            sa.delete(models.CustomGamePlayerRole).where(
                models.CustomGamePlayerRole.custom_game_player_id == custom_game_player_id
            )
        )
        session.add_all(
            [
                models.CustomGamePlayerRole(
                    custom_game_player_id=custom_game_player_id,
                    role=role,
                    priority=priority,
                )
                for priority, role in enumerate(roles, start=1)
            ]
        )
        await session.flush()


class CustomGameTeamNameRepository:
    async def mapping_for_game(self, session: AsyncSession, custom_game_id: int) -> dict[int, str]:
        result = await session.execute(
            sa.select(models.CustomGameTeamName.team_index, models.CustomGameTeamName.name).where(
                models.CustomGameTeamName.custom_game_id == custom_game_id
            )
        )
        return dict(result.all())

    async def mapping_for_games(
        self, session: AsyncSession, custom_game_ids: Sequence[int]
    ) -> dict[int, dict[int, str]]:
        """``custom_game_id -> {team_index: name}`` for a whole mix list in one query.

        A mix with no custom names is absent from the result.
        """
        if not custom_game_ids:
            return {}
        result = await session.execute(
            sa.select(
                models.CustomGameTeamName.custom_game_id,
                models.CustomGameTeamName.team_index,
                models.CustomGameTeamName.name,
            ).where(models.CustomGameTeamName.custom_game_id.in_(custom_game_ids))
        )
        grouped: dict[int, dict[int, str]] = {}
        for custom_game_id, team_index, name in result.all():
            grouped.setdefault(custom_game_id, {})[team_index] = name
        return grouped

    async def set(
        self,
        session: AsyncSession,
        custom_game_id: int,
        team_index: int,
        name: str | None,
    ) -> None:
        current = await session.get(models.CustomGameTeamName, (custom_game_id, team_index))
        if name is None:
            if current is not None:
                await session.delete(current)
        elif current is None:
            session.add(
                models.CustomGameTeamName(
                    custom_game_id=custom_game_id,
                    team_index=team_index,
                    name=name,
                )
            )
        else:
            current.name = name
        await session.flush()
