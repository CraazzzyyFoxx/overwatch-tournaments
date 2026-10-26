"""Shared helpers for the balancer-service typed-RPC handlers.

Re-exports the gateway envelope/param-decoding plumbing from ``shared.rpc.common``
and adds the balancer-local gates plus the session-less ``call`` envelope.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from pydantic import ValidationError

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.rpc.common import (
    actor,
    dump,
    http_error,
    integrity_error,
    payload,
    q,
    q1,
    require_active,
    require_id,
    validation_error,
)
from shared.rpc.common import (
    envelope as _envelope,
)
from shared.rpc.common import (
    require_path_int as path_int,
)
from shared.rpc.identity import MissingIdentityError
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code

__all__ = (
    "q",
    "q1",
    "payload",
    "actor",
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


def active_actor(data: dict[str, Any]) -> AuthUser:
    """Rehydrate identity and reject an inactive account; authenticated handlers use this, not bare ``actor``."""
    user = actor(data)
    require_active(user)
    return user


def require_member(user: AuthUser, workspace_id: int) -> None:
    if not user.is_workspace_member(workspace_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")


def require_admin_panel(user: AuthUser) -> None:
    """Raise 403 unless ``user`` has admin-panel access."""
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
    if (mapped := integrity_error(exc)) is not None:
        code, message, details = mapped
        logger.warning("balancer rpc {}: {} ({})", label, message, details.get("constraint"))
        return rpc_error(code, message, details)
    logger.exception("balancer rpc failed: {}", label)
    return rpc_error("internal", "internal error")


envelope = partial(_envelope, service="balancer")


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
