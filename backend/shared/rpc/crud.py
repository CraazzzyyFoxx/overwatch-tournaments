"""Config-driven generic CRUD-over-RPC engine.

Uniform admin CRUD (fetch -> validate -> mutate -> side-effects -> serialize)
collapses to one ``EntityConfig`` row per entity instead of a hand-written RPC
handler. A service builds a ``CrudDispatcher`` from its registry + session factory
and wires the five generic subscribers under its own queue prefix, e.g.::

    dispatcher = CrudDispatcher(REGISTRY, db.async_session_maker)

    @broker.subscriber("rpc.tournament.admin.update")
    async def _(data: dict, msg) -> dict:
        return await dispatcher.do_update(data)

Each request carries ``{entity, id?, payload?, identity, query?}``. The dispatcher
rehydrates the user, resolves the owning workspace, checks the permission, then
either delegates to the existing service function (``service_*`` hook, which owns
its commit + side-effects) or runs a generic ``BaseRepository`` path (engine owns
the commit). Returns the ``{ok,data,error}`` envelope.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from shared.core.errors import BaseAPIException as HTTPException
from shared.core import http_status as status
from loguru import logger
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.db import Base
from shared.repository.base import BaseRepository
from shared.rpc.identity import MissingIdentityError, ensure_workspace_permission, rehydrate_user
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code

__all__ = ("EntityConfig", "CrudDispatcher")

# A session factory is anything callable returning an async-context-manager that
# yields an AsyncSession (e.g. SQLAlchemy ``async_sessionmaker``).
SessionFactory = Callable[[], Any]
Serializer = Callable[[AsyncSession, Any], Awaitable[Any]]
WsFromId = Callable[[AsyncSession, int], Awaitable[int]]
WsFromData = Callable[[AsyncSession, dict[str, Any]], Awaitable[int]]

# Map an action verb to the RBAC action checked against ``permission_resource``.
_ACTION_PERMISSION = {"create": "create", "get": "read", "update": "update", "delete": "delete", "list": "read"}


def _validation_detail(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "validation error"
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ()) if p not in ("body", "payload"))
    msg = first.get("msg", "invalid value")
    return f"{loc}: {msg}" if loc else msg


def _detail_message(exc: HTTPException) -> str:
    """Flatten an HTTPException detail into a clean string.

    ``ApiHTTPException`` normalizes ``detail`` to a ``list[{msg, code}]``; the
    gateway emits ``{"detail": "<string>"}`` either way, so join the ``msg``
    fields instead of leaking a Python list repr (the per-item ``code`` is
    dropped). Plain string details pass through unchanged.
    """
    detail = exc.detail
    if isinstance(detail, list):
        msgs = [str(d.get("msg")) for d in detail if isinstance(d, dict) and d.get("msg")]
        return "; ".join(msgs) if msgs else "error"
    return str(detail)


@dataclass(frozen=True)
class EntityConfig:
    """Declarative description of one CRUD entity.

    ``service_*`` hooks delegate to the existing service function (which keeps its
    side-effects + commit). When a hook is absent the engine runs a generic
    ``BaseRepository`` path and owns the commit. NEVER both — that is the
    commit-ownership rule.

    ``public_read=True`` marks an entity whose ``get``/``list`` are public: the
    engine skips identity rehydration + workspace permission for those actions
    (global reference data with no owning workspace, e.g. heroes/maps). Writes
    are never public — ``create``/``update``/``delete`` always authenticate.
    """

    entity: str
    model: type[Base]
    permission_resource: str
    serializer: Serializer
    public_read: bool = False
    create_schema: type[BaseModel] | None = None
    update_schema: type[BaseModel] | None = None
    resolve_ws_from_id: WsFromId | None = None       # get / update / delete (id from data["id"])
    resolve_ws_for_create: WsFromData | None = None  # create (workspace from payload/path)
    resolve_ws_for_list: WsFromData | None = None    # list (workspace from query/path)
    # Hooks receive the full request ``data`` dict (3rd/4th arg) so adapters can
    # read path params (e.g. a create nested under /stages/tournament/{id}).
    service_create: Callable[[AsyncSession, BaseModel, dict], Awaitable[Any]] | None = None
    service_get: Callable[[AsyncSession, int, dict], Awaitable[Any]] | None = None
    service_update: Callable[[AsyncSession, int, BaseModel, dict], Awaitable[Any]] | None = None
    service_delete: Callable[[AsyncSession, int, dict], Awaitable[None]] | None = None
    list_fn: Callable[[AsyncSession, dict[str, Any]], Awaitable[Any]] | None = None
    not_found_detail: str = "Not found"
    actions: frozenset[str] = frozenset({"create", "get", "update", "delete"})

    @property
    def repo(self) -> BaseRepository:
        return BaseRepository(self.model)


class CrudDispatcher:
    def __init__(self, registry: dict[str, EntityConfig], session_factory: SessionFactory) -> None:
        self._registry = registry
        self._session_factory = session_factory

    # --- public RPC entrypoints ---------------------------------------------

    async def do_create(self, data: dict[str, Any]) -> dict[str, Any]:
        return await self._envelope(lambda: self._create(data or {}))

    async def do_get(self, data: dict[str, Any]) -> dict[str, Any]:
        return await self._envelope(lambda: self._get(data or {}))

    async def do_update(self, data: dict[str, Any]) -> dict[str, Any]:
        return await self._envelope(lambda: self._update(data or {}))

    async def do_delete(self, data: dict[str, Any]) -> dict[str, Any]:
        return await self._envelope(lambda: self._delete(data or {}))

    async def do_list(self, data: dict[str, Any]) -> dict[str, Any]:
        return await self._envelope(lambda: self._list(data or {}))

    # --- internals -----------------------------------------------------------

    def _config(self, data: dict[str, Any], action: str) -> EntityConfig:
        cfg = self._registry.get(data.get("entity"))
        if cfg is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"unknown entity: {data.get('entity')!r}")
        if action not in cfg.actions:
            raise HTTPException(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, detail=f"{action} not allowed for {cfg.entity}")
        return cfg

    @staticmethod
    def _require_id(data: dict[str, Any]) -> int:
        try:
            return int(data["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="id is required") from exc

    async def _create(self, data: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config(data, "create")
        user = rehydrate_user(data.get("identity"))
        if cfg.create_schema is None or cfg.resolve_ws_for_create is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="create not supported")
        async with self._session_factory() as session:
            ws_id = await cfg.resolve_ws_for_create(session, data)
            ensure_workspace_permission(user, ws_id, cfg.permission_resource, _ACTION_PERMISSION["create"])
            payload = cfg.create_schema.model_validate(data.get("payload") or {})
            if cfg.service_create is not None:
                obj = await cfg.service_create(session, payload, data)
            else:
                obj = cfg.model(**payload.model_dump(exclude_unset=True))
                await cfg.repo.create(session, obj)
                await session.commit()
            return rpc_ok(await cfg.serializer(session, obj))

    async def _get(self, data: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config(data, "get")
        obj_id = self._require_id(data)
        async with self._session_factory() as session:
            if not cfg.public_read:
                user = rehydrate_user(data.get("identity"))
                ws_id = await self._ws_from_id(cfg, session, obj_id)
                ensure_workspace_permission(user, ws_id, cfg.permission_resource, _ACTION_PERMISSION["get"])
            obj = await cfg.service_get(session, obj_id, data) if cfg.service_get else await cfg.repo.get(session, obj_id)
            if obj is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=cfg.not_found_detail)
            return rpc_ok(await cfg.serializer(session, obj))

    async def _update(self, data: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config(data, "update")
        user = rehydrate_user(data.get("identity"))
        obj_id = self._require_id(data)
        if cfg.update_schema is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="update not supported")
        async with self._session_factory() as session:
            ws_id = await self._ws_from_id(cfg, session, obj_id)
            ensure_workspace_permission(user, ws_id, cfg.permission_resource, _ACTION_PERMISSION["update"])
            payload = cfg.update_schema.model_validate(data.get("payload") or {})
            if cfg.service_update is not None:
                obj = await cfg.service_update(session, obj_id, payload, data)
            else:
                obj = await cfg.repo.get(session, obj_id)
                if obj is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=cfg.not_found_detail)
                await cfg.repo.update_fields(session, obj, payload.model_dump(exclude_unset=True))
                await session.commit()
            return rpc_ok(await cfg.serializer(session, obj))

    async def _delete(self, data: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config(data, "delete")
        user = rehydrate_user(data.get("identity"))
        obj_id = self._require_id(data)
        async with self._session_factory() as session:
            ws_id = await self._ws_from_id(cfg, session, obj_id)
            ensure_workspace_permission(user, ws_id, cfg.permission_resource, _ACTION_PERMISSION["delete"])
            if cfg.service_delete is not None:
                await cfg.service_delete(session, obj_id, data)
            else:
                obj = await cfg.repo.get(session, obj_id)
                if obj is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=cfg.not_found_detail)
                await cfg.repo.delete(session, obj)
                await session.commit()
            return rpc_ok(None)

    async def _list(self, data: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config(data, "list")
        if cfg.list_fn is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="list not supported")
        async with self._session_factory() as session:
            if not cfg.public_read:
                user = rehydrate_user(data.get("identity"))
                if cfg.resolve_ws_for_list is not None:
                    ws_id = await cfg.resolve_ws_for_list(session, data)
                    ensure_workspace_permission(user, ws_id, cfg.permission_resource, _ACTION_PERMISSION["list"])
            return rpc_ok(await cfg.list_fn(session, data))

    @staticmethod
    async def _ws_from_id(cfg: EntityConfig, session: AsyncSession, obj_id: int) -> int:
        if cfg.resolve_ws_from_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="entity has no workspace resolver")
        return await cfg.resolve_ws_from_id(session, obj_id)

    @staticmethod
    async def _envelope(op: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        try:
            return await op()
        except MissingIdentityError:
            return rpc_error("forbidden", "Not authenticated")
        except ValidationError as exc:
            return rpc_error("unprocessable", _validation_detail(exc))
        except HTTPException as exc:
            return rpc_error(status_to_code(exc.status_code), _detail_message(exc))
        except Exception:  # pragma: no cover - defensive worker guard
            logger.exception("crud rpc failed")
            return rpc_error("internal", "internal error")
