from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.repository.base import BaseRepository


class TournamentRepository(BaseRepository[models.Tournament]):
    def __init__(self) -> None:
        super().__init__(models.Tournament)

    async def get_by_number_and_league(
        self,
        session: AsyncSession,
        *,
        number: int,
        league: str | None,
    ) -> models.Tournament | None:
        return await self.get_by(session, number=number, league=league)

    async def get_by_name(self, session: AsyncSession, name: str) -> models.Tournament | None:
        return await self.get_by(session, name=name)

    async def list_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> Sequence[models.Tournament]:
        result = await session.execute(
            sa.select(models.Tournament)
            .where(models.Tournament.workspace_id == workspace_id)
            .order_by(models.Tournament.id.desc())
        )
        return result.scalars().all()


class StageRepository(BaseRepository[models.Stage]):
    def __init__(self) -> None:
        super().__init__(models.Stage)

    async def list_by_tournament(self, session: AsyncSession, tournament_id: int) -> Sequence[models.Stage]:
        result = await session.execute(
            sa.select(models.Stage)
            .where(models.Stage.tournament_id == tournament_id)
            .order_by(models.Stage.order.asc(), models.Stage.id.asc())
        )
        return result.scalars().all()


class StageItemRepository(BaseRepository[models.StageItem]):
    def __init__(self) -> None:
        super().__init__(models.StageItem)

    async def list_by_stage(self, session: AsyncSession, stage_id: int) -> Sequence[models.StageItem]:
        result = await session.execute(
            sa.select(models.StageItem)
            .where(models.StageItem.stage_id == stage_id)
            .order_by(models.StageItem.order.asc(), models.StageItem.id.asc())
        )
        return result.scalars().all()


class TeamRepository(BaseRepository[models.Team]):
    def __init__(self) -> None:
        super().__init__(models.Team)

    async def get_by_name_and_tournament(
        self,
        session: AsyncSession,
        *,
        name: str,
        tournament_id: int,
    ) -> models.Team | None:
        return await self.get_by(session, name=name, tournament_id=tournament_id)

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Sequence[models.Team]:
        result = await session.execute(
            sa.select(models.Team)
            .options(selectinload(models.Team.players))
            .where(models.Team.tournament_id == tournament_id)
            .order_by(models.Team.id.asc())
        )
        return result.unique().scalars().all()


class PlayerRepository(BaseRepository[models.Player]):
    def __init__(self) -> None:
        super().__init__(models.Player)

    async def get_by_user_and_tournament(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        tournament_id: int,
    ) -> models.Player | None:
        return await self.get_by(session, user_id=user_id, tournament_id=tournament_id)

    async def list_by_team(self, session: AsyncSession, team_id: int) -> Sequence[models.Player]:
        result = await session.execute(
            sa.select(models.Player).where(models.Player.team_id == team_id).order_by(models.Player.id.asc())
        )
        return result.scalars().all()


class EncounterRepository(BaseRepository[models.Encounter]):
    def __init__(self) -> None:
        super().__init__(models.Encounter)

    async def get_by_challonge_id(
        self,
        session: AsyncSession,
        challonge_id: int,
    ) -> models.Encounter | None:
        return await self.get_by(session, challonge_id=challonge_id)

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Sequence[models.Encounter]:
        result = await session.execute(
            sa.select(models.Encounter)
            .where(models.Encounter.tournament_id == tournament_id)
            .order_by(models.Encounter.round.asc(), models.Encounter.id.asc())
        )
        return result.scalars().all()


class MatchRepository(BaseRepository[models.Match]):
    def __init__(self) -> None:
        super().__init__(models.Match)

    async def list_by_encounter(self, session: AsyncSession, encounter_id: int) -> Sequence[models.Match]:
        result = await session.execute(
            sa.select(models.Match).where(models.Match.encounter_id == encounter_id).order_by(models.Match.id.asc())
        )
        return result.scalars().all()


class StandingRepository(BaseRepository[models.Standing]):
    def __init__(self) -> None:
        super().__init__(models.Standing)

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Sequence[models.Standing]:
        result = await session.execute(
            sa.select(models.Standing)
            .where(models.Standing.tournament_id == tournament_id)
            .order_by(models.Standing.position.asc(), models.Standing.id.asc())
        )
        return result.scalars().all()
