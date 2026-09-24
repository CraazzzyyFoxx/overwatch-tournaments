"""Shared gateway-envelope + param-decoding helpers for typed-RPC handlers.

Every FastStream-RPC service (app, balancer, analytics, parser, stream) had a
near-identical ``src/rpc/_common.py`` reimplementing the same plumbing for
decoding the gateway request (``data["id"]`` / ``data["query"][k]=[...]`` /
``data["payload"]`` / ``data["identity"]``) and emitting the one
``{ok,data,error}`` envelope the gateway understands — several of them said so
explicitly in their own docstrings ("Mirrors the tournament-service ...
helpers"). This is the single source of truth; each service's local
``_common.py`` now just re-exports the subset it needs, so existing
``from . import _common as c`` / ``from src.rpc import _common as c`` call
sites are unaffected.

``dump`` defaults to ``exclude_none=False`` — byte-identical to FastAPI's
default serialization. Routes that set ``response_model_exclude_none=True``
must pass ``exclude_none=True`` to ``envelope`` to preserve their HTTP contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.rpc.identity import MissingIdentityError, rehydrate_user, rehydrate_user_optional
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code

__all__ = (
    "identity_user_id",
    "q",
    "q1",
    "qbool",
    "payload",
    "actor",
    "optional_actor",
    "require_active",
    "require_permission",
    "require_superuser",
    "require_id",
    "require_query_int",
    "require_path_int",
    "dump",
    "field_entry",
    "http_error",
    "validation_error",
    "retry_after_seconds",
    "envelope",
)


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


def optional_actor(data: dict[str, Any]) -> AuthUser | None:
    """Rehydrate identity for ``AuthNone``/``AuthOptional`` reads; None when anonymous."""
    return rehydrate_user_optional(data.get("identity"))


def require_active(user: AuthUser) -> None:
    """Mirror ``get_current_active_user``: reject inactive users with 403."""
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")


def require_permission(user: AuthUser, resource: str, action: str) -> None:
    """Global (non-workspace-scoped) permission check.

    Mirrors ``shared.core.auth.require_permission``: the HTTP routes chain
    ``get_current_active_user`` (active check) then ``current_user.has_permission``
    for global resources; replicate both 403 bodies in order.
    """
    require_active(user)
    if not user.has_permission(resource, action):
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: {resource}.{action} required",
        )


def require_superuser(user: AuthUser) -> None:
    """Mirror ``get_current_superuser``: reject non-superusers with 403."""
    require_active(user)
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="The user doesn't have enough privileges")


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


def require_path_int(data: dict[str, Any], key: str) -> int:
    """Read a ``RouteSpec.Path`` param, which the gateway copies to the body by name.

    Distinct from ``require_query_int``: ``{tournament_id}`` arrives as
    ``data["tournament_id"]``, not under ``data["query"]``.
    """
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} is required") from exc


def dump(obj: Any, exclude_none: bool) -> Any:
    if obj is None:
        return None
    if isinstance(obj, list):
        return [dump(x, exclude_none) for x in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=exclude_none)
    return obj


def _loc_path(loc: Any) -> str | None:
    """Dotted field path from a pydantic ``loc``, minus the envelope wrappers.

    ``body``/``payload`` are artefacts of where the value was carried, not part of
    the field's name as the client knows it.
    """
    if not isinstance(loc, (list, tuple)):
        return str(loc) if loc else None
    return ".".join(str(p) for p in loc if p not in ("body", "payload")) or None


def field_entry(item: dict[str, Any]) -> dict[str, Any]:
    """One ``details["fields"]`` entry from an error item.

    Accepts both dialects that reach here: ``ApiExc`` items (``msg``/``code``,
    sometimes ``field``) and pydantic items (``loc``/``msg``/``type``).
    """
    field = _loc_path(item.get("loc")) or item.get("field")
    return {
        "field": str(field) if field else None,
        "msg": str(item.get("msg") or "invalid value"),
        "code": str(item.get("code") or item.get("type") or "error"),
    }


def retry_after_seconds(exc: HTTPException) -> int | None:
    """Seconds from a ``Retry-After`` header, which a worker cannot itself emit.

    Rate limiters set the header because the same exception is also raised on the
    HTTP path; over RPC only the envelope crosses the queue, so the value has to
    ride ``details`` for the gateway to put the header back.
    """
    headers = getattr(exc, "headers", None)
    if not isinstance(headers, dict):
        return None
    raw = next((v for k, v in headers.items() if str(k).lower() == "retry-after"), None)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def http_error(exc: HTTPException) -> tuple[str, dict[str, Any]]:
    """Split an HTTPException into a human ``message`` and machine ``details``.

    Three detail dialects reach here:

    ``ApiHTTPException`` (the v1 read flows) carries ``detail`` as a
    ``list[{msg, code}]``; a bare ``BaseAPIException`` raised with
    ``detail=[ApiExc(...)]`` (the FFA + game-correction sites) carries the models
    themselves, so items are dumped here before being read. Joining the ``msg``
    fields is what a human reads, but the per-item ``code`` is the only thing a
    client can branch on -- it used to be dropped here, so it now rides
    ``details["fields"]`` instead.

    A ``dict`` detail is either one item (``msg``/``code``) or an attribute bag:
    a ``code`` plus whatever the refusal is about (``limit_name``, ``scope``,
    ``limit``). Either way it becomes ONE ``fields`` entry rather than being
    merged at the top of ``details``: ``details["code"]`` would be silently
    dropped there, because the gateway writes the envelope's status-derived code
    last and deliberately lets it win (a worker must not be able to rewrite the
    key clients branch on). Without this branch the dict reached clients as a
    Python repr in ``message`` and every attribute was lost -- which is what
    ``shared.quota``'s refusals depend on not happening.

    Anything else is a plain string.
    """
    detail = exc.detail
    details: dict[str, Any] = {}
    if isinstance(detail, list):
        items = [d.model_dump(mode="json") if hasattr(d, "model_dump") else d for d in detail]
        items = [d for d in items if isinstance(d, dict)]
        if items:
            details["fields"] = [field_entry(d) for d in items]
        msgs = [str(d.get("msg")) for d in items if d.get("msg")]
        message = "; ".join(msgs) if msgs else "error"
    elif isinstance(detail, dict):
        if detail.get("msg"):
            message = str(detail["msg"])
            details["fields"] = [field_entry(detail)]
        else:
            code = str(detail.get("code") or "error")
            message = code.replace("_", " ")
            entry: dict[str, Any] = {"field": detail.get("field"), "msg": message, "code": code}
            entry.update({k: v for k, v in detail.items() if k not in ("code", "field", "msg")})
            details["fields"] = [entry]
    else:
        message = str(detail)
    retry_after = retry_after_seconds(exc)
    if retry_after is not None:
        details["retry_after"] = retry_after
    return message, details


def validation_error(exc: ValidationError) -> tuple[str, dict[str, Any]]:
    """Split a pydantic ValidationError into a human summary + per-field details.

    ``str(exc)`` is a multi-line developer repr (model name, doc urls, echoed
    input) and used to be shipped to clients verbatim as the message. Its actual
    content -- which field, why -- belongs in ``details["fields"]``, where a
    client can render it per input instead of parsing prose.
    """
    errors = exc.errors()
    if not errors:
        return "validation error", {}
    fields = [field_entry(e) for e in errors]
    first = fields[0]
    message = f"{first['field']}: {first['msg']}" if first["field"] else first["msg"]
    return message, {"fields": fields}


async def envelope(
    logger: Any,
    label: str,
    op: Callable[[Any], Awaitable[Any]],
    *,
    session_factory: Callable[[], Any],
    exclude_none: bool = False,
    service: str = "rpc",
) -> dict[str, Any]:
    """Run ``op`` inside a DB session and wrap the result/exception in the envelope.

    ``service`` only affects the defensive-guard log line (``"<service> rpc
    failed: <label>"``) — each service's local ``_common.py`` binds it via
    ``functools.partial`` so existing log greps/alerts keep matching.
    """
    try:
        async with session_factory() as session:
            return rpc_ok(dump(await op(session), exclude_none))
    except MissingIdentityError as exc:
        return rpc_error("unauthorized", str(exc) or "Not authenticated")
    except HTTPException as exc:
        message, details = http_error(exc)
        return rpc_error(status_to_code(exc.status_code), message, details)
    except ValidationError as exc:
        message, details = validation_error(exc)
        return rpc_error("unprocessable", message, details)
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("%s rpc failed: %s", service, label)
        return rpc_error("internal", "internal error")
