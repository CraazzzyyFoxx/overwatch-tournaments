"""Authentication dependencies for tournament-service.

The ``get_*_workspace_id`` resolvers and ``require_*`` helpers below are the
cross-module authorization contract: RPC handlers resolve the workspace from
the actual object being acted on (never from a client-supplied field) and then
check the caller's permission in that workspace.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from src import models


async def require_workspace_permission(
    current_user: AuthUser,
    *,
    workspace_id: int,
    resource: str,
    action: str,
) -> AuthUser:
    if not current_user.has_workspace_permission(workspace_id, resource, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied for workspace {workspace_id}: {resource}.{action} required",
        )

    return current_user


async def get_tournament_workspace_id(session: AsyncSession, tournament_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tournament not found",
        )
    return int(workspace_id)


async def get_team_workspace_id(session: AsyncSession, team_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Team, models.Team.tournament_id == models.Tournament.id)
        .where(models.Team.id == team_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return int(workspace_id)


async def get_player_workspace_id(session: AsyncSession, player_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Player, models.Player.tournament_id == models.Tournament.id)
        .where(models.Player.id == player_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return int(workspace_id)


async def get_player_sub_role_workspace_id(session: AsyncSession, sub_role_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.PlayerSubRole.workspace_id).where(models.PlayerSubRole.id == sub_role_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player sub-role not found")
    return int(workspace_id)


async def get_stage_workspace_id(session: AsyncSession, stage_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Stage, models.Stage.tournament_id == models.Tournament.id)
        .where(models.Stage.id == stage_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    return int(workspace_id)


async def get_stage_item_workspace_id(session: AsyncSession, stage_item_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Stage, models.Stage.tournament_id == models.Tournament.id)
        .join(models.StageItem, models.StageItem.stage_id == models.Stage.id)
        .where(models.StageItem.id == stage_item_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage item not found")
    return int(workspace_id)


async def get_stage_item_input_workspace_id(session: AsyncSession, input_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Stage, models.Stage.tournament_id == models.Tournament.id)
        .join(models.StageItem, models.StageItem.stage_id == models.Stage.id)
        .join(models.StageItemInput, models.StageItemInput.stage_item_id == models.StageItem.id)
        .where(models.StageItemInput.id == input_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage item input not found")
    return int(workspace_id)


async def get_encounter_workspace_id(session: AsyncSession, encounter_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Encounter, models.Encounter.tournament_id == models.Tournament.id)
        .where(models.Encounter.id == encounter_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    return int(workspace_id)


async def get_match_workspace_id(session: AsyncSession, match_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Encounter, models.Encounter.tournament_id == models.Tournament.id)
        .join(models.Match, models.Match.encounter_id == models.Encounter.id)
        .where(models.Match.id == match_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    return int(workspace_id)


async def get_standing_workspace_id(session: AsyncSession, standing_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Standing, models.Standing.tournament_id == models.Tournament.id)
        .where(models.Standing.id == standing_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standing not found")
    return int(workspace_id)


async def get_registration_workspace_id(session: AsyncSession, registration_id: int) -> int:
    # BalancerRegistration has no denormalized workspace_id column — derive it via
    # the owning tournament (registrations are always tournament-scoped).
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.BalancerRegistration, models.BalancerRegistration.tournament_id == models.Tournament.id)
        .where(models.BalancerRegistration.id == registration_id)
    )
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )
    return int(workspace_id)


async def require_tournament_id_permission(
    session: AsyncSession,
    current_user: AuthUser,
    *,
    tournament_id: int,
    resource: str,
    action: str,
) -> AuthUser:
    workspace_id = await get_tournament_workspace_id(session, tournament_id)
    return await require_workspace_permission(
        current_user,
        workspace_id=workspace_id,
        resource=resource,
        action=action,
    )


async def require_encounter_ids_permission(
    session: AsyncSession,
    current_user: AuthUser,
    *,
    encounter_ids: list[int],
    resource: str,
    action: str,
) -> AuthUser:
    result = await session.execute(
        sa.select(models.Tournament.workspace_id)
        .join(models.Encounter, models.Encounter.tournament_id == models.Tournament.id)
        .where(models.Encounter.id.in_(encounter_ids))
        .distinct()
    )
    workspace_ids = [int(workspace_id) for workspace_id in result.scalars().all()]
    if not workspace_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounters not found")
    for workspace_id in workspace_ids:
        await require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )
    return current_user
