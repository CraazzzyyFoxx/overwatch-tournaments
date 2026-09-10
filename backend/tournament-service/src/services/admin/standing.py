"""Admin service layer for standing management"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import StandingRepository, TournamentRepository
from src import models, schemas
from src.services.computation.jobs import jobs_service
from src.services.tournament.events import RESULT_RESOURCES, publish_tournament_invalidation


class AdminStandingService:
    def __init__(
        self,
        *,
        standing_repo: StandingRepository = StandingRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
    ) -> None:
        self.standing_repo = standing_repo
        self.tournament_repo = tournament_repo

    async def _publish_results_changed(self, session: AsyncSession, tournament_id: int) -> None:
        await publish_tournament_invalidation(session, tournament_id, RESULT_RESOURCES)

    async def get_standing(self, session: AsyncSession, standing_id: int) -> models.Standing:
        standing = await self.standing_repo.get(
            session,
            standing_id,
            options=(
                selectinload(models.Standing.team),
                selectinload(models.Standing.stage)
                .selectinload(models.Stage.items)
                .selectinload(models.StageItem.inputs),
                selectinload(models.Standing.stage_item).selectinload(models.StageItem.inputs),
                selectinload(models.Standing.tournament),
            ),
        )

        if not standing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Standing not found",
            )

        return standing

    async def update_standing(
        self, session: AsyncSession, standing_id: int, data: schemas.StandingUpdate
    ) -> models.Standing:
        """Update standing fields"""
        standing = await self.get_standing(session, standing_id)

        # Update fields
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(standing, field, value)

        await self._publish_results_changed(session, standing.tournament_id)
        await session.commit()
        return await self.get_standing(session, standing.id)

    async def delete_standing(self, session: AsyncSession, standing_id: int) -> None:
        """Delete standing"""
        standing = await self.standing_repo.get(session, standing_id)

        if not standing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standing not found")

        await self._publish_results_changed(session, standing.tournament_id)
        await self.standing_repo.delete(session, standing)
        await session.commit()

    async def recalculate_standings(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        requested_by_user_id: int | None = None,
    ) -> models.TournamentComputationJob:
        """Schedule a durable standings recalculation without exposing empty data."""
        # Verify tournament exists
        tournament = await self.tournament_repo.get(session, tournament_id)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        job = await jobs_service.request_standings_recalculation(
            session,
            tournament_id,
            requested_by_user_id=requested_by_user_id,
        )
        await session.commit()
        return job


standing_service = AdminStandingService()
