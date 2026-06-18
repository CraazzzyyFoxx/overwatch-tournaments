"""Rehydrate an AuthUser from the gateway-injected identity payload.

The Go gateway validates the JWT locally and resolves RBAC (via identity-svc),
then injects the resolved identity into each RPC request. Headless workers
rehydrate a transient ``AuthUser`` from that payload and check permissions
imperatively — no token parsing, no DB lookup.

Trust model: the RPC subscriber is reachable only over RabbitMQ from the gateway,
so the injected identity is implicitly trusted (no external path can forge it).

The payload shape matches what identity-svc's ``validate_token`` returns and what
the per-service ``_resolve_user_from_db`` consumes:

    {
      "user_id": int,            # or "sub"
      "is_superuser": bool,
      "is_active": bool,
      "roles": [str, ...],                       # global role names
      "permissions": [{"resource","action"}],    # global permissions
      "workspaces": [                            # membership
        {"workspace_id": int, "role": str,
         "rbac_roles": [...], "rbac_permissions": [{"resource","action"}]}
      ]
    }
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from shared.models.auth_user import AuthUser

__all__ = ("rehydrate_user", "ensure_workspace_permission", "ensure_admin_panel_access", "MissingIdentityError")


class MissingIdentityError(Exception):
    """Raised when an authenticated RPC method gets no identity payload."""


def _payload_user_id(identity: dict[str, Any]) -> int:
    raw = identity.get("user_id", identity.get("sub"))
    try:
        user_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise MissingIdentityError("identity has no valid user_id") from exc
    if user_id <= 0:
        raise MissingIdentityError("identity has no valid user_id")
    return user_id


def rehydrate_user(identity: dict[str, Any] | None) -> AuthUser:
    """Build a transient AuthUser whose permission checks use the cached RBAC.

    No DB access: every AuthUser permission method falls back to the in-memory
    cache set here and only touches ORM relationships when the cache is absent.
    """
    if not identity or not isinstance(identity, dict):
        raise MissingIdentityError("no identity payload")

    user = AuthUser()
    user.id = _payload_user_id(identity)
    user.is_superuser = bool(identity.get("is_superuser", False))
    user.is_active = bool(identity.get("is_active", True))

    workspaces = identity.get("workspaces") or []
    workspace_rbac: dict[int, dict] = {}
    for ws in workspaces:
        ws_id = ws.get("workspace_id")
        if ws_id is not None:
            workspace_rbac[int(ws_id)] = {
                "roles": ws.get("rbac_roles", []),
                "permissions": ws.get("rbac_permissions", []),
            }
    user.set_rbac_cache(
        role_names=identity.get("roles", []),
        permissions=identity.get("permissions", []),
        workspaces=workspaces,
        workspace_rbac=workspace_rbac,
    )
    return user


def ensure_workspace_permission(user: AuthUser, workspace_id: int, resource: str, action: str) -> None:
    """Imperative form of the route ``_require_workspace_permission`` dependency."""
    if not user.has_workspace_permission(workspace_id, resource, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied for workspace {workspace_id}: {resource}.{action} required",
        )


def ensure_admin_panel_access(user: AuthUser, workspace_id: int | None = None) -> None:
    """Imperative form of the router-level ``require_admin_panel_access`` gate."""
    if not user.has_admin_panel_access(workspace_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin panel access required",
        )
