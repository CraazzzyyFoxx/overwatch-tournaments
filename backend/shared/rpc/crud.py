"""Config-driven generic CRUD-over-RPC engine.

Uniform admin CRUD (fetch -> validate -> mutate -> side-effects -> serialize)
collapses to one ``EntityConfig`` row per entity instead of a hand-written RPC
handler. A service builds a ``CrudDispatcher`` from its registry + session factory
and wires the five generic subscribers under its own queue prefix, e.g.::

    from faststream.rabbit import RabbitMessage

    dispatcher = CrudDispatcher(REGISTRY, db.async_session_maker)

    @broker.subscriber("rpc.tournament.admin.update")
    async def _(data: dict, msg: RabbitMessage) -> dict:
        return await dispatcher.do_update(data)

Each request carries ``{entity, id?, payload?, identity, query?}``. The dispatcher
rehydrates the user, resolves the owning workspace, checks the permission, then
either delegates to the existing service function (``service_*`` hook, which owns
its commit + side-effects) or runs a generic ``BaseRepository`` path (engine owns
the commit). Returns the ``{ok,data,error}`` envelope.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from loguru import logger
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.db import Base
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.pagination import PaginationQueryParams
from shared.models.identity.auth_user import AuthUser
from shared.repository.base import BaseRepository
from shared.rpc.common import http_error, q1, validation_error
from shared.rpc.identity import MissingIdentityError, ensure_workspace_permission, rehydrate_user
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code
from shared.services.audit import json_safe, record_audit

__all__ = ("EntityConfig", "CrudDispatcher")

# A session factory is anything callable returning an async-context-manager that
# yields an AsyncSession (e.g. SQLAlchemy ``async_sessionmaker``).
SessionFactory = Callable[[], Any]
Serializer = Callable[[AsyncSession, Any], Awaitable[Any]]
WsFromId = Callable[[AsyncSession, int], Awaitable[int]]
WsFromData = Callable[[AsyncSession, dict[str, Any]], Awaitable[int]]

# Map an action verb to the RBAC action checked against ``permission_resource``.
_ACTION_PERMISSION = {"create": "create", "get": "read", "update": "update", "delete": "delete", "list": "read"}


# Where ``page``/``per_page`` fall back to when the request omits them: the same
# model the paginated list flows validate against, so the two cannot drift apart.
_PAGE_DEFAULTS = PaginationQueryParams()


def _paginated(reply: Any, data: dict[str, Any]) -> Any:
    """Guarantee the four-key list envelope on a generic CRUD list reply.

    ``list_fn`` implementations range from a full ``Paginated.model_dump()`` down
    to a bare ``{results, total}``; a client should not have to know which entity
    it asked for to know whether ``page`` is present. Extra keys the service added
    (``counts``, ``available_scopes``) pass through untouched -- this fills gaps,
    it does not define the key set. A non-envelope reply (a bare list) is left
    alone: adding keys there would change the contract, not extend it.
    """
    if not isinstance(reply, dict) or "results" not in reply:
        return reply
    filled = dict(reply)
    filled.setdefault("page", q1(data, "page", int, _PAGE_DEFAULTS.page))
    filled.setdefault("per_page", q1(data, "per_page", int, _PAGE_DEFAULTS.per_page))
    return filled


# Fields an entity may carry as its human-readable name, best first. Nothing is
# registered per entity on purpose: the journal degrades to "no label" rather
# than forcing every EntityConfig to declare one.
_LABEL_FIELDS = ("name", "title", "slug")


def _label(obj: Any) -> str | None:
    for field in _LABEL_FIELDS:
        value = getattr(obj, field, None)
        if isinstance(value, str) and value:
            return value
    return None


# One implementation, in the primitive that owns the columns: ``record_audit``
# coerces ``before``/``after`` itself, so a call site cannot forget. Kept under
# the old private name because this module's callers and tests already use it.
_json_safe = json_safe


def _field_values(obj: Any, fields: Iterable[str]) -> dict[str, Any]:
    """Read the named fields off an entity, JSON-coerced.

    Read off the object, never off the request: a service may normalise or ignore
    what was sent, and the journal must state what was actually written.
    """
    return {name: _json_safe(getattr(obj, name, None)) for name in fields}


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

    ``update_actions`` narrows an update's permission by what the request sets:
    given the payload's keys, the actions on ``permission_resource`` it needs
    (every one of them). Absent, an update needs ``update``. Decided from the raw
    keys, before validation, so a caller with no grant still gets 403, not 422.
    """

    entity: str
    model: type[Base]
    permission_resource: str
    serializer: Serializer
    public_read: bool = False
    create_schema: type[BaseModel] | None = None
    update_schema: type[BaseModel] | None = None
    resolve_ws_from_id: WsFromId | None = None  # get / update / delete (id from data["id"])
    resolve_ws_for_create: WsFromData | None = None  # create (workspace from payload/path)
    resolve_ws_for_list: WsFromData | None = None  # list (workspace from query/path)
    # Hooks receive the full request ``data`` dict (3rd/4th arg) so adapters can
    # read path params (e.g. a create nested under /stages/tournament/{id}).
    service_create: Callable[[AsyncSession, BaseModel, dict], Awaitable[Any]] | None = None
    service_get: Callable[[AsyncSession, int, dict], Awaitable[Any]] | None = None
    service_update: Callable[[AsyncSession, int, BaseModel, dict], Awaitable[Any]] | None = None
    service_delete: Callable[[AsyncSession, int, dict], Awaitable[None]] | None = None
    list_fn: Callable[[AsyncSession, dict[str, Any]], Awaitable[Any]] | None = None
    not_found_detail: str = "Not found"
    actions: frozenset[str] = frozenset({"create", "get", "update", "delete"})
    update_actions: Callable[[frozenset[str]], Iterable[str]] | None = None

    @cached_property
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"unknown entity: {data.get('entity')!r}"
            )
        if action not in cfg.actions:
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED, detail=f"{action} not allowed for {cfg.entity}"
            )
        return cfg

    @staticmethod
    def _require_id(data: dict[str, Any]) -> int:
        try:
            return int(data["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="id is required") from exc

    @staticmethod
    async def _audit(
        session: AsyncSession,
        cfg: EntityConfig,
        verb: str,
        *,
        user: AuthUser,
        ws_id: int,
        data: dict[str, Any],
        entity_id: int | None,
        entity_label: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        """Stage one audit row for a write on this entity.

        ``ws_id`` is the very value ``ensure_workspace_permission`` was checked
        against, passed down rather than resolved again: the journal's scope is the
        authorisation scope by construction, so the two can never disagree.

        ``action``/``entity_type`` come from ``cfg.entity``, not from the queue, so
        one dispatcher serving nine entities still reads as nine kinds of event.
        """
        await record_audit(
            session,
            action=f"{cfg.entity}.{verb}",
            source="admin",
            actor=user,
            # Snapshotted so the row stays readable after the account is deleted:
            # with no FK on actor_auth_user_id, a reader's join resolves nothing then.
            actor_label=user.username,
            workspace_id=ws_id,
            entity_type=cfg.entity,
            entity_id=entity_id,
            entity_label=entity_label,
            before=before,
            after=after,
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
        )

    async def _create(self, data: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config(data, "create")
        user = rehydrate_user(data.get("identity"))
        if cfg.create_schema is None or cfg.resolve_ws_for_create is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="create not supported")
        async with self._session_factory() as session:
            ws_id = await cfg.resolve_ws_for_create(session, data)
            ensure_workspace_permission(user, ws_id, cfg.permission_resource, _ACTION_PERMISSION["create"])
            payload = cfg.create_schema.model_validate(data.get("payload") or {})
            fields = payload.model_dump(exclude_unset=True)
            if cfg.service_create is not None:
                obj = await cfg.service_create(session, payload, data)
                # ponytail: this row lands in a second transaction, unlike every other
                # branch here. The id it names does not exist until the service has run,
                # and the service owns its commit, so there is no moment that is both
                # after the id and inside the write's transaction. Ceiling: a crash
                # between the two commits loses the trail (never the other way round).
                # Upgrade path: move the commit out of service_create into this engine
                # -- the commit-ownership rule on EntityConfig already forbids both --
                # and this same call then becomes atomic, like the branch below.
            else:
                obj = cfg.model(**fields)
                # repo.create flushes, so the autoincrement id the audit row names is
                # already assigned by the time it is read below.
                await cfg.repo.create(session, obj)
            await self._audit(
                session,
                cfg,
                "create",
                user=user,
                ws_id=ws_id,
                data=data,
                entity_id=getattr(obj, "id", None),
                entity_label=_label(obj),
                after=_field_values(obj, fields),
            )
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
            obj = (
                await cfg.service_get(session, obj_id, data) if cfg.service_get else await cfg.repo.get(session, obj_id)
            )
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
            raw = data.get("payload")
            fields = frozenset(raw) if isinstance(raw, dict) else frozenset()
            actions = cfg.update_actions(fields) if cfg.update_actions else (_ACTION_PERMISSION["update"],)
            for action in actions:
                ensure_workspace_permission(user, ws_id, cfg.permission_resource, action)
            payload = cfg.update_schema.model_validate(data.get("payload") or {})
            changes = payload.model_dump(exclude_unset=True)
            if cfg.service_update is not None:
                # Staged before the hook so the row rides the transaction the service
                # commits: a rejected update rolls back and leaves no trail of having
                # happened.
                # ponytail: no before-image, and ``after`` carries the requested values
                # rather than the stored ones -- the row cannot be read here, since a
                # service-backed entity may declare model=None. Ceiling: field-level
                # truth when a service normalises input. Upgrade path: as in create,
                # move the commit into this engine, then read the object back.
                await self._audit(
                    session,
                    cfg,
                    "update",
                    user=user,
                    ws_id=ws_id,
                    data=data,
                    entity_id=obj_id,
                    after={name: _json_safe(value) for name, value in changes.items()},
                )
                obj = await cfg.service_update(session, obj_id, payload, data)
            else:
                obj = await cfg.repo.get(session, obj_id)
                if obj is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=cfg.not_found_detail)
                # Only the keys this request actually set: the journal records a change,
                # not a snapshot of the row.
                before = _field_values(obj, changes)
                await cfg.repo.update_fields(session, obj, changes)
                await self._audit(
                    session,
                    cfg,
                    "update",
                    user=user,
                    ws_id=ws_id,
                    data=data,
                    entity_id=obj_id,
                    entity_label=_label(obj),
                    before=before,
                    after=_field_values(obj, changes),
                )
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
                # Staged before the hook for the same reason as update: the service owns
                # the commit, so this is the only point that shares its transaction.
                # ponytail: identity only, no label -- reading the row here is not
                # possible for a service-backed entity with model=None. Ceiling: readers
                # see the id of what was removed, not its name. Upgrade path: move the
                # commit into this engine and read the object before deleting it.
                await self._audit(
                    session,
                    cfg,
                    "delete",
                    user=user,
                    ws_id=ws_id,
                    data=data,
                    entity_id=obj_id,
                    before={"id": obj_id},
                )
                await cfg.service_delete(session, obj_id, data)
            else:
                obj = await cfg.repo.get(session, obj_id)
                if obj is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=cfg.not_found_detail)
                # Key fields only, read while the row is still alive. The journal names
                # what was removed; it is not a backup of it.
                label = _label(obj)
                await self._audit(
                    session,
                    cfg,
                    "delete",
                    user=user,
                    ws_id=ws_id,
                    data=data,
                    entity_id=obj_id,
                    entity_label=label,
                    before={"id": obj_id, "label": label},
                )
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
                if cfg.resolve_ws_for_list is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="entity has no list workspace resolver",
                    )
                ws_id = await cfg.resolve_ws_for_list(session, data)
                ensure_workspace_permission(user, ws_id, cfg.permission_resource, _ACTION_PERMISSION["list"])
            return rpc_ok(_paginated(await cfg.list_fn(session, data), data))

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
            return rpc_error("unauthorized", "Not authenticated")
        except ValidationError as exc:
            message, details = validation_error(exc)
            return rpc_error("unprocessable", message, details)
        except HTTPException as exc:
            message, details = http_error(exc)
            return rpc_error(status_to_code(exc.status_code), message, details)
        except Exception:  # pragma: no cover - defensive worker guard
            logger.exception("crud rpc failed")
            return rpc_error("internal", "internal error")
