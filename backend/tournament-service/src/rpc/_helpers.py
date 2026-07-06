"""Shared helpers for tournament-service RPC subscriber modules.

These were previously copy-pasted into every rpc module (reads, public_rpc,
admin_misc, registration_admin, integrations, stage_admin) and had already
drifted (``_dump`` existed with three different signatures). This module is the
single source of truth; the names keep their historical leading underscore so
subscriber bodies stay unchanged.

Envelope conventions (mirrors the Go gateway contract):
- body arrives under ``data["payload"]``; path params at the top level;
  query params under ``data["query"]`` as ``{key: [values]}``.
- actor identity is ONLY read from the gateway-stamped ``data["identity"]``
  blob (never from the client-controlled payload).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import MissingIdentityError, rehydrate_user
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code
from src import models
from src.core import db

__all__ = (
    "_bool",
    "_dump",
    "_identity",
    "_path_int",
    "_payload",
    "_q",
    "_q1",
    "_read",
    "_require_id",
    "_require_q1",
    "_run",
)


def _identity(data: dict[str, Any]) -> models.AuthUser:
    """Rehydrate the gateway-injected identity into a transient AuthUser."""
    return rehydrate_user(data.get("identity"))


def _payload(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("payload") or {}


def _require_id(data: dict[str, Any]) -> int:
    try:
        return int(data["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="id is required") from exc


def _path_int(data: dict[str, Any], name: str) -> int:
    raw = data.get(name)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{name} is required") from exc


def _q(data: dict[str, Any], key: str) -> list[str] | None:
    vals = (data.get("query") or {}).get(key)
    if vals is None:
        return None
    return vals if isinstance(vals, list) else [vals]


def _q1(data: dict[str, Any], key: str, cast: Callable[[str], Any] = str, default: Any = None) -> Any:
    vals = _q(data, key)
    if not vals:
        return default
    try:
        return cast(vals[0])
    except (TypeError, ValueError):
        return default


def _require_q1(data: dict[str, Any], key: str, cast: Callable[[str], Any] = str) -> Any:
    val = _q1(data, key, cast)
    if val is None:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return val


def _bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def _dump(obj: Any, *, exclude_none: bool = False) -> Any:
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_dump(x, exclude_none=exclude_none) for x in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=exclude_none)
    return obj


async def _run(logger: Any, op: Callable[[Any], Awaitable[Any]]) -> dict[str, Any]:
    """Session-per-message envelope with identity/HTTP/validation mapping.

    The subscriber's ``op`` returns raw (already dumped) data; errors never leak
    internals to the client — the traceback goes to the server log only.
    """
    try:
        async with db.async_session_maker() as session:
            return rpc_ok(await op(session))
    except MissingIdentityError as exc:
        return rpc_error("unauthorized", str(exc) or "Not authenticated")
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except ValidationError as exc:
        return rpc_error("unprocessable", str(exc))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("tournament rpc failed")
        return rpc_error("internal", "internal error")


async def _read(logger: Any, op: Callable[[Any], Awaitable[Any]], *, exclude_none: bool = False) -> dict[str, Any]:
    """Read-path envelope: like ``_run`` but dumps the result itself.

    ``exclude_none`` must match each route's ``response_model_exclude_none``:
    True for get_one/get_stages/get_standings; False (keep nulls) for
    statistics/OWAL.
    """
    try:
        async with db.async_session_maker() as session:
            return rpc_ok(_dump(await op(session), exclude_none=exclude_none))
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except ValidationError as exc:
        return rpc_error("unprocessable", str(exc))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("tournament read rpc failed")
        return rpc_error("internal", "internal error")
