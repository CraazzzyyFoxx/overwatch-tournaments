"""Authentication dependencies for app-service (DB-backed user resolution)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.auth_user import AuthUser


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
