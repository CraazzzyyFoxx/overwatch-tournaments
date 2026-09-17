"""Authentication dependencies for balancer-service.

Stateless user resolution still relies on the auth-service token payload;
workspace-scoped admin access is enforced imperatively at each RPC handler via
``rpc/_common.py::require_workspace_permission`` after resolving the resource's
workspace id with one of the ``_get_*_workspace_id`` helpers below.

``_get_tournament_workspace_id`` re-exports ``shared.rbac.workspace_lookup``
(identical body to tournament-service's non-underscore-named version there);
everything else here is genuinely balancer-local.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.models.identity.rbac import Permission, Role
from shared.rbac.workspace_lookup import (
    get_tournament_workspace_id as _get_tournament_workspace_id,  # noqa: F401 -- re-exported for rpc/admin.py, rpc/binary.py, rpc/draft.py
)
from shared.repository import BalancerBalanceRepository
from shared.repository.draft import DraftPickRepository, DraftSessionRepository

_drafts = DraftSessionRepository()
_draft_picks = DraftPickRepository()
_balances = BalancerBalanceRepository()


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
    return user


async def _get_balance_workspace_id(session: AsyncSession, balance_id: int) -> int:
    workspace_id = await _balances.get_workspace_id(session, balance_id)
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Balance not found",
        )
    return int(workspace_id)


async def _get_draft_session_workspace_id(session: AsyncSession, session_id: int) -> int:
    workspace_id = await _drafts.get_workspace_id(session, session_id)
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft session not found")
    return int(workspace_id)


async def _get_pick_workspace_id(session: AsyncSession, pick_id: int) -> int:
    workspace_id = await _draft_picks.get_workspace_id(session, pick_id)
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft pick not found")
    return int(workspace_id)
