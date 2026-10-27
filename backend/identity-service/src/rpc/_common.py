"""Envelope + param helpers shared by the identity typed-RPC handlers.

Identity's gateway contract differs from ``shared.rpc.common``: most methods
take a flat ``data`` dict rather than the ``{payload, query, identity}``
envelope, and the caller arrives as a bearer ``data["access_token"]`` this
service resolves itself instead of a gateway-injected identity block. So these
stay identity-local; the reply envelope itself
(``rpc_ok``/``rpc_error``/``status_to_code``) is the shared one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.common import integrity_error
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code
from src.core import db
from src.services.token_validation import token_validation

__all__ = (
    "envelope",
    "envelope_session",
    "with_active_user",
    "with_active_principal",
    "opt_int",
    "require_int",
)


def _validation_detail(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "validation error"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    msg = first.get("msg", "invalid value")
    return f"{loc}: {msg}" if loc else msg


async def envelope(
    logger: Any,
    label: str,
    op: Callable[[], Awaitable[Any]],
    *,
    failure: str = "internal error",
) -> dict:
    """Run an RPC body and map every outcome onto the reply envelope.

    One place decides how a domain error, a schema error and an unexpected crash
    each look on the wire, so no handler can drift from the mapping the gateway
    asserts on.
    """
    try:
        return rpc_ok(await op())
    except ValidationError as exc:
        return rpc_error("unprocessable", _validation_detail(exc))
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception as exc:
        if (mapped := integrity_error(exc)) is not None:
            code, message, details = mapped
            logger.warning(f"{label} RPC: {message} ({details.get('constraint')})")
            return rpc_error(code, message, details)
        # Defensive worker guard.
        logger.exception(f"{label} RPC failed")
        return rpc_error("internal", failure)


async def envelope_session(
    logger: Any,
    label: str,
    op: Callable[[Any], Awaitable[Any]],
    *,
    failure: str = "internal error",
) -> dict:
    """``envelope`` with a database session scoped to the call."""

    async def run() -> Any:
        async with db.async_session_maker() as session:
            return await op(session)

    return await envelope(logger, label, run, failure=failure)


async def with_active_user(
    logger: Any,
    access_token: Any,
    op: Callable[[Any, Any], Awaitable[Any]],
    *,
    label: str = "authenticated",
) -> dict:
    """Resolve the active user from a bearer access token, run op, map errors.

    Shared by every authenticated RPC method. A missing or non-string token is
    rejected before any database work — the gateway only omits it for anonymous
    callers, so this is not an error worth a round trip.
    """
    if not access_token or not isinstance(access_token, str):
        return rpc_error("forbidden", "Not authenticated")

    async def run(session: Any) -> Any:
        user = await token_validation.resolve_active_user(session, access_token)
        return await op(session, user)

    return await envelope_session(logger, label, run)


async def with_active_principal(
    logger: Any,
    access_token: Any,
    op: Callable[[Any, Any, Any], Awaitable[Any]],
    *,
    label: str = "authenticated",
) -> dict:
    """``with_active_user`` for the few reads an API key may also perform.

    ``op`` additionally receives the API-key descriptor the caller presented, or
    ``None`` for a session credential — a handler that only makes sense for one
    of the two decides that itself, since "no current key" is a 403 here and a
    non-answer everywhere else.

    The JWT-only default of ``with_active_user`` is the boundary keeping keys
    away from session, credential and RBAC mutations; every widening goes
    through this helper, so it stays one grep away.
    """
    if not access_token or not isinstance(access_token, str):
        return rpc_error("forbidden", "Not authenticated")

    async def run(session: Any) -> Any:
        user, api_key = await token_validation.resolve_active_principal(session, access_token)
        return await op(session, user, api_key)

    return await envelope_session(logger, label, run)


def opt_int(data: dict, key: str) -> int | None:
    raw = data.get(key)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{key} must be an integer")


def require_int(data: dict, key: str) -> int:
    value = opt_int(data, key)
    if value is None:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return value
