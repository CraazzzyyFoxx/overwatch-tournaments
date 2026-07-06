"""Admin CRUD for game metadata (hero / map / gamemode), relocated from
parser-service. The public reads already live in app-service (shared CRUD read
engine); these are the global-permission-gated admin writes + paginated admin
list. Service + schema code ported verbatim into ``src/services/admin`` and
``src/schemas/admin``.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.query import build_query_model
from src.core import db
from src.schemas import GamemodeRead, HeroRead, MapRead
from src.schemas.admin import gamemode as gamemode_schemas
from src.schemas.admin import hero as hero_schemas
from src.schemas.admin import map as map_schemas
from src.services.admin import gamemode as gamemode_service
from src.services.admin import hero as hero_service
from src.services.admin import map as map_service

from . import _common as c

_SF = db.async_session_maker


def _gate(data: dict, resource: str, action: str) -> None:
    user = c.actor(data)
    c.require_active(user)
    if not user.has_permission(resource, action):
        raise HTTPException(status_code=403, detail=f"Permission denied: {resource}.{action} required")


def register(broker: Any, logger: Any) -> None:
    def _register_entity(
        *,
        prefix: str,
        resource: str,
        list_qp: Any,
        list_params: Any,
        create_schema: Any,
        update_schema: Any,
        read_schema: Any,
        list_fn: Any,
        create_fn: Any,
        update_fn: Any,
        delete_fn: Any,
    ) -> None:
        @broker.subscriber(f"rpc.app.{prefix}.admin_list")
        async def _list(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                _gate(data, resource, "read")
                qp = build_query_model(list_qp, data.get("query"))
                res = await list_fn(session, list_params.from_query_params(qp))
                return {
                    "results": [r.model_dump(mode="json") for r in res["results"]],
                    "total": res["total"],
                    "page": res["page"],
                    "per_page": res["per_page"],
                }

            return await c.envelope(logger, f"{prefix}.admin_list", op, session_factory=_SF)

        @broker.subscriber(f"rpc.app.{prefix}.admin_create")
        async def _create(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                _gate(data, resource, "create")
                obj = await create_fn(session, create_schema.model_validate(c.payload(data)))
                return read_schema.model_validate(obj, from_attributes=True)

            return await c.envelope(logger, f"{prefix}.admin_create", op, session_factory=_SF)

        @broker.subscriber(f"rpc.app.{prefix}.admin_update")
        async def _update(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                _gate(data, resource, "update")
                obj = await update_fn(session, c.require_id(data), update_schema.model_validate(c.payload(data)))
                return read_schema.model_validate(obj, from_attributes=True)

            return await c.envelope(logger, f"{prefix}.admin_update", op, session_factory=_SF)

        @broker.subscriber(f"rpc.app.{prefix}.admin_delete")
        async def _delete(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                _gate(data, resource, "delete")
                await delete_fn(session, c.require_id(data))
                return None

            return await c.envelope(logger, f"{prefix}.admin_delete", op, session_factory=_SF)

    _register_entity(
        prefix="heroes",
        resource="hero",
        list_qp=hero_schemas.HeroListQueryParams,
        list_params=hero_schemas.HeroListParams,
        create_schema=hero_schemas.HeroCreate,
        update_schema=hero_schemas.HeroUpdate,
        read_schema=HeroRead,
        list_fn=hero_service.get_heroes,
        create_fn=hero_service.create_hero,
        update_fn=hero_service.update_hero,
        delete_fn=hero_service.delete_hero,
    )
    _register_entity(
        prefix="maps",
        resource="map",
        list_qp=map_schemas.MapListQueryParams,
        list_params=map_schemas.MapListParams,
        create_schema=map_schemas.MapCreate,
        update_schema=map_schemas.MapUpdate,
        read_schema=MapRead,
        list_fn=map_service.get_maps,
        create_fn=map_service.create_map,
        update_fn=map_service.update_map,
        delete_fn=map_service.delete_map,
    )
    _register_entity(
        prefix="gamemodes",
        resource="gamemode",
        list_qp=gamemode_schemas.GamemodeListQueryParams,
        list_params=gamemode_schemas.GamemodeListParams,
        create_schema=gamemode_schemas.GamemodeCreate,
        update_schema=gamemode_schemas.GamemodeUpdate,
        read_schema=GamemodeRead,
        list_fn=gamemode_service.get_gamemodes,
        create_fn=gamemode_service.create_gamemode,
        update_fn=gamemode_service.update_gamemode,
        delete_fn=gamemode_service.delete_gamemode,
    )
