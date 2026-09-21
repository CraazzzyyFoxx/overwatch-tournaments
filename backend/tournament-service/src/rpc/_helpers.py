"""Shared helpers for tournament-service RPC subscriber modules.

Param decoding is ``shared.rpc.common`` — the same helpers every other
typed-RPC worker uses, including the exception→envelope mapping
(``http_error``/``validation_error``), so an ``ApiHTTPException``'s per-item
``code``/``field`` reaches clients under ``details["fields"]`` instead of being
flattened into a Python repr. ``_run``/``_read`` stay local: they do not dump
(``_run``) or do not map ``MissingIdentityError`` (``_read``), which
``shared.rpc.common.envelope`` would change.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.common import (
    actor as _identity,
)
from shared.rpc.common import (
    dump,
    http_error,
    validation_error,
)
from shared.rpc.common import (
    payload as _payload,
)
from shared.rpc.common import (
    q as _q,
)
from shared.rpc.common import (
    q1 as _q1,
)
from shared.rpc.common import (
    qbool as _bool,
)
from shared.rpc.common import (
    require_id as _require_id,
)
from shared.rpc.common import (
    require_path_int as _path_int,
)
from shared.rpc.identity import MissingIdentityError
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code
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


def _require_q1(data: dict[str, Any], key: str, cast: Callable[[str], Any] = str) -> Any:
    val = _q1(data, key, cast)
    if val is None:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return val


def _dump(obj: Any, *, exclude_none: bool = False) -> Any:
    return dump(obj, exclude_none)


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
        message, details = http_error(exc)
        return rpc_error(status_to_code(exc.status_code), message, details)
    except ValidationError as exc:
        message, details = validation_error(exc)
        return rpc_error("unprocessable", message, details)
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
        message, details = http_error(exc)
        return rpc_error(status_to_code(exc.status_code), message, details)
    except ValidationError as exc:
        message, details = validation_error(exc)
        return rpc_error("unprocessable", message, details)
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("tournament read rpc failed")
        return rpc_error("internal", "internal error")
