"""Authentication dependencies for parser-service (DB-backed + service scopes)."""

from typing import Any

import sqlalchemy as sa
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

# ── Shared auth dependencies (DB-backed) ─────────────────────────────

async def _resolve_user_from_db(
    user_id: int, payload: dict[str, Any], *, session: AsyncSession
) -> AuthUser | None:
    result = await session.execute(
        select(AuthUser).where(AuthUser.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is not None:
        workspace_rbac: dict[int, dict] = {}
        for ws in payload.get("workspaces", []):
            ws_id = ws.get("workspace_id")
            if ws_id is not None:
                workspace_rbac[ws_id] = {
                    "roles": ws.get("rbac_roles", []),
                    "permissions": ws.get("rbac_permissions", []),
                }
        user.set_rbac_cache(
            role_names=payload.get("roles", []),
            permissions=payload.get("permissions", []),
            workspaces=payload.get("workspaces", []),
            workspace_rbac=workspace_rbac,
        )
    return user


# ── Parser-specific: service token scopes ─────────────────────────────

async def _require_workspace_permission(
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


async def _get_tournament_workspace_id(session: AsyncSession, tournament_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return int(workspace_id)


async def _get_team_workspace_id(session: AsyncSession, team_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Team, models.Team.tournament_id == models.Tournament.id)
        .where(models.Team.id == team_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return int(workspace_id)


async def _get_player_workspace_id(session: AsyncSession, player_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Player, models.Player.tournament_id == models.Tournament.id)
        .where(models.Player.id == player_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return int(workspace_id)


async def _get_player_sub_role_workspace_id(session: AsyncSession, sub_role_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.PlayerSubRole.workspace_id).where(models.PlayerSubRole.id == sub_role_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player sub-role not found")
    return int(workspace_id)


async def _get_stage_workspace_id(session: AsyncSession, stage_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Stage, models.Stage.tournament_id == models.Tournament.id)
        .where(models.Stage.id == stage_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    return int(workspace_id)


async def _get_stage_item_workspace_id(session: AsyncSession, stage_item_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Stage, models.Stage.tournament_id == models.Tournament.id)
        .join(models.StageItem, models.StageItem.stage_id == models.Stage.id)
        .where(models.StageItem.id == stage_item_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage item not found")
    return int(workspace_id)


async def _get_stage_item_input_workspace_id(session: AsyncSession, input_id: int) -> int:
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


async def _get_encounter_workspace_id(session: AsyncSession, encounter_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Encounter, models.Encounter.tournament_id == models.Tournament.id)
        .where(models.Encounter.id == encounter_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    return int(workspace_id)


async def _get_match_workspace_id(session: AsyncSession, match_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Encounter, models.Encounter.tournament_id == models.Tournament.id)
        .join(models.Match, models.Match.encounter_id == models.Encounter.id)
        .where(models.Match.id == match_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    return int(workspace_id)


async def _get_standing_workspace_id(session: AsyncSession, standing_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.Standing, models.Standing.tournament_id == models.Tournament.id)
        .where(models.Standing.id == standing_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standing not found")
    return int(workspace_id)


async def _get_log_record_workspace_id(session: AsyncSession, record_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.LogProcessingRecord, models.LogProcessingRecord.tournament_id == models.Tournament.id)
        .where(models.LogProcessingRecord.id == record_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log processing record not found")
    return int(workspace_id)


async def require_tournament_id_permission(
    session: AsyncSession,
    current_user: AuthUser,
    *,
    tournament_id: int,
    resource: str,
    action: str,
) -> AuthUser:
    workspace_id = await _get_tournament_workspace_id(session, tournament_id)
    return await _require_workspace_permission(
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
        await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )
    return current_user
