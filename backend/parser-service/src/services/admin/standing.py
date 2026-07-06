"""Admin service layer for standing management"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src import models
from src.schemas.admin import standing as admin_schemas
from src.services.standings import recalculation


async def get_standing(session: AsyncSession, standing_id: int) -> models.Standing:
    result = await session.execute(
        select(models.Standing)
        .where(models.Standing.id == standing_id)
        .options(
            selectinload(models.Standing.team),
            selectinload(models.Standing.group),
            selectinload(models.Standing.stage).selectinload(models.Stage.items).selectinload(models.StageItem.inputs),
            selectinload(models.Standing.stage_item).selectinload(models.StageItem.inputs),
            selectinload(models.Standing.tournament),
        )
    )
    standing = result.scalar_one_or_none()

    if not standing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Standing not found",
        )

    return standing


async def update_standing(
    session: AsyncSession, standing_id: int, data: admin_schemas.StandingUpdate
) -> models.Standing:
    """Update standing fields"""
    standing = await get_standing(session, standing_id)

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(standing, field, value)

    await session.commit()
    return await get_standing(session, standing.id)


async def delete_standing(session: AsyncSession, standing_id: int) -> None:
    """Delete standing"""
    result = await session.execute(select(models.Standing).where(models.Standing.id == standing_id))
    standing = result.scalar_one_or_none()

    if not standing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standing not found")

    await session.delete(standing)
    await session.commit()


async def recalculate_standings(session: AsyncSession, tournament_id: int) -> dict:
    """Publish a standings invalidation for tournament-service."""
    # Verify tournament exists
    result = await session.execute(select(models.Tournament).where(models.Tournament.id == tournament_id))
    tournament = result.scalar_one_or_none()

    if not tournament:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    await recalculation.enqueue_tournament_recalculation(tournament_id)
    return {
        "message": "Standings recalculation scheduled.",
        "tournament_id": tournament_id,
    }
