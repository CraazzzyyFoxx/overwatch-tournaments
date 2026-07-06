"""Shared helpers for the analytics typed-RPC handlers.

Mirrors the tournament-service ``src/rpc`` envelope/param helpers so analytics
reads, mutations, and job-control all decode the gateway request
(``data["id"]`` / ``data["query"][k]=[...]`` / ``data["payload"]`` /
``data["identity"]``) and emit the ``{ok,data,error}`` envelope uniformly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.rpc.identity import MissingIdentityError, rehydrate_user
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code


def identity_user_id(data: dict[str, Any]) -> int | None:
    identity = data.get("identity") or {}
    raw = identity.get("user_id", identity.get("sub"))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def q(data: dict[str, Any], key: str) -> list[str] | None:
    vals = (data.get("query") or {}).get(key)
    if vals is None:
        return None
    return vals if isinstance(vals, list) else [vals]


def q1(data: dict[str, Any], key: str, cast: Callable[[str], Any] = str, default: Any = None) -> Any:
    vals = q(data, key)
    if not vals:
        return default
    try:
        return cast(vals[0])
    except (TypeError, ValueError):
        return default


def qbool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def payload(data: dict[str, Any]) -> dict[str, Any]:
    body = data.get("payload")
    return body if isinstance(body, dict) else {}


def actor(data: dict[str, Any]) -> AuthUser:
    """Rehydrate the gateway-injected identity into a transient AuthUser.

    Raises ``MissingIdentityError`` if the gateway did not inject identity
    (the envelope helper maps that to ``unauthorized``).
    """
    return rehydrate_user(data.get("identity"))


def require_active(user: AuthUser) -> None:
    """Mirror ``get_current_active_user``: reject inactive users with 403."""
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")


def require_permission(user: AuthUser, resource: str, action: str) -> None:
    """Global permission check mirroring ``shared.core.auth.require_permission``.

    The HTTP routes chain ``get_current_active_user`` (active check) then
    ``current_user.has_permission`` (NOT workspace-scoped) for
    ``analytics.read`` / ``analytics.update``; replicate both 403 bodies in order.
    """
    require_active(user)
    if not user.has_permission(resource, action):
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: {resource}.{action} required",
        )


def require_id(data: dict[str, Any]) -> int:
    try:
        return int(data["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="id is required") from exc


def require_query_int(data: dict[str, Any], key: str) -> int:
    value = q1(data, key, int)
    if value is None:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return value


def dump(obj: Any, exclude_none: bool) -> Any:
    if obj is None:
        return None
    if isinstance(obj, list):
        return [dump(x, exclude_none) for x in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=exclude_none)
    return obj


def _detail_message(exc: HTTPException) -> str:
    """Flatten an HTTPException detail into a clean string.

    ``ApiHTTPException`` (the v1 read flows) carries ``detail`` as a
    ``list[{msg, code}]``; the gateway emits ``{"detail": "<string>"}`` either
    way, so join the ``msg`` fields instead of leaking a Python list repr. The
    HTTP status is preserved via ``status_to_code(exc.status_code)``; only the
    per-item machine ``code`` is dropped (the frontend tolerates this).
    """
    detail = exc.detail
    if isinstance(detail, list):
        msgs = [str(d.get("msg")) for d in detail if isinstance(d, dict) and d.get("msg")]
        return "; ".join(msgs) if msgs else "error"
    return str(detail)


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
    except MissingIdentityError as exc:
        return rpc_error("unauthorized", str(exc) or "Not authenticated")
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), _detail_message(exc))
    except ValidationError as exc:
        return rpc_error("unprocessable", str(exc))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("analytics rpc failed: %s", label)
        return rpc_error("internal", "internal error")
