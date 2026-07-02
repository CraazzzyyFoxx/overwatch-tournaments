"""RPC-callable RBAC flows (no FastAPI Request/Depends).

Faithful ports of the RBAC route bodies in ``src/routes/rbac.py`` so the same
permission checks, 403/404 semantics, and RBAC-cache invalidation side effects
run from both the (legacy) HTTP routes and the typed-RPC handlers in serve.py.
``fastapi.HTTPException`` remains the error vehicle the RPC envelope maps; a
later phase removes it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

from shared.core.errors import BaseAPIException as HTTPException
from shared.core import http_status as status
from shared.core import pagination
from loguru import logger
from shared.models.oauth import OAuthConnection
from shared.models.rbac import Permission, Role, UserPermissionDeny, role_permissions, user_roles
from shared.models.workspace import WorkspaceMember
from shared.rbac import user_has_only_workspace_owner_role
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models, schemas
from src.services import auth_service
from src.services.player_link_service import PlayerLinkService
from src.services.session_cache import invalidate_rbac
from src.services.session_service import SessionService

ADMIN_EQUIVALENT_ROLE_NAMES = {"admin"}


def _permission_key(resource: str, action: str) -> str:
    if resource == "*" and action == "*":
        return "admin.*"
    return f"{resource}.{action}"


def _has_global_permission(user: models.AuthUser, resource: str, action: str) -> bool:
    return bool(getattr(user, "is_superuser", False)) or user.has_permission(resource, action)


def _has_workspace_permission(user: models.AuthUser, workspace_id: int, resource: str, action: str) -> bool:
    return bool(getattr(user, "is_superuser", False)) or user.has_workspace_permission(workspace_id, resource, action)


def _effective_permissions(user: models.AuthUser) -> list[str]:
    keys = {
        _permission_key(permission.resource, permission.action)
        for role in user.roles
        if role.workspace_id is None
        for permission in role.permissions
    }
    return sorted(keys)


def _linked_players_payload(user: models.AuthUser) -> list[schemas.AuthUserLinkedPlayerRead]:
    """Return the 0-or-1 player linked to ``user`` via ``players.user.auth_user_id``
    (see ``auth_token_helpers._linked_players_payload`` for the wire-shape note)."""
    player = user.player
    if player is None:
        return []
    return [
        schemas.AuthUserLinkedPlayerRead(
            player_id=player.id,
            player_name=player.name,
            is_primary=True,
            linked_at=player.created_at.isoformat(),
        )
    ]


def _global_roles(user: models.AuthUser) -> list[Role]:
    return [role for role in user.roles if role.workspace_id is None]


def _auth_user_list_payload(user: models.AuthUser) -> dict:
    payload = schemas.AuthUserListRead.model_validate(user, from_attributes=True).model_dump()
    payload["roles"] = _global_roles(user)
    payload["linked_players"] = _linked_players_payload(user)
    return payload


async def _count_users_with_role(session: AsyncSession, role_id: int) -> int:
    result = await session.execute(select(user_roles.c.user_id).where(user_roles.c.role_id == role_id))
    return len(result.scalars().all())


async def _invalidate_users_with_role(session: AsyncSession, role_id: int) -> None:
    """Invalidate RBAC cache for every user that holds a given role."""
    result = await session.execute(select(user_roles.c.user_id).where(user_roles.c.role_id == role_id))
    for uid in result.scalars().all():
        await invalidate_rbac(uid)


def _check_role_access(user: models.AuthUser, role: Role, required_action: str) -> None:
    """Check access control for a role based on its scope (global vs workspace)."""
    if role.workspace_id is not None:
        if not _has_workspace_permission(user, role.workspace_id, "role", required_action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: role.{required_action} required",
            )
    else:
        if not _has_global_permission(user, "role", required_action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: role.{required_action} required",
            )


def _require_permission(user: models.AuthUser, resource: str, action: str) -> None:
    """Mirror auth_service.require_permission's check for the typed-RPC path."""
    if not user.has_permission(resource, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {resource}.{action} required",
        )


def _require_superuser(user: models.AuthUser) -> None:
    """Mirror auth_service.get_current_superuser's check for the typed-RPC path."""
    if not user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")


# --- Permission flows ---
async def list_permissions(
    session: AsyncSession,
    current_user: models.AuthUser,
    params: schemas.PermissionListParams,
) -> dict:
    """List permissions visible to RBAC operators (paginated, server-side search)."""
    if params.workspace_id is None:
        if not _has_global_permission(current_user, "permission", "read"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: permission.read required",
            )
    elif not _has_workspace_permission(current_user, params.workspace_id, "permission", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: permission.read required",
        )

    query = select(Permission)
    count_query = select(func.count(Permission.id))
    if params.search:
        term = f"%{params.search}%"
        condition = (
            Permission.name.ilike(term)
            | Permission.resource.ilike(term)
            | Permission.action.ilike(term)
            | Permission.description.ilike(term)
        )
        query = query.where(condition)
        count_query = count_query.where(condition)

    query = params.apply_pagination_sort(query, Permission)
    permissions = (await session.execute(query)).scalars().all()
    total = (await session.execute(count_query)).scalar_one()
    return {
        "results": [schemas.PermissionRead.model_validate(p, from_attributes=True) for p in permissions],
        "total": total,
        "page": params.page,
        "per_page": params.per_page,
    }


async def create_permission(
    session: AsyncSession,
    current_user: models.AuthUser,
    permission_data: schemas.PermissionCreate,
) -> Permission:
    """Create a new permission (superuser only)."""
    _require_superuser(current_user)
    result = await session.execute(select(Permission).where(Permission.name == permission_data.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Permission with this name already exists")

    permission = Permission(
        name=permission_data.name,
        resource=permission_data.resource,
        action=permission_data.action,
        description=permission_data.description,
    )
    session.add(permission)
    await session.commit()
    await session.refresh(permission)

    logger.info(f"Permission created: {permission.name}")
    return permission


async def delete_permission(
    session: AsyncSession,
    current_user: models.AuthUser,
    permission_id: int,
) -> None:
    """Delete a permission (superuser only)."""
    _require_superuser(current_user)
    result = await session.execute(select(Permission).where(Permission.id == permission_id))
    permission = result.scalar_one_or_none()

    if not permission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")

    rp_result = await session.execute(
        select(role_permissions.c.role_id).where(role_permissions.c.permission_id == permission_id)
    )
    affected_role_ids = rp_result.scalars().all()
    for rid in affected_role_ids:
        await _invalidate_users_with_role(session, rid)

    await session.delete(permission)
    await session.commit()
    logger.info(f"Permission deleted: {permission.name}")


# --- Role flows ---
async def list_roles(
    session: AsyncSession,
    current_user: models.AuthUser,
    params: schemas.RoleListParams,
) -> dict:
    """List roles by scope (paginated, server-side search)."""
    query = select(Role)
    count_query = select(func.count(Role.id))

    if params.workspace_id is not None:
        if not _has_workspace_permission(current_user, params.workspace_id, "role", "read") and not _has_global_permission(current_user, "role", "read"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        query = query.where(Role.workspace_id == params.workspace_id)
        count_query = count_query.where(Role.workspace_id == params.workspace_id)
    else:
        if not _has_global_permission(current_user, "role", "read"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied: role.read required")
        query = query.where(Role.workspace_id.is_(None))
        count_query = count_query.where(Role.workspace_id.is_(None))

    if params.search:
        term = f"%{params.search}%"
        condition = Role.name.ilike(term) | Role.description.ilike(term)
        query = query.where(condition)
        count_query = count_query.where(condition)

    query = params.apply_pagination_sort(query, Role)
    roles = (await session.execute(query)).scalars().all()
    total = (await session.execute(count_query)).scalar_one()
    return {
        "results": [schemas.RoleRead.model_validate(r, from_attributes=True) for r in roles],
        "total": total,
        "page": params.page,
        "per_page": params.per_page,
    }


async def get_role(
    session: AsyncSession,
    current_user: models.AuthUser,
    role_id: int,
) -> Role:
    """Get role with permissions."""
    result = await session.execute(select(Role).where(Role.id == role_id).options(selectinload(Role.permissions)))
    role = result.scalar_one_or_none()

    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    if role.workspace_id is not None:
        if not _has_workspace_permission(current_user, role.workspace_id, "role", "read") and not _has_global_permission(current_user, "role", "read"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    else:
        if not _has_global_permission(current_user, "role", "read"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied: role.read required")

    return role


async def create_role(
    session: AsyncSession,
    current_user: models.AuthUser,
    role_data: schemas.RoleCreate,
) -> Role:
    """Create a new role (global or workspace-scoped)."""
    if role_data.workspace_id is not None:
        if not _has_workspace_permission(current_user, role_data.workspace_id, "role", "create"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: role.create required",
            )
        ws_result = await session.execute(
            select(models.Workspace.id).where(models.Workspace.id == role_data.workspace_id)
        )
        if not ws_result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    else:
        if not _has_global_permission(current_user, "role", "create"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: role.create required",
            )

    uniqueness_query = select(Role).where(Role.name == role_data.name)
    if role_data.workspace_id is not None:
        uniqueness_query = uniqueness_query.where(Role.workspace_id == role_data.workspace_id)
    else:
        uniqueness_query = uniqueness_query.where(Role.workspace_id.is_(None))

    result = await session.execute(uniqueness_query)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role with this name already exists")

    role = Role(
        name=role_data.name,
        description=role_data.description,
        is_system=False,
        workspace_id=role_data.workspace_id,
    )

    if role_data.permission_ids:
        result = await session.execute(select(Permission).where(Permission.id.in_(role_data.permission_ids)))
        permissions = result.scalars().all()
        role.permissions = list(permissions)

    session.add(role)
    await session.commit()
    await session.refresh(role)

    logger.info(f"Role created: {role.name} (workspace_id={role.workspace_id})")
    return role


async def update_role(
    session: AsyncSession,
    current_user: models.AuthUser,
    role_id: int,
    role_data: schemas.RoleUpdate,
) -> Role:
    """Update a role."""
    result = await session.execute(select(Role).where(Role.id == role_id).options(selectinload(Role.permissions)))
    role = result.scalar_one_or_none()

    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    if role.is_system:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify system roles")

    _check_role_access(current_user, role, "update")

    if role_data.name is not None:
        uniqueness_query = select(Role).where(Role.name == role_data.name, Role.id != role_id)
        if role.workspace_id is not None:
            uniqueness_query = uniqueness_query.where(Role.workspace_id == role.workspace_id)
        else:
            uniqueness_query = uniqueness_query.where(Role.workspace_id.is_(None))

        result = await session.execute(uniqueness_query)
        if result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role with this name already exists")
        role.name = role_data.name

    if role_data.description is not None:
        role.description = role_data.description

    permissions_changed = False
    if role_data.permission_ids is not None:
        result = await session.execute(select(Permission).where(Permission.id.in_(role_data.permission_ids)))
        permissions = result.scalars().all()
        role.permissions = list(permissions)
        permissions_changed = True

    await session.commit()
    await session.refresh(role)

    if permissions_changed:
        await _invalidate_users_with_role(session, role.id)

    logger.info(f"Role updated: {role.name}")
    return role


async def delete_role(
    session: AsyncSession,
    current_user: models.AuthUser,
    role_id: int,
) -> None:
    """Delete a role."""
    result = await session.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()

    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    if role.is_system:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete system roles")

    _check_role_access(current_user, role, "delete")

    await _invalidate_users_with_role(session, role.id)
    await session.delete(role)
    await session.commit()
    logger.info(f"Role deleted: {role.name}")


# --- Auth-user flows ---
async def list_auth_users(
    session: AsyncSession,
    current_user: models.AuthUser,
    params: schemas.AuthUserListParams,
) -> dict:
    """List auth users with assigned roles (paginated, server-side filters)."""
    if params.workspace_id is None:
        if not _has_global_permission(current_user, "auth_user", "read"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: auth_user.read required",
            )
    elif not _has_workspace_permission(current_user, params.workspace_id, "auth_user", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: auth_user.read required",
        )

    users, total = await auth_service.AuthService.list_users_with_rbac(
        session,
        params,
        include_player_links=True,
    )
    return {
        "results": [schemas.AuthUserListRead.model_validate(_auth_user_list_payload(user)) for user in users],
        "total": total,
        "page": params.page,
        "per_page": params.per_page,
    }


async def get_auth_user(
    session: AsyncSession,
    current_user: models.AuthUser,
    user_id: int,
) -> schemas.AuthUserDetailRead:
    """Get auth-user detail with assigned roles and effective permissions."""
    _require_permission(current_user, "auth_user", "read")

    user = await auth_service.AuthService.get_user_with_rbac(session, user_id, include_player_links=True)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    payload = _auth_user_list_payload(user)
    payload["effective_permissions"] = _effective_permissions(user)
    return schemas.AuthUserDetailRead.model_validate(payload)


async def assign_linked_player_to_auth_user(
    session: AsyncSession,
    current_user: models.AuthUser,
    user_id: int,
    data: schemas.AuthUserPlayerLinkAssign,
) -> None:
    """Assign a player account from the analytics system to an auth user."""
    _require_permission(current_user, "auth_user", "update")

    result = await session.execute(select(models.AuthUser).where(models.AuthUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await PlayerLinkService.admin_link_player(session, user_id, data.player_id, data.is_primary)


async def remove_linked_player_from_auth_user(
    session: AsyncSession,
    current_user: models.AuthUser,
    user_id: int,
    player_id: int,
) -> None:
    """Remove a player account link from an auth user."""
    _require_permission(current_user, "auth_user", "update")

    result = await session.execute(select(models.AuthUser).where(models.AuthUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await PlayerLinkService.admin_unlink_player(session, user_id, player_id)


async def assign_role_to_user(
    session: AsyncSession,
    current_user: models.AuthUser,
    data: schemas.UserRoleAssign,
) -> None:
    """Assign a role to a user."""
    result = await session.execute(select(models.AuthUser).where(models.AuthUser.id == data.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    result = await session.execute(select(Role).where(Role.id == data.role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    if role.workspace_id is not None:
        if not _has_workspace_permission(current_user, role.workspace_id, "role", "assign"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: role.assign required",
            )
        member_result = await session.execute(
            select(WorkspaceMember)
            .join(models.User, models.User.id == WorkspaceMember.player_id)
            .where(
                WorkspaceMember.workspace_id == role.workspace_id,
                models.User.auth_user_id == data.user_id,
            )
        )
        if not member_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target user must be a member of the workspace",
            )
    else:
        if not _has_global_permission(current_user, "role", "assign"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: role.assign required",
            )

    if role in user.roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already has this role")

    user.roles.append(role)
    await session.commit()
    await invalidate_rbac(data.user_id)
    logger.info(f"Role {role.name} assigned to user {user.email}")


async def remove_role_from_user(
    session: AsyncSession,
    current_user: models.AuthUser,
    data: schemas.UserRoleRemove,
) -> None:
    """Remove a role from a user."""
    result = await session.execute(
        select(models.AuthUser).where(models.AuthUser.id == data.user_id).options(selectinload(models.AuthUser.roles))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    result = await session.execute(select(Role).where(Role.id == data.role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    if role.workspace_id is not None:
        if not _has_workspace_permission(current_user, role.workspace_id, "role", "assign"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: role.assign required",
            )
    else:
        if not _has_global_permission(current_user, "role", "assign"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: role.assign required",
            )

    if role not in user.roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User does not have this role")

    if role.workspace_id is not None and role.name == "owner":
        if await user_has_only_workspace_owner_role(session, user_id=data.user_id, workspace_id=role.workspace_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last workspace owner role assignment",
            )

    if role.workspace_id is None and role.name in ADMIN_EQUIVALENT_ROLE_NAMES:
        role_assignment_count = await _count_users_with_role(session, role.id)
        if role_assignment_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the last admin role assignment"
            )

    user.roles.remove(role)
    await session.commit()
    await invalidate_rbac(data.user_id)
    logger.info(f"Role {role.name} removed from user {user.email}")


async def get_user_roles(
    session: AsyncSession,
    current_user: models.AuthUser,
    user_id: int,
) -> list[Role]:
    """Get all roles for a user."""
    _require_permission(current_user, "auth_user", "read")

    result = await session.execute(
        select(models.AuthUser).where(models.AuthUser.id == user_id).options(selectinload(models.AuthUser.roles))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return _global_roles(user)


async def list_oauth_connections(
    session: AsyncSession,
    current_user: models.AuthUser,
    params: schemas.OAuthConnectionListParams,
) -> dict:
    """List OAuth connections across all users (admin view, paginated)."""
    _require_permission(current_user, "auth_user", "read")

    query = select(OAuthConnection).options(selectinload(OAuthConnection.auth_user))
    count_query = select(func.count(OAuthConnection.id))

    if params.provider:
        query = query.where(OAuthConnection.provider == params.provider)
        count_query = count_query.where(OAuthConnection.provider == params.provider)

    if params.search:
        term = f"%{params.search}%"
        condition = (
            OAuthConnection.username.ilike(term)
            | OAuthConnection.email.ilike(term)
            | OAuthConnection.display_name.ilike(term)
            | OAuthConnection.provider_user_id.ilike(term)
        )
        query = query.where(condition)
        count_query = count_query.where(condition)

    query = params.apply_pagination_sort(query, OAuthConnection)
    connections = (await session.execute(query)).scalars().all()
    total = (await session.execute(count_query)).scalar_one()

    results = [
        schemas.OAuthConnectionAdminRead(
            id=conn.id,
            provider=conn.provider,
            provider_user_id=conn.provider_user_id,
            email=conn.email,
            username=conn.username,
            display_name=conn.display_name,
            avatar_url=conn.avatar_url,
            created_at=conn.created_at,
            updated_at=conn.updated_at,
            auth_user_id=conn.auth_user_id,
            auth_user_email=conn.auth_user.email if conn.auth_user else None,
            auth_user_username=conn.auth_user.username if conn.auth_user else None,
            token_expires_at=conn.token_expires_at,
        )
        for conn in connections
    ]
    return {"results": results, "total": total, "page": params.page, "per_page": params.per_page}


_SESSION_SORT_KEYS = frozenset({"login_at", "last_seen_at", "expires_at", "status"})


def _sort_session_summaries(
    summaries: Sequence[dict],
    sort: str,
    order: pagination.SortOrder | str,
) -> list[dict]:
    """Stable-sort aggregated session summaries by a whitelisted key.

    Logical sessions are aggregated from refresh tokens in Python, so sorting
    happens here (not in SQL). Falls back to ``last_seen_at`` for unknown keys.
    """
    key_name = sort if sort in _SESSION_SORT_KEYS else "last_seen_at"
    reverse = order == pagination.SortOrder.DESC or order == "desc"
    _min_dt = datetime.min.replace(tzinfo=UTC)

    if key_name == "status":
        def key(summary: dict) -> tuple:
            return (summary.get("status") or "",)
    else:
        def key(summary: dict) -> tuple:
            return (summary.get(key_name) or _min_dt,)

    return sorted(summaries, key=key, reverse=reverse)


async def list_auth_sessions(
    session: AsyncSession,
    current_user: models.AuthUser,
    params: schemas.SessionListParams,
) -> dict:
    """List logical auth sessions across all users (superuser only, paginated).

    Aggregation/status derivation stay in Python; sort + pagination are applied
    to the aggregated summaries, and ``total`` reflects the filtered set.
    """
    _require_superuser(current_user)
    summaries = await SessionService.list_all_sessions(
        session,
        user_id=params.user_id,
        search=params.search,
        status=params.status,
    )
    summaries = _sort_session_summaries(summaries, params.sort, params.order)
    total = len(summaries)
    page_items = params.paginate_data(summaries)
    return {
        "results": [schemas.AdminSessionRead.model_validate(summary) for summary in page_items],
        "total": total,
        "page": params.page,
        "per_page": params.per_page,
    }


async def delete_oauth_connection(
    session: AsyncSession,
    current_user: models.AuthUser,
    connection_id: int,
) -> None:
    """Delete a specific OAuth connection from an auth user (admin view)."""
    _require_permission(current_user, "auth_user", "update")

    result = await session.execute(
        select(OAuthConnection)
        .where(OAuthConnection.id == connection_id)
        .options(selectinload(OAuthConnection.auth_user))
    )
    connection = result.scalar_one_or_none()

    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth connection not found")

    linked_user = connection.auth_user
    if linked_user and not linked_user.hashed_password:
        count_result = await session.execute(
            select(OAuthConnection.id).where(OAuthConnection.auth_user_id == connection.auth_user_id)
        )
        connections_count = len(count_result.scalars().all())
        if connections_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot unlink last OAuth provider for a passwordless account. Set a password first.",
            )

    await session.delete(connection)
    await session.commit()
    logger.info(
        "OAuth connection deleted by admin: "
        f"connection_id={connection.id} provider={connection.provider} auth_user_id={connection.auth_user_id} "
        f"actor_user_id={current_user.id}"
    )


# --- Per-user permission denies (negative RBAC) ---

# A deny on these resources could lock RBAC administration out of the system or
# brick a superuser; never deniable.
_DENY_PROTECTED_RESOURCES = frozenset({"*", "role", "permission", "auth_user"})


def _deny_payload(permission: Permission, workspace_id: int | None) -> dict:
    return {
        "permission_id": permission.id,
        "name": permission.name,
        "resource": permission.resource,
        "action": permission.action,
        "description": permission.description,
        "workspace_id": workspace_id,
    }


def _workspace_scope_filter(workspace_id: int | None):
    """NULL-safe equality filter for ``UserPermissionDeny.workspace_id``.

    Mirrors the ``COALESCE(workspace_id, 0)`` unique-index semantics: a global
    deny (``workspace_id IS NULL``) and a deny scoped to a concrete workspace
    are distinct scopes and must never be conflated by a plain ``==`` (which
    never matches NULL).
    """
    if workspace_id is None:
        return UserPermissionDeny.workspace_id.is_(None)
    return UserPermissionDeny.workspace_id == workspace_id


async def list_user_denies(
    session: AsyncSession, current_user: models.AuthUser, user_id: int
) -> list[dict]:
    """List the permissions explicitly denied for a user (global + per-workspace)."""
    _require_permission(current_user, "auth_user", "read")
    result = await session.execute(
        select(Permission, UserPermissionDeny.workspace_id)
        .join(UserPermissionDeny, UserPermissionDeny.permission_id == Permission.id)
        .where(UserPermissionDeny.user_id == user_id)
        .order_by(Permission.name, UserPermissionDeny.workspace_id)
    )
    return [_deny_payload(permission, workspace_id) for permission, workspace_id in result.all()]


async def add_user_deny(
    session: AsyncSession,
    current_user: models.AuthUser,
    user_id: int,
    permission_id: int,
    reason: str | None = None,
    workspace_id: int | None = None,
) -> list[dict]:
    """Deny a permission to a user (idempotent). Rejects governance permissions.

    ``workspace_id=None`` denies the permission globally (everywhere); a
    concrete ``workspace_id`` scopes the deny to that workspace only. A user
    can hold both a global and a workspace-scoped deny for the same
    permission at once (distinct rows per the partial-unique index).
    """
    _require_permission(current_user, "auth_user", "update")

    user = await session.scalar(select(models.AuthUser).where(models.AuthUser.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    permission = await session.scalar(select(Permission).where(Permission.id == permission_id))
    if permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    if permission.resource in _DENY_PROTECTED_RESOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot deny governance permission '{permission.name}'",
        )

    if workspace_id is not None:
        workspace = await session.scalar(select(models.Workspace).where(models.Workspace.id == workspace_id))
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    existing = await session.scalar(
        select(UserPermissionDeny).where(
            UserPermissionDeny.user_id == user_id,
            UserPermissionDeny.permission_id == permission_id,
            _workspace_scope_filter(workspace_id),
        )
    )
    if existing is None:
        session.add(
            UserPermissionDeny(
                user_id=user_id,
                permission_id=permission_id,
                workspace_id=workspace_id,
                created_by=current_user.id,
                reason=reason,
            )
        )
        await session.commit()
        logger.info(
            f"Permission denied to user: user_id={user_id} permission={permission.name} "
            f"workspace_id={workspace_id} actor={current_user.id}"
        )
    await invalidate_rbac(user_id)
    return await list_user_denies(session, current_user, user_id)


async def remove_user_deny(
    session: AsyncSession,
    current_user: models.AuthUser,
    user_id: int,
    permission_id: int,
    workspace_id: int | None = None,
) -> list[dict]:
    """Remove a permission deny from a user (idempotent).

    Matches the exact ``(user_id, permission_id, workspace_id)`` scope (see
    ``_workspace_scope_filter``) so removing a global deny never removes a
    workspace-scoped deny for the same permission, and vice-versa.
    """
    _require_permission(current_user, "auth_user", "update")
    await session.execute(
        delete(UserPermissionDeny).where(
            UserPermissionDeny.user_id == user_id,
            UserPermissionDeny.permission_id == permission_id,
            _workspace_scope_filter(workspace_id),
        )
    )
    await session.commit()
    await invalidate_rbac(user_id)
    logger.info(
        f"Permission deny removed: user_id={user_id} permission_id={permission_id} "
        f"workspace_id={workspace_id} actor={current_user.id}"
    )
    return await list_user_denies(session, current_user, user_id)
