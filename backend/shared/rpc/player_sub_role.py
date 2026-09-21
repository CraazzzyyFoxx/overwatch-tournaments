"""CRUD-over-RPC adapter for the workspace player-sub-role catalog."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rbac.workspace_lookup import get_player_sub_role_workspace_id
from shared.rpc.crud import EntityConfig
from shared.schemas.player_sub_role import PlayerSubRoleCreate, PlayerSubRoleRead, PlayerSubRoleUpdate
from shared.services.player_sub_role import player_sub_role_service

__all__ = ("player_sub_role_entity",)


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _int_or_400(value: Any, field: str) -> int:
    value = _first(value)
    if value is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"missing {field}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid {field}") from exc


def _dump(row: models.PlayerSubRole) -> dict[str, Any]:
    return PlayerSubRoleRead.model_validate(row, from_attributes=True).model_dump(mode="json")


async def _serialize(_session: AsyncSession, row: models.PlayerSubRole) -> dict[str, Any]:
    return _dump(row)


async def _ws_from_payload(_session: AsyncSession, data: dict[str, Any]) -> int:
    return _int_or_400((data.get("payload") or {}).get("workspace_id"), "workspace_id")


async def _ws_from_query(_session: AsyncSession, data: dict[str, Any]) -> int:
    return _int_or_400((data.get("query") or {}).get("workspace_id"), "workspace_id")


async def _list_rpc(session: AsyncSession, data: dict[str, Any]) -> list[dict[str, Any]]:
    query = data.get("query") or {}
    include = _first(query.get("include_inactive"))
    include_inactive = str(include).lower() in ("1", "true", "yes", "on") if include is not None else False
    rows = await player_sub_role_service.list_sub_roles(
        session,
        workspace_id=_int_or_400(query.get("workspace_id"), "workspace_id"),
        role=_first(query.get("role")) or None,
        include_inactive=include_inactive,
    )
    return [_dump(row) for row in rows]


def player_sub_role_entity() -> EntityConfig:
    """CRUD entity any service's ``CrudDispatcher`` can register as-is."""
    return EntityConfig(
        entity="player_sub_role",
        model=None,
        permission_resource="player",
        serializer=_serialize,
        create_schema=PlayerSubRoleCreate,
        update_schema=PlayerSubRoleUpdate,
        resolve_ws_from_id=get_player_sub_role_workspace_id,
        resolve_ws_for_create=_ws_from_payload,
        resolve_ws_for_list=_ws_from_query,
        service_create=lambda session, payload, _data: player_sub_role_service.create_sub_role(session, payload),
        service_update=lambda session, row_id, payload, _data: player_sub_role_service.update_sub_role(
            session, row_id, payload
        ),
        service_delete=lambda session, row_id, _data: player_sub_role_service.deactivate_sub_role(session, row_id),
        list_fn=_list_rpc,
        not_found_detail="Player sub-role not found",
        actions=frozenset({"create", "update", "delete", "list"}),
    )
