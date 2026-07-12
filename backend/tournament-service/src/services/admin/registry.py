"""Generic admin-CRUD registry for tournament-service.

One EntityConfig per uniform admin entity; the shared CrudDispatcher serves them
over ``rpc.tournament.admin.{create,get,update,delete,list}``. ``service_*`` hooks
delegate to the existing admin service functions (which keep their commits +
side-effects); the engine adds permission + payload validation + serialization +
the envelope. Non-uniform admin endpoints (status transitions, bulk ops, stage
workflows, jobs, challonge, sheets, registration, registration-status) stay
bespoke (Phase 3).
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.crud import CrudDispatcher, EntityConfig
from src import schemas
from src.core import auth, db
from src.core.workspace import get_division_grid
from src.schemas.admin import encounter as enc_schemas
from src.schemas.admin import player_sub_role as psr_schemas
from src.schemas.admin import stage as stage_schemas
from src.schemas.admin import standing as standing_schemas
from src.schemas.admin import team as team_schemas
from src.schemas.admin import tournament as tournament_schemas
from src.services.admin import encounter as enc_service
from src.services.admin import player_sub_role as psr_service
from src.services.admin import stage as stage_service
from src.services.admin import standing as standing_service
from src.services.admin import team as team_service
from src.services.admin import tournament as tournament_service
from src.services.encounter import flows as encounter_flows
from src.services.standings import flows as standings_flows
from src.services.team import flows as team_flows
from src.services.tournament import flows as tournament_flows

# --- workspace resolvers for create/list (must be awaitables) ---


def _body(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("payload") or {}


def _query(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("query") or {}


def _int_or_400(value: Any, field: str) -> int:
    if value is None:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    try:
        return int(value[0] if isinstance(value, list) else value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field}") from exc


async def _ws_body(data: dict[str, Any]) -> int:
    return _int_or_400(_body(data).get("workspace_id"), "workspace_id")


async def _ws_via_tournament_body(session: AsyncSession, data: dict[str, Any]) -> int:
    return await auth.get_tournament_workspace_id(
        session, _int_or_400(_body(data).get("tournament_id"), "tournament_id")
    )


async def _ws_via_team_body(session: AsyncSession, data: dict[str, Any]) -> int:
    # For entities attached to a team (player), the permission workspace must be
    # derived from the team actually being written to — not from an independent
    # client-supplied tournament_id.
    return await auth.get_team_workspace_id(session, _int_or_400(_body(data).get("team_id"), "team_id"))


async def _ws_via_tournament_path(session: AsyncSession, data: dict[str, Any]) -> int:
    return await auth.get_tournament_workspace_id(session, _int_or_400(data.get("tournament_id"), "tournament_id"))


async def _ws_via_stage_path(session: AsyncSession, data: dict[str, Any]) -> int:
    return await auth.get_stage_workspace_id(session, _int_or_400(data.get("stage_id"), "stage_id"))


async def _ws_via_stage_item_path(session: AsyncSession, data: dict[str, Any]) -> int:
    return await auth.get_stage_item_workspace_id(session, _int_or_400(data.get("stage_item_id"), "stage_item_id"))


async def _ws_query(session: AsyncSession, data: dict[str, Any]) -> int:
    return _int_or_400(_query(data).get("workspace_id"), "workspace_id")


# --- serializers (async (session, model) -> json-able dict) ---


def _dump(obj: Any) -> Any:
    return obj.model_dump(mode="json")


async def _ser_tournament(session: AsyncSession, m: Any) -> Any:
    return _dump(await tournament_flows.to_pydantic(session, m, ["stages"]))


async def _ser_team(session: AsyncSession, m: Any) -> Any:
    return _dump(await team_flows.to_pydantic(session, m, ["tournament", "players", "players.user", "captain"]))


async def _ser_player(session: AsyncSession, m: Any) -> Any:
    # to_pydantic_player requires the effective division grid to resolve
    # PlayerRead.division. Resolve it from the player's own tournament so the
    # value matches team-roster serialization (see team_flows.to_pydantic),
    # instead of silently falling back to DEFAULT_GRID.
    grid = await get_division_grid(session, None, tournament_id=m.tournament_id)
    return _dump(await team_flows.to_pydantic_player(session, m, ["user", "tournament"], grid=grid))


async def _ser_stage(session: AsyncSession, m: Any) -> Any:
    return _dump(schemas.StageRead.model_validate(m, from_attributes=True))


async def _ser_stage_item(session: AsyncSession, m: Any) -> Any:
    return _dump(schemas.StageItemRead.model_validate(m, from_attributes=True))


async def _ser_stage_item_input(session: AsyncSession, m: Any) -> Any:
    return _dump(schemas.StageItemInputRead.model_validate(m, from_attributes=True))


async def _ser_encounter(session: AsyncSession, m: Any) -> Any:
    enc = await encounter_flows.get_encounter(
        session, m.id, ["tournament", "stage", "stage_item", "home_team", "away_team"]
    )
    return _dump(enc)


async def _ser_standing(session: AsyncSession, m: Any) -> Any:
    return _dump(await standings_flows.to_pydantic(session, m, ["team", "stage", "stage_item", "tournament"]))


async def _ser_player_sub_role(session: AsyncSession, m: Any) -> Any:
    return _dump(psr_schemas.PlayerSubRoleRead.model_validate(m, from_attributes=True))


# --- list functions ---


async def _list_stages(session: AsyncSession, data: dict[str, Any]) -> Any:
    tournament_id = _int_or_400(data.get("tournament_id"), "tournament_id")
    stages = await stage_service.get_stages_by_tournament(session, tournament_id)
    return [_dump(schemas.StageRead.model_validate(s, from_attributes=True)) for s in stages]


async def _list_player_sub_roles(session: AsyncSession, data: dict[str, Any]) -> Any:
    q = _query(data)
    workspace_id = _int_or_400(q.get("workspace_id"), "workspace_id")
    role_raw = q.get("role")
    role = (role_raw[0] if isinstance(role_raw, list) else role_raw) or None
    inc_raw = q.get("include_inactive")
    inc = inc_raw[0] if isinstance(inc_raw, list) else inc_raw
    include_inactive = str(inc).lower() in ("1", "true", "yes", "on") if inc is not None else False
    rows = await psr_service.list_sub_roles(
        session, workspace_id=workspace_id, role=role, include_inactive=include_inactive
    )
    return [_dump(psr_schemas.PlayerSubRoleRead.model_validate(r, from_attributes=True)) for r in rows]


# --- registry ---

REGISTRY: dict[str, EntityConfig] = {
    "tournament": EntityConfig(
        entity="tournament",
        model=None,  # service hooks own all DB access; model unused
        permission_resource="tournament",
        serializer=_ser_tournament,
        create_schema=tournament_schemas.TournamentCreate,
        update_schema=tournament_schemas.TournamentUpdate,
        resolve_ws_from_id=auth.get_tournament_workspace_id,
        resolve_ws_for_create=lambda s, d: _ws_body(d),
        service_create=lambda s, p, d: tournament_service.create_tournament(s, p),
        service_get=lambda s, i, d: tournament_service.get_tournament(s, i),
        service_update=lambda s, i, p, d: tournament_service.update_tournament(s, i, p),
        service_delete=lambda s, i, d: tournament_service.delete_tournament(s, i),
        not_found_detail="Tournament not found",
        actions=frozenset({"create", "get", "update", "delete"}),
    ),
    "team": EntityConfig(
        entity="team",
        model=None,
        permission_resource="team",
        serializer=_ser_team,
        create_schema=team_schemas.TeamCreate,
        update_schema=team_schemas.TeamUpdate,
        resolve_ws_from_id=auth.get_team_workspace_id,
        resolve_ws_for_create=_ws_via_tournament_body,
        service_create=lambda s, p, d: team_service.create_team(s, p),
        service_get=lambda s, i, d: team_service.get_team(s, i),
        service_update=lambda s, i, p, d: team_service.update_team(s, i, p),
        service_delete=lambda s, i, d: team_service.delete_team(s, i),
        not_found_detail="Team not found",
        actions=frozenset({"create", "get", "update", "delete"}),
    ),
    "player": EntityConfig(
        entity="player",
        model=None,
        permission_resource="player",
        serializer=_ser_player,
        create_schema=team_schemas.PlayerCreate,
        update_schema=team_schemas.PlayerUpdate,
        resolve_ws_from_id=auth.get_player_workspace_id,
        resolve_ws_for_create=_ws_via_team_body,
        service_create=lambda s, p, d: team_service.create_player(s, p),
        service_update=lambda s, i, p, d: team_service.update_player(s, i, p),
        service_delete=lambda s, i, d: team_service.delete_player(s, i),
        not_found_detail="Player not found",
        actions=frozenset({"create", "update", "delete"}),
    ),
    "stage": EntityConfig(
        entity="stage",
        model=None,
        permission_resource="stage",
        serializer=_ser_stage,
        create_schema=stage_schemas.StageCreate,
        update_schema=stage_schemas.StageUpdate,
        resolve_ws_from_id=auth.get_stage_workspace_id,
        resolve_ws_for_create=_ws_via_tournament_path,
        resolve_ws_for_list=_ws_via_tournament_path,
        service_create=lambda s, p, d: stage_service.create_stage(
            s, _int_or_400(d.get("tournament_id"), "tournament_id"), p
        ),
        service_get=lambda s, i, d: stage_service.get_stage(s, i),
        service_update=lambda s, i, p, d: stage_service.update_stage(s, i, p),
        service_delete=lambda s, i, d: stage_service.delete_stage(s, i),
        list_fn=_list_stages,
        not_found_detail="Stage not found",
        actions=frozenset({"create", "get", "update", "delete", "list"}),
    ),
    "stage_item": EntityConfig(
        entity="stage_item",
        model=None,
        permission_resource="stage",
        serializer=_ser_stage_item,
        create_schema=stage_schemas.StageItemCreate,
        update_schema=stage_schemas.StageItemUpdate,
        resolve_ws_from_id=auth.get_stage_item_workspace_id,
        resolve_ws_for_create=_ws_via_stage_path,
        service_create=lambda s, p, d: stage_service.create_stage_item(
            s, _int_or_400(d.get("stage_id"), "stage_id"), p
        ),
        service_update=lambda s, i, p, d: stage_service.update_stage_item(s, i, p),
        not_found_detail="Stage item not found",
        actions=frozenset({"create", "update"}),
    ),
    "stage_item_input": EntityConfig(
        entity="stage_item_input",
        model=None,
        permission_resource="stage",
        serializer=_ser_stage_item_input,
        create_schema=stage_schemas.StageItemInputCreate,
        update_schema=stage_schemas.StageItemInputUpdate,
        resolve_ws_from_id=auth.get_stage_item_input_workspace_id,
        resolve_ws_for_create=_ws_via_stage_item_path,
        service_create=lambda s, p, d: stage_service.create_stage_item_input(
            s, _int_or_400(d.get("stage_item_id"), "stage_item_id"), p
        ),
        service_update=lambda s, i, p, d: stage_service.update_stage_item_input(s, i, p),
        not_found_detail="Stage item input not found",
        actions=frozenset({"create", "update"}),
    ),
    "encounter": EntityConfig(
        entity="encounter",
        model=None,
        permission_resource="match",
        serializer=_ser_encounter,
        create_schema=enc_schemas.EncounterCreate,
        update_schema=enc_schemas.EncounterUpdate,
        resolve_ws_from_id=auth.get_encounter_workspace_id,
        resolve_ws_for_create=_ws_via_tournament_body,
        service_create=lambda s, p, d: enc_service.create_encounter(s, p),
        service_update=lambda s, i, p, d: enc_service.update_encounter(s, i, p),
        service_delete=lambda s, i, d: enc_service.delete_encounter(s, i),
        not_found_detail="Encounter not found",
        actions=frozenset({"create", "update", "delete"}),
    ),
    "standing": EntityConfig(
        entity="standing",
        model=None,
        permission_resource="standing",
        serializer=_ser_standing,
        update_schema=standing_schemas.StandingUpdate,
        resolve_ws_from_id=auth.get_standing_workspace_id,
        service_update=lambda s, i, p, d: standing_service.update_standing(s, i, p),
        service_delete=lambda s, i, d: standing_service.delete_standing(s, i),
        not_found_detail="Standing not found",
        actions=frozenset({"update", "delete"}),
    ),
    "player_sub_role": EntityConfig(
        entity="player_sub_role",
        model=None,
        permission_resource="player",
        serializer=_ser_player_sub_role,
        create_schema=psr_schemas.PlayerSubRoleCreate,
        update_schema=psr_schemas.PlayerSubRoleUpdate,
        resolve_ws_from_id=auth.get_player_sub_role_workspace_id,
        resolve_ws_for_create=lambda s, d: _ws_body(d),
        resolve_ws_for_list=_ws_query,
        service_create=lambda s, p, d: psr_service.create_sub_role(s, p),
        service_update=lambda s, i, p, d: psr_service.update_sub_role(s, i, p),
        service_delete=lambda s, i, d: psr_service.deactivate_sub_role(s, i),
        list_fn=_list_player_sub_roles,
        not_found_detail="Player sub-role not found",
        actions=frozenset({"create", "update", "delete", "list"}),
    ),
}

dispatcher = CrudDispatcher(REGISTRY, db.async_session_maker)


def register(broker: Any) -> None:
    @broker.subscriber("rpc.tournament.admin.create")
    async def _admin_create(data: dict, msg: RabbitMessage) -> dict:
        return await dispatcher.do_create(data)

    @broker.subscriber("rpc.tournament.admin.get")
    async def _admin_get(data: dict, msg: RabbitMessage) -> dict:
        return await dispatcher.do_get(data)

    @broker.subscriber("rpc.tournament.admin.update")
    async def _admin_update(data: dict, msg: RabbitMessage) -> dict:
        return await dispatcher.do_update(data)

    @broker.subscriber("rpc.tournament.admin.delete")
    async def _admin_delete(data: dict, msg: RabbitMessage) -> dict:
        return await dispatcher.do_delete(data)

    @broker.subscriber("rpc.tournament.admin.list")
    async def _admin_list(data: dict, msg: RabbitMessage) -> dict:
        return await dispatcher.do_list(data)
