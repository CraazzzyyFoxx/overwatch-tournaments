"""Shared helpers for the balancer-service typed-RPC handlers.

The gateway envelope/param-decoding plumbing this shares with the other
typed-RPC services (``q``/``q1``/``payload``/``actor``/``require_active``/
``require_id``/``dump``/``require_path_int``) now lives in
``shared.rpc.common``, the single source of truth. Everything below that is
genuinely balancer-local: the workspace-RBAC admin gate, the dict-detail
``_http_error`` variant the job API needs, and the session-less ``call``
envelope (the job API uses the Redis-backed job store + broker, not a
SQLAlchemy session).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.rpc.common import (
    actor,
    dump,
    http_error,
    payload,
    q,
    q1,
    require_active,
    require_id,
    validation_error,
)
from shared.rpc.common import (
    require_path_int as path_int,
)
from shared.rpc.identity import MissingIdentityError, ensure_workspace_permission
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code

__all__ = (
    "q",
    "q1",
    "payload",
    "actor",
    "require_workspace_permission",
    "require_member",
    "require_active",
    "active_actor",
    "require_admin_panel",
    "require_id",
    "path_int",
    "dump",
    "envelope",
    "call",
)


def require_workspace_permission(
    data: dict[str, Any], user: AuthUser, workspace_id: int, resource: str, action: str
) -> None:
    """Imperative form of ``src/core/auth.py::_require_workspace_permission``.

    Credential type is deliberately *not* consulted. An API key reaches us with
    a payload identity-service already narrowed to exactly one workspace, whose
    ``rbac_permissions`` are the requested scopes intersected with what the key's
    owner effectively holds there -- so a key can never out-reach its owner, and
    workspace RBAC is the whole gate, same as a session. ``data`` is unused; it
    stays in the signature so every handler keeps one gate call shape.
    """
    ensure_workspace_permission(user, workspace_id, resource, action)


def active_actor(data: dict[str, Any]) -> AuthUser:
    """Rehydrate identity and enforce the active check.

    Every authenticated balancer/draft endpoint resolves through
    ``get_current_active_user``, so handlers use this instead of bare ``actor``.
    """
    user = actor(data)
    require_active(user)
    return user


def require_member(user: AuthUser, workspace_id: int) -> None:
    if not user.is_workspace_member(workspace_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")


def require_admin_panel(user: AuthUser) -> None:
    """Mirror the admin balancer router-level ``require_admin_panel_access()`` gate.

    Same check + same 403 detail as ``shared.core.auth``'s dependency so the error
    body is byte-identical to the HTTP service.
    """
    if not user.has_admin_panel_access():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin panel access requires a non-read permission",
        )


def _map_error(logger: Any, label: str, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, MissingIdentityError):
        return rpc_error("unauthorized", str(exc) or "Not authenticated")
    if isinstance(exc, HTTPException):
        message, details = http_error(exc)
        return rpc_error(status_to_code(exc.status_code), message, details)
    if isinstance(exc, ValidationError):
        message, details = validation_error(exc)
        return rpc_error("unprocessable", message, details)
    logger.exception("balancer rpc failed: %s", label)
    return rpc_error("internal", "internal error")


async def envelope(
    logger: Any,
    label: str,
    op: Callable[[Any], Awaitable[Any]],
    *,
    session_factory: Callable[[], Any],
    exclude_none: bool = False,
) -> dict[str, Any]:
    """Run ``op`` inside a DB session and wrap the result/exception in the envelope."""
    try:
        async with session_factory() as session:
            return rpc_ok(dump(await op(session), exclude_none))
    except Exception as exc:  # noqa: BLE001 — mapped to the envelope below
        return _map_error(logger, label, exc)


async def call(
    logger: Any,
    label: str,
    op: Callable[[], Awaitable[Any]],
    *,
    exclude_none: bool = False,
) -> dict[str, Any]:
    """Run a session-less ``op`` and wrap the result/exception in the envelope.

    For handlers that don't touch the DB (the job API uses the Redis-backed job
    store + broker, not a SQLAlchemy session).
    """
    try:
        return rpc_ok(dump(await op(), exclude_none))
    except Exception as exc:  # noqa: BLE001 — mapped to the envelope below
        return _map_error(logger, label, exc)
