"""Authentication dependencies for app-service (DB-backed user resolution)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.auth import create_auth_dependencies
from shared.models.auth_user import AuthUser

from src.core import db


async def _resolve_user_from_db(
    user_id: int, payload: dict[str, Any], *, session: AsyncSession
) -> AuthUser | None:
    result = await session.execute(
        select(AuthUser).where(AuthUser.id == user_id)
    )
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
