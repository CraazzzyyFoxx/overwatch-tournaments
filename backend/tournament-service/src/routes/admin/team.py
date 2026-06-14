"""Admin routes for team and player CRUD operations"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, db
from src.schemas.admin import team as admin_schemas
from src.services.admin import team as admin_service
from src.services.team import flows as team_flows

router = APIRouter(
    prefix="/teams",
    tags=["admin", "teams"],
)

player_router = APIRouter(
    prefix="/players",
    tags=["admin", "players"],
)


# ─── Team CRUD ───────────────────────────────────────────────────────────────


@router.post("", response_model=schemas.TeamRead)
async def create_team(
    data: admin_schemas.TeamCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Create a new team (admin/organizer only)"""
    await auth.require_tournament_id_permission(
        session,
        user,
        tournament_id=data.tournament_id,
        resource="team",
        action="create",
    )
    team = await admin_service.create_team(session, data)
    return await team_flows.to_pydantic(session, team, ["tournament", "players", "players.user", "captain"])


@router.get("/{team_id}", response_model=schemas.TeamRead)
async def get_team(
    team_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_team_permission("team", "read")),
):
    """Get one team for admin workspace pages."""
    team = await admin_service.get_team(session, team_id)
    return await team_flows.to_pydantic(session, team, ["tournament", "players", "players.user", "captain"])


@router.patch("/{team_id}", response_model=schemas.TeamRead)
async def update_team(
    team_id: int,
    data: admin_schemas.TeamUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_team_permission("team", "update")),
):
    """Update team fields (admin/organizer only)"""
    team = await admin_service.update_team(session, team_id, data)
    return await team_flows.to_pydantic(session, team, ["tournament", "players", "players.user", "captain"])


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    team_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_team_permission("team", "delete")),
):
    """Delete team and all players (admin/organizer only)"""
    await admin_service.delete_team(session, team_id)


# ─── Player Management (via team) ────────────────────────────────────────────


@router.post("/{team_id}/players", response_model=schemas.PlayerRead)
async def add_player_to_team(
    team_id: int,
    data: admin_schemas.PlayerCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_team_permission("player", "create")),
):
    """Add a player to a team (admin/organizer only)"""
    player = await admin_service.add_player_to_team(session, team_id, data)
    return await team_flows.to_pydantic_player(session, player, ["user", "tournament"])


@router.delete("/{team_id}/players/{player_id}", status_code=204)
async def remove_player_from_team(
    team_id: int,
    player_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_team_permission("player", "delete")),
):
    """Remove a player from a team (admin/organizer only)"""
    await admin_service.remove_player_from_team(session, team_id, player_id)


# ─── Player CRUD ─────────────────────────────────────────────────────────────


@player_router.post("", response_model=schemas.PlayerRead)
async def create_player(
    data: admin_schemas.PlayerCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Create a new player (admin/organizer only)"""
    await auth.require_tournament_id_permission(
        session,
        user,
        tournament_id=data.tournament_id,
        resource="player",
        action="create",
    )
    player = await admin_service.create_player(session, data)
    return await team_flows.to_pydantic_player(session, player, ["user", "tournament"])


@player_router.patch("/{player_id}", response_model=schemas.PlayerRead)
async def update_player(
    player_id: int,
    data: admin_schemas.PlayerUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_player_permission("player", "update")),
):
    """Update player fields (admin/organizer only)"""
    player = await admin_service.update_player(session, player_id, data)
    return await team_flows.to_pydantic_player(session, player, ["user", "tournament"])


@player_router.delete("/{player_id}", status_code=204)
async def delete_player(
    player_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_player_permission("player", "delete")),
):
    """Delete player (admin/organizer only)"""
    await admin_service.delete_player(session, player_id)
