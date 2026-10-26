"""Shared helpers for tournament-service RPC subscriber modules.

Param decoding is ``shared.rpc.common`` — the same helpers every other
typed-RPC worker uses, including the exception→envelope mapping
(``http_error``/``validation_error``/``integrity_error``), so an
``ApiHTTPException``'s per-item ``code``/``field`` reaches clients under
``details["fields"]`` instead of being flattened into a Python repr.
``_run``/``_read`` stay local: ``_run`` does not dump, and ``_read`` dumps only
after its session is closed, both of which ``shared.rpc.common.envelope`` would
change.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from shared import models
from shared.core import http_status as status
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import DISCIPLINES
from shared.repository import UserRepository
from shared.rpc.common import (
    actor as _identity,
)
from shared.rpc.common import (
    dump,
    http_error,
    integrity_error,
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
    "_actor_player_id",
    "_bool",
    "_dump",
    "_identity",
    "_optional_discipline",
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


def _optional_discipline(data: dict[str, Any]) -> str | None:
    """A list read's optional game (spec §8.1): ``?discipline=`` absent, empty or ``all`` is every game (``None``).

    Any other value must be an installed game: an unknown code is a 404 ``discipline_not_installed``, never every
    game's rows under a bogus label.
    """
    raw = _q1(data, "discipline", str, None)
    if not isinstance(raw, str) or not raw.strip() or raw == "all":
        return None
    if raw not in DISCIPLINES:
        raise ApiHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[ApiExc(code="discipline_not_installed", msg=f"Discipline {raw!r} is not installed")],
        )
    return raw


_user_repo = UserRepository()


async def _actor_player_id(session: Any, user: models.AuthUser) -> int | None:
    """Translate the caller's auth id into the ``players.user`` id a result audit stores.

    ``EncounterResultAudit.actor_user_id`` is a FK to ``players.user``, not to
    ``auth.user``: an auth id passed straight through would name whichever
    unrelated player holds that number. The captain paths store the linked player
    id (``_resolve_captain_identity``); this is the same translation at the admin
    boundary.

    ``None`` -- an account with no linked player -- reads as a machine actor.
    """
    return await _user_repo.get_id_by_auth_user_id(session, user.id)


def _dump(obj: Any, *, exclude_none: bool = False) -> Any:
    return dump(obj, exclude_none)


async def _run(logger: Any, op: Callable[[Any], Awaitable[Any]]) -> dict[str, Any]:
    """Session-per-message envelope with identity/HTTP/validation/constraint mapping.

    The subscriber's ``op`` returns raw (already dumped) data; errors never leak
    internals to the client — the traceback goes to the server log only.
    """
    try:
        async with db.async_session_maker() as session:
            return rpc_ok(await op(session))
    except Exception as exc:
        return _error(logger, exc, "tournament rpc failed")


async def _read(logger: Any, op: Callable[[Any], Awaitable[Any]], *, exclude_none: bool = False) -> dict[str, Any]:
    """Read-path envelope: like ``_run`` but dumps the result itself.

    The dump runs after the session block, so the connection is back in the pool
    before the CPU-bound serialization. Every ``_read`` op returns pydantic
    models or plain dicts already built inside the session, never ORM rows that
    a dump could lazy-load from.

    ``exclude_none`` is part of each subject's wire contract: True for
    get_one/get_stages/get_standings; False (keep nulls) for statistics.
    """
    try:
        async with db.async_session_maker() as session:
            result = await op(session)
        return rpc_ok(_dump(result, exclude_none=exclude_none))
    except Exception as exc:
        return _error(logger, exc, "tournament read rpc failed")


def _error(logger: Any, exc: Exception, label: str) -> dict[str, Any]:
    if isinstance(exc, MissingIdentityError):
        return rpc_error("unauthorized", str(exc) or "Not authenticated")
    if isinstance(exc, HTTPException):
        message, details = http_error(exc)
        return rpc_error(status_to_code(exc.status_code), message, details)
    if isinstance(exc, ValidationError):
        message, details = validation_error(exc)
        return rpc_error("unprocessable", message, details)
    if (mapped := integrity_error(exc)) is not None:
        # A constraint the handler did not pre-check (a lost race, a dangling reference): 409/422, not a server fault.
        code, message, details = mapped
        return rpc_error(code, message, details)
    # Defensive worker guard: the traceback goes to the server log only.
    logger.exception(label)
    return rpc_error("internal", "internal error")
