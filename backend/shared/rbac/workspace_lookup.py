"""Canonical workspace-scoped RBAC lookups for typed-RPC/DB-backed auth.

``core/auth.py`` reimplemented the identical set of "resolve this entity's
owning workspace, 404 if missing, then check the caller's permission in that
workspace" getters in tournament-service, parser-service, and
analytics-service — the last two were a **byte-for-byte identical file**
(parser-service's docstring even survived, unedited, inside analytics-service).
balancer-service overlaps on the tournament/registration getters while adding
its own token-based user resolution and balance/draft-specific lookups, which
stay local. This module is the single source of truth for the shared subset;
each service's ``core/auth.py`` re-exports what it needs (some under a leading
underscore, to match existing ``from src.core.auth import _get_x_workspace_id``
call sites).

Distinct from ``shared.services.workspace_scope.get_tournament_workspace_id``:
that one scopes a *read* and returns ``None`` for a missing tournament; this one
gates *access* and raises ``404`` — same name, different module, different
contract, do not conflate them.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.repository import TournamentRepository

__all__ = (
    "resolve_user_from_db",
    "require_workspace_permission",
    "get_tournament_workspace_id",
    "get_team_workspace_id",
    "get_player_workspace_id",
    "get_player_sub_role_workspace_id",
    "get_stage_workspace_id",
    "get_stage_item_workspace_id",
    "get_stage_item_input_workspace_id",
    "get_encounter_workspace_id",
    "get_match_workspace_id",
    "get_standing_workspace_id",
    "get_log_record_workspace_id",
    "get_registration_workspace_id",
    "get_tournament_link_workspace_id",
    "require_tournament_id_permission",
    "require_encounter_ids_permission",
)

_tournaments = TournamentRepository()


async def resolve_user_from_db(user_id: int, payload: dict[str, Any], *, session: AsyncSession) -> AuthUser | None:
    result = await session.execute(select(AuthUser).where(AuthUser.id == user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        # Build workspace RBAC lookup from validate payload
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
    workspace_id = await _tournaments.get_workspace_id(session, tournament_id)
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


async def get_log_record_workspace_id(session: AsyncSession, record_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.LogProcessingRecord, models.LogProcessingRecord.tournament_id == models.Tournament.id)
        .where(models.LogProcessingRecord.id == record_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log processing record not found")
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


async def get_tournament_link_workspace_id(session: AsyncSession, link_id: int) -> int:
    # TournamentLink has no denormalized workspace_id column — derive it via the
    # owning tournament (links are always tournament-scoped).
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id)
        .join(models.TournamentLink, models.TournamentLink.tournament_id == models.Tournament.id)
        .where(models.TournamentLink.id == link_id)
    )
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tournament link not found",
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
