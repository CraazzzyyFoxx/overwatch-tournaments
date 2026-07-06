"""Admin service layer for standing management"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src import models
from src.schemas.admin import standing as admin_schemas
from src.services.computation.jobs import request_standings_recalculation
from src.services.tournament.events import enqueue_tournament_changed


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

    await enqueue_tournament_changed(
        session,
        standing.tournament_id,
        "results_changed",
    )
    await session.commit()
    return await get_standing(session, standing.id)


async def delete_standing(session: AsyncSession, standing_id: int) -> None:
    """Delete standing"""
    result = await session.execute(select(models.Standing).where(models.Standing.id == standing_id))
    standing = result.scalar_one_or_none()

    if not standing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standing not found")

    await enqueue_tournament_changed(
        session,
        standing.tournament_id,
        "results_changed",
    )
    await session.delete(standing)
    await session.commit()


async def recalculate_standings(
    session: AsyncSession,
    tournament_id: int,
    *,
    requested_by_user_id: int | None = None,
) -> models.TournamentComputationJob:
    """Schedule a durable standings recalculation without exposing empty data."""
    # Verify tournament exists
    result = await session.execute(select(models.Tournament).where(models.Tournament.id == tournament_id))
    tournament = result.scalar_one_or_none()

    if not tournament:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    job = await request_standings_recalculation(
        session,
        tournament_id,
        requested_by_user_id=requested_by_user_id,
    )
    await session.commit()
    return job
