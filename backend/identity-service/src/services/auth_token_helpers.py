"""FastAPI-free auth-token helpers shared by RPC flows.

These were relocated verbatim from the (now-deleted) ``src/routes/auth.py`` so
the live flows (``auth_flows``, ``token_validation``) keep their exact behaviour
without depending on any HTTP route module. ``HTTPException`` is the aliased,
fastapi-free ``BaseAPIException`` that the RPC envelope maps.
"""

from __future__ import annotations

import sqlalchemy as sa
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.services import auth_service
from src.services.session_cache import get_rbac, set_rbac


def _linked_players_payload(user: models.AuthUser) -> list[schemas.AuthLinkedPlayer]:
    """Return the 0-or-1 player linked to ``user`` via ``players.user.auth_user_id``.

    Kept as a list (rather than an optional single value) for wire-shape
    compatibility with the historical many-to-many ``auth.user_player`` model;
    every returned player is, by construction, the single link, so
    ``is_primary`` is always ``True``.
    """
    player = user.player
    if player is None:
        return []
    return [
        schemas.AuthLinkedPlayer(
            player_id=player.id,
            player_name=player.name,
            is_primary=True,
            linked_at=player.created_at.isoformat(),
        )
    ]


async def _build_access_token_payload(
    session: AsyncSession,
    current_user: models.AuthUser,
) -> schemas.TokenPayload:
    cached = await get_rbac(current_user.id)
    if cached is not None:
        roles = cached["roles"]
        permissions = cached["permissions"]
        workspace_roles_cached = cached.get("workspace_roles")
        denies = cached.get("denies")
    else:
        roles = None
        permissions = None
        workspace_roles_cached = None
        denies = None

    if roles is None:
        roles, permissions = await auth_service.AuthService.get_user_roles_and_permissions_db(session, current_user.id)

    # Per-user deny overlay (negative RBAC). Loaded on the DB path too, so denies
    # still apply when Redis is unavailable. ``None`` = not in cache → load fresh.
    if denies is None:
        denies = await _load_user_denies(session, current_user.id)

    # Fetch workspace memberships
    workspace_rows = await session.execute(
        sa.select(
            models.WorkspaceMember.workspace_id,
            models.Workspace.slug,
            models.WorkspaceMember.role,
        )
        .join(models.Workspace, models.Workspace.id == models.WorkspaceMember.workspace_id)
        .where(models.WorkspaceMember.auth_user_id == current_user.id)
    )
    ws_memberships = workspace_rows.all()
    ws_ids = [row[0] for row in ws_memberships]

    # Fetch workspace-scoped RBAC data
    if workspace_roles_cached is not None:
        ws_rbac = {
            int(k): (v["roles"], v["permissions"])
            for k, v in workspace_roles_cached.items()
        }
    else:
        ws_rbac = await auth_service.AuthService.get_workspace_roles_and_permissions_db(
            session, current_user.id, ws_ids
        )

    # Build cache payload
    ws_cache: dict[str, dict] = {}
    for ws_id in ws_ids:
        ws_data = ws_rbac.get(ws_id, ([], []))
        ws_cache[str(ws_id)] = {"roles": ws_data[0], "permissions": ws_data[1]}

    await set_rbac(current_user.id, roles, permissions, workspace_roles=ws_cache, denies=denies)

    workspaces = []
    for row in ws_memberships:
        ws_id, slug, member_role = row
        ws_data = ws_rbac.get(ws_id, ([], []))
        workspaces.append(
            schemas.WorkspaceMembership(
                workspace_id=ws_id,
                slug=slug,
                role=member_role,
                rbac_roles=ws_data[0],
                rbac_permissions=ws_data[1],
            )
        )

    return schemas.TokenPayload(
        sub=current_user.id,
        email=current_user.email,
        username=current_user.username,
        is_superuser=current_user.is_superuser,
        roles=roles,
        permissions=permissions,
        workspaces=workspaces,
        denies=denies,
    )


async def _load_user_denies(session: AsyncSession, user_id: int) -> list[dict[str, str]]:
    """Per-user denied (resource, action) pairs from ``auth.user_permission_deny``."""
    rows = await session.execute(
        sa.select(models.Permission.resource, models.Permission.action)
        .join(models.UserPermissionDeny, models.UserPermissionDeny.permission_id == models.Permission.id)
        .where(models.UserPermissionDeny.user_id == user_id)
    )
    return [{"resource": resource, "action": action} for resource, action in rows.all()]


async def _resolve_access_token_user(
    session: AsyncSession,
    raw_token: str,
) -> models.AuthUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = auth_service.AuthService.decode_token(raw_token)
        user_id_str = payload.get("sub")
        token_type = payload.get("type")
        if not user_id_str or token_type != "access":
            raise credentials_exception
        user_id = int(user_id_str)
    except (HTTPException, ValueError):
        raise credentials_exception

    user = await auth_service.AuthService.get_user_with_rbac(session, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    return user
