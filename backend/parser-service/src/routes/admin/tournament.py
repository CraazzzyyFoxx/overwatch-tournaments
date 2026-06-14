"""Admin routes for tournament CRUD operations"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, db
from src.schemas.admin import tournament as admin_schemas
from src.services.admin import tournament as admin_service
from src.services.tournament import flows as tournament_flows

router = APIRouter(
    prefix="/tournaments",
    tags=["admin", "tournaments"],
)


@router.post("", response_model=schemas.TournamentRead)
async def create_tournament(
    data: admin_schemas.TournamentCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Create a new tournament (admin/organizer only)."""
    if not user.has_workspace_permission(data.workspace_id, "tournament", "create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: tournament.create required",
        )
    tournament = await admin_service.create_tournament(session, data)
    return await tournament_flows.to_pydantic(session, tournament, ["stages"])


@router.get("/{tournament_id}", response_model=schemas.TournamentRead)
async def get_tournament(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("tournament", "read")),
):
    """Get one tournament for admin workspace pages."""
    tournament = await admin_service.get_tournament(session, tournament_id)
    return await tournament_flows.to_pydantic(session, tournament, ["stages"])


@router.patch("/{tournament_id}", response_model=schemas.TournamentRead)
async def update_tournament(
    tournament_id: int,
    data: admin_schemas.TournamentUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("tournament", "update")),
):
    """Update tournament fields (admin/organizer only)."""
    tournament = await admin_service.update_tournament(session, tournament_id, data)
    return await tournament_flows.to_pydantic(session, tournament, ["stages"])


@router.delete("/{tournament_id}", status_code=204)
async def delete_tournament(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("tournament", "delete")),
):
    """Delete tournament and all related data (admin/organizer only)."""
    await admin_service.delete_tournament(session, tournament_id)


@router.post("/{tournament_id}/finish", response_model=schemas.TournamentRead)
async def toggle_tournament_finished(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_superuser),
):
    """Toggle tournament finished status (legacy, prefer PATCH status)."""
    tournament = await admin_service.toggle_finished(session, tournament_id)
    return await tournament_flows.to_pydantic(session, tournament, ["stages"])


@router.patch("/{tournament_id}/status", response_model=schemas.TournamentRead)
async def transition_tournament_status(
    tournament_id: int,
    data: admin_schemas.TournamentStatusTransition,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("tournament", "update")),
):
    """Transition tournament to a new status (admin/organizer only)."""
    if data.force and not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superusers can bypass tournament status transitions",
        )

    tournament = await admin_service.transition_status(
        session,
        tournament_id,
        data.status,
        force=data.force,
    )
    return await tournament_flows.to_pydantic(session, tournament, ["stages"])
