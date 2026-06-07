"""Admin routes for standing management"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, db
from src.schemas.admin import standing as admin_schemas
from src.services.admin import standing as admin_service
from src.services.standings import flows as standings_flows

router = APIRouter(
    prefix="/standings",
    tags=["admin", "standings"],
)


@router.patch("/{standing_id}", response_model=schemas.StandingRead)
async def update_standing(
    standing_id: int,
    data: admin_schemas.StandingUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_standing_permission("standing", "update")),
):
    """Update standing fields (admin/organizer only)"""
    standing = await admin_service.update_standing(session, standing_id, data)
    return await standings_flows.to_pydantic(session, standing, ["team", "stage", "stage_item", "tournament"])


@router.delete("/{standing_id}", status_code=204)
async def delete_standing(
    standing_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_standing_permission("standing", "delete")),
):
    """Delete standing (admin/organizer only)"""
    await admin_service.delete_standing(session, standing_id)


@router.post(
    "/recalculate/{tournament_id}",
    response_model=schemas.admin.computation.TournamentComputationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def recalculate_standings(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("standing", "recalculate")),
):
    """Schedule standings recalculation (admin/organizer only)."""
    return await admin_service.recalculate_standings(
        session,
        tournament_id,
        requested_by_user_id=int(user.id),
    )
