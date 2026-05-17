from __future__ import annotations

from typing import Any

from fastapi import WebSocket
from loguru import logger
from shared.clients.auth_client import AuthServiceUnavailable
from shared.models.auth_user import AuthUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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


async def _resolve_user_from_db(
    user_id: int,
    payload: dict[str, Any],
    *,
    session: AsyncSession,
) -> AuthUser | None:
    result = await session.execute(select(AuthUser).where(AuthUser.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return None

    workspace_rbac: dict[int, dict] = {}
    for workspace in payload.get("workspaces", []):
        workspace_id = workspace.get("workspace_id")
        if workspace_id is not None:
            workspace_rbac[int(workspace_id)] = {
                "roles": workspace.get("rbac_roles", []),
                "permissions": workspace.get("rbac_permissions", []),
            }
    user.set_rbac_cache(
        role_names=payload.get("roles", []),
        permissions=payload.get("permissions", []),
        workspaces=payload.get("workspaces", []),
        workspace_rbac=workspace_rbac,
    )
    return user


async def get_websocket_user_optional(
    websocket: WebSocket,
    session: AsyncSession,
) -> AuthUser | None:
    token = _get_websocket_token(websocket)
    if not token:
        return None

    auth_client = getattr(websocket.app.state, "auth_client", None)
    if auth_client is None:
        logger.warning("WebSocket auth requested but auth_client is not configured")
        return None

    try:
        payload = await auth_client.validate_token(token)
    except AuthServiceUnavailable:
        logger.warning("Auth service unavailable while resolving WebSocket user")
        return None

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
