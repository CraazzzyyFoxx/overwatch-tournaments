"""Authentication dependencies for balancer-service.

Stateless user resolution still relies on the auth-service token payload, but
workspace-scoped admin access must be enforced against workspace RBAC from that
payload instead of legacy global roles only.
"""

from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.auth import create_auth_dependencies
from shared.models.auth_user import AuthUser
from shared.models.rbac import Permission, Role
from src import models
from src.core import db


def _safe_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _build_roles(value: Any) -> list[Role]:
    if not isinstance(value, list):
        return []
    roles: list[Role] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            roles.append(Role(name=item.strip()))
    return roles


def _build_permissions(value: Any) -> list[Permission]:
    if not isinstance(value, list):
        return []
    permissions: list[Permission] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        resource = item.get("resource")
        action = item.get("action")
        if not isinstance(resource, str) or not resource.strip():
            continue
        if not isinstance(action, str) or not action.strip():
            continue
        resource = resource.strip()
        action = action.strip()
        permissions.append(
            Permission(
                name=f"{resource}.{action}",
                resource=resource,
                action=action,
            )
        )
    return permissions


def _build_workspace_cache(
    value: Any,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, list[dict[str, str]] | list[str]]]]:
    if not isinstance(value, list):
        return [], {}

    workspaces: list[dict[str, Any]] = []
    workspace_rbac: dict[int, dict[str, list[dict[str, str]] | list[str]]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue

        workspace_id_raw = item.get("workspace_id")
        try:
            workspace_id = int(workspace_id_raw)
        except (TypeError, ValueError):
            continue

        rbac_roles = item.get("rbac_roles")
        if not isinstance(rbac_roles, list):
            rbac_roles = []

        rbac_permissions = item.get("rbac_permissions")
        if not isinstance(rbac_permissions, list):
            rbac_permissions = []

        workspace_payload = {
            "workspace_id": workspace_id,
            "slug": _safe_str(item.get("slug")),
            "role": _safe_str(item.get("role")),
            "rbac_roles": rbac_roles,
            "rbac_permissions": rbac_permissions,
        }
        workspaces.append(workspace_payload)
        workspace_rbac[workspace_id] = {
            "roles": rbac_roles,
            "permissions": rbac_permissions,
        }

    return workspaces, workspace_rbac


async def _resolve_user_from_token(user_id: int, payload: dict[str, Any]) -> AuthUser:
    roles = _build_roles(payload.get("roles"))
    permissions = _build_permissions(payload.get("permissions"))
    workspaces, workspace_rbac = _build_workspace_cache(payload.get("workspaces"))
    if permissions:
        if roles:
            for role in roles:
                role.permissions = permissions
        else:
            role = Role(name="token")
            role.permissions = permissions
            roles = [role]

    user = AuthUser(
        id=user_id,
        username=_safe_str(payload.get("username")),
        email=_safe_str(payload.get("email")),
        is_active=True,
        is_superuser=bool(payload.get("is_superuser", False)),
    )
    user.roles = roles
    user.set_rbac_cache(
        role_names=payload.get("roles", []),
        permissions=payload.get("permissions", []),
        workspaces=workspaces,
        workspace_rbac=workspace_rbac,
    )
    credential_type = _safe_str(payload.get("credential_type")) or "access_token"
    object.__setattr__(user, "_credential_type", credential_type)
    api_key_payload = payload.get("api_key")
    if isinstance(api_key_payload, dict):
        object.__setattr__(user, "_api_key_id", api_key_payload.get("id"))
        object.__setattr__(user, "_api_key_public_id", _safe_str(api_key_payload.get("public_id")))
        object.__setattr__(user, "_api_key_workspace_id", api_key_payload.get("workspace_id"))
        object.__setattr__(user, "_api_key_scopes", api_key_payload.get("scopes") or [])
        object.__setattr__(user, "_api_key_limits", api_key_payload.get("limits") or {})
        object.__setattr__(user, "_api_key_config_policy", api_key_payload.get("config_policy") or {})
    return user


_auth = create_auth_dependencies(_resolve_user_from_token)

get_current_user = _auth.get_current_user
get_current_active_user = _auth.get_current_active_user
get_current_superuser = _auth.get_current_superuser
require_permission = _auth.require_permission
require_role = _auth.require_role
require_any_role = _auth.require_any_role
require_admin_panel_access = _auth.require_admin_panel_access
require_workspace_member = _auth.require_workspace_member
require_workspace_admin = _auth.require_workspace_admin


async def _require_workspace_permission(
    current_user: AuthUser,
    *,
    workspace_id: int,
    resource: str,
    action: str,
) -> AuthUser:
    if getattr(current_user, "_credential_type", "access_token") == "api_key":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys cannot access balancer admin endpoints",
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tournament not found",
        )
    return int(workspace_id)


async def _get_registration_workspace_id(session: AsyncSession, registration_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.BalancerRegistration.workspace_id).where(models.BalancerRegistration.id == registration_id)
    )
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )
    return int(workspace_id)


async def _get_balance_workspace_id(session: AsyncSession, balance_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(sa.func.coalesce(models.BalancerBalance.workspace_id, models.Tournament.workspace_id))
        .join(models.Tournament, models.Tournament.id == models.BalancerBalance.tournament_id)
        .where(models.BalancerBalance.id == balance_id)
    )
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Balance not found",
        )
    return int(workspace_id)


def require_workspace_permission(resource: str, action: str):
    async def permission_checker(
        workspace_id: int,
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_tournament_permission(resource: str, action: str):
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


def require_registration_permission(resource: str, action: str):
    async def permission_checker(
        registration_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_registration_workspace_id(session, registration_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


def require_balance_permission(resource: str, action: str):
    async def permission_checker(
        balance_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_balance_workspace_id(session, balance_id)
        return await _require_workspace_permission(
            current_user,
            workspace_id=workspace_id,
            resource=resource,
            action=action,
        )

    return permission_checker


async def _get_draft_session_workspace_id(session: AsyncSession, session_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.DraftSession.workspace_id).where(models.DraftSession.id == session_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft session not found")
    return int(workspace_id)


async def _get_pick_workspace_id(session: AsyncSession, pick_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.DraftSession.workspace_id)
        .join(models.DraftPick, models.DraftPick.session_id == models.DraftSession.id)
        .where(models.DraftPick.id == pick_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft pick not found")
    return int(workspace_id)


def require_draft_session_permission(resource: str, action: str):
    async def permission_checker(
        session_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_draft_session_workspace_id(session, session_id)
        return await _require_workspace_permission(
            current_user, workspace_id=workspace_id, resource=resource, action=action
        )

    return permission_checker


def require_pick_permission(resource: str, action: str):
    async def permission_checker(
        pick_id: int,
        session: Annotated[AsyncSession, Depends(db.get_async_session)],
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        workspace_id = await _get_pick_workspace_id(session, pick_id)
        return await _require_workspace_permission(
            current_user, workspace_id=workspace_id, resource=resource, action=action
        )

    return permission_checker
