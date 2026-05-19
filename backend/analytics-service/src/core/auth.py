"""Authentication dependencies for parser-service (DB-backed + service scopes)."""

from collections.abc import Callable
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from shared.core.auth import create_auth_dependencies
from shared.models.auth_user import AuthUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import db

# Re-use the shared security scheme
_security = HTTPBearer(auto_error=False)


def _get_request_token(
    token: HTTPAuthorizationCredentials | None,
    request: Request,
) -> str | None:
    if token is not None:
        return token.credentials
    cookie_token = request.cookies.get("aqt_access_token")
    if not cookie_token:
        return None
    cookie_token = cookie_token.removeprefix("Bearer ").strip()
    return cookie_token or None


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


_auth = create_auth_dependencies(
    _resolve_user_from_db,
    get_session=db.get_async_session,
)

get_current_user = _auth.get_current_user
get_current_active_user = _auth.get_current_active_user
get_current_superuser = _auth.get_current_superuser
require_permission = _auth.require_permission
require_role = _auth.require_role
require_any_role = _auth.require_any_role
require_workspace_member = _auth.require_workspace_member
require_workspace_admin = _auth.require_workspace_admin


def require_workspace_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        workspace_id: int,
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        if not current_user.has_workspace_permission(workspace_id, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied for workspace {workspace_id}: {resource}.{action} required",
            )
        return current_user

    return permission_checker


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


def require_tournament_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        tournament_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_tournament_workspace_id(session, tournament_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_team_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        team_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_team_workspace_id(session, team_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_player_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        player_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_player_workspace_id(session, player_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_player_sub_role_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        sub_role_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_player_sub_role_workspace_id(session, sub_role_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_stage_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        stage_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_stage_workspace_id(session, stage_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_stage_item_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        stage_item_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_stage_item_workspace_id(session, stage_item_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_stage_item_input_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        input_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_stage_item_input_workspace_id(session, input_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_encounter_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        encounter_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_encounter_workspace_id(session, encounter_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_match_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        match_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_match_workspace_id(session, match_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_standing_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        standing_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_standing_workspace_id(session, standing_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_log_record_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        record_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_log_record_workspace_id(session, record_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


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


def require_service_scope(scope: str) -> Callable:
    """Dependency factory for requiring a service token scope."""

    async def scope_checker(
        request: Request,
        token: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
    ) -> dict:
        token_value = _get_request_token(token, request)
        if not token_value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate service credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        import main
        payload = await main.auth_client.validate_service_token(token_value)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate service credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        scopes = payload.get("scopes", [])
        if not isinstance(scopes, list) or scope not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Service scope required: {scope}",
            )

        return payload

    return scope_checker


def require_role_or_service_scope(role_name: str, scope: str) -> Callable:
    """Allow either an authenticated user with role OR a service token with scope."""

    async def checker(
        request: Request,
        token: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
    ):
        token_value = _get_request_token(token, request)
        if not token_value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        import main
        service_payload = await main.auth_client.validate_service_token(token_value)
        if service_payload:
            scopes = service_payload.get("scopes", [])
            if not isinstance(scopes, list) or scope not in scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Service scope required: {scope}",
                )
            return

        user = await get_current_user(request=request, token=token, session=session)
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user",
            )
        if not user.has_role(role_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {role_name}",
            )

    return checker


async def get_current_user_optional(
    request: Request,
    token: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
) -> AuthUser | None:
    """Return the authenticated user if a valid user token is provided, otherwise None."""
    try:
        return await get_current_user(request=request, token=token, session=session)
    except HTTPException:
        return None


def _get_websocket_token(websocket: WebSocket) -> str | None:
    query_token = websocket.query_params.get("token")
    if query_token:
        return query_token.removeprefix("Bearer ").strip() or None

    authorization = websocket.headers.get("authorization")
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials:
            return credentials.strip()

    cookie_token = websocket.cookies.get("aqt_access_token")
    if not cookie_token:
        return None

    cookie_token = cookie_token.removeprefix("Bearer ").strip()
    return cookie_token or None


async def get_websocket_user_optional(
    websocket: WebSocket,
    session: AsyncSession,
) -> AuthUser | None:
    token = _get_websocket_token(websocket)
    if not token:
        return None

    import main

    payload = await main.auth_client.validate_token(token)
    if not payload:
        return None

    user_id_raw = payload.get("sub")
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        return None

    if user_id <= 0:
        return None

    return await _resolve_user_from_db(user_id, payload, session=session)
