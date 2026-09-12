"""Generic admin-CRUD registry for tournament-service.

One EntityConfig per uniform admin entity; the shared CrudDispatcher serves them
over ``rpc.tournament.admin.{create,get,update,delete,list}``. ``service_*`` hooks
delegate to the existing admin service methods (which keep their commits +
side-effects); the engine adds permission + payload validation + serialization +
the envelope. Non-uniform admin endpoints (status transitions, bulk ops, stage
workflows, jobs, challonge, sheets, registration, registration-status) stay
bespoke (Phase 3).

``REGISTRY``, ``dispatcher`` and ``register`` stay module-level: ``serve.py``
calls ``admin_registry.register(broker)``. The session-taking hooks are bound
methods of ``registry_service``.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.crud import CrudDispatcher, EntityConfig
from shared.services.player_sub_role import player_sub_role_entity
from src import schemas
from src.core import auth, db
from src.core.workspace import get_division_grid
from src.services.admin.encounter import encounter_service as enc_service
from src.services.admin.stage import stage_service
from src.services.admin.standing import standing_service
from src.services.admin.team import team_service
from src.services.admin.tournament import tournament_service
from src.services.admin.tournament_link import TournamentLinkService
from src.services.admin.tournament_link import tournament_link_service as tlink_service
from src.services.encounter.flows import EncounterFlowsService
from src.services.encounter.flows import flows_service as encounter_flows
from src.services.standings.flows import StandingsFlowsService
from src.services.standings.flows import flows_service as standings_flows
from src.services.team.flows import TeamFlowsService
from src.services.team.flows import flows_service as team_flows
from src.services.tournament.flows import TournamentFlowsService
from src.services.tournament.flows import flows_service as tournament_flows

# --- payload/query accessors (pure) ---


def _body(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("payload") or {}


def _query(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("query") or {}


def _int_or_400(value: Any, field: str) -> int:
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        raise HTTPException(status_code=400, detail=f"missing {field}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field}") from exc


async def _ws_body(data: dict[str, Any]) -> int:
    return _int_or_400(_body(data).get("workspace_id"), "workspace_id")


def _dump(obj: Any) -> Any:
    return obj.model_dump(mode="json")


class AdminRegistryService:
    """Session-taking hooks the ``REGISTRY`` table binds into its EntityConfigs."""

    def __init__(
        self,
        *,
        tournament_flows: TournamentFlowsService = tournament_flows,
        team_flows: TeamFlowsService = team_flows,
        encounter_flows: EncounterFlowsService = encounter_flows,
        standings_flows: StandingsFlowsService = standings_flows,
        tournament_links: TournamentLinkService = tlink_service,
    ) -> None:
        self.tournament_flows = tournament_flows
        self.team_flows = team_flows
        self.encounter_flows = encounter_flows
        self.standings_flows = standings_flows
        self.tournament_links = tournament_links

    # --- workspace resolvers for create/list (must be awaitables) ---

    async def _ws_via_tournament_body(self, session: AsyncSession, data: dict[str, Any]) -> int:
        return await auth.get_tournament_workspace_id(
            session, _int_or_400(_body(data).get("tournament_id"), "tournament_id")
        )

    async def _ws_via_team_body(self, session: AsyncSession, data: dict[str, Any]) -> int:
        # For entities attached to a team (player), the permission workspace must be
        # derived from the team actually being written to — not from an independent
        # client-supplied tournament_id.
        return await auth.get_team_workspace_id(session, _int_or_400(_body(data).get("team_id"), "team_id"))

    async def _ws_via_tournament_path(self, session: AsyncSession, data: dict[str, Any]) -> int:
        return await auth.get_tournament_workspace_id(session, _int_or_400(data.get("tournament_id"), "tournament_id"))

    async def _ws_via_tournament_query(self, session: AsyncSession, data: dict[str, Any]) -> int:
        # Same reason as _ws_via_team_body: the entity is tournament-scoped and has no
        # workspace_id of its own, so the permission workspace comes from the parent
        # tournament being listed — never from an independent client-supplied
        # workspace_id query param.
        return await auth.get_tournament_workspace_id(
            session, _int_or_400(_query(data).get("tournament_id"), "tournament_id")
        )

    async def _ws_via_stage_path(self, session: AsyncSession, data: dict[str, Any]) -> int:
        return await auth.get_stage_workspace_id(session, _int_or_400(data.get("stage_id"), "stage_id"))

    async def _ws_via_stage_item_path(self, session: AsyncSession, data: dict[str, Any]) -> int:
        return await auth.get_stage_item_workspace_id(session, _int_or_400(data.get("stage_item_id"), "stage_item_id"))

    # --- serializers (async (session, model) -> json-able dict) ---

    async def _ser_tournament(self, session: AsyncSession, m: Any) -> Any:
        # `roster_shape` is opt-in (D16): the admin Settings tab renders the roster
        # form from it, so this read must ask for it explicitly. `division_grid_version`
        # is the same kind of opt-in: the hub's draft setup resolves player divisions
        # against the tournament's OWN grid, not the workspace default.
        #
        # `tournament_read`, not `to_pydantic`: it resolves the `challonge_source`-derived
        # ids/slugs, which `to_pydantic` serializes as None when a caller omits them (the
        # columns behind those fields are gone). Omitting them here made the admin Settings
        # tab read back `challonge_slug: null` right after linking a bracket -- the field
        # looked blank, the badge read "Not linked" and every sync control stayed disabled
        # even though the link was persisted.
        entities = ["stages", "roster_shape", "division_grid_version"]
        return _dump(await self.tournament_flows.tournament_read(session, m, entities))

    async def _ser_team(self, session: AsyncSession, m: Any) -> Any:
        return _dump(
            await self.team_flows.to_pydantic(session, m, ["tournament", "players", "players.user", "captain"])
        )

    async def _ser_player(self, session: AsyncSession, m: Any) -> Any:
        # to_pydantic_player requires the effective division grid to resolve
        # PlayerRead.division. Resolve it from the player's own tournament so the
        # value matches team-roster serialization (see team_flows.to_pydantic),
        # instead of silently falling back to DEFAULT_GRID.
        grid = await get_division_grid(session, None, tournament_id=m.tournament_id)
        return _dump(await self.team_flows.to_pydantic_player(session, m, ["user", "tournament"], grid=grid))

    async def _ser_stage(self, session: AsyncSession, m: Any) -> Any:
        # `stage_read`, not `model_validate`: same derivation as `_list_stages`, else a
        # stage create/update response blanks the hub's Challonge link.
        return _dump(await self.tournament_flows.stage_read(session, m))

    async def _ser_stage_item(self, session: AsyncSession, m: Any) -> Any:
        return _dump(schemas.StageItemRead.model_validate(m, from_attributes=True))

    async def _ser_stage_item_input(self, session: AsyncSession, m: Any) -> Any:
        return _dump(schemas.StageItemInputRead.model_validate(m, from_attributes=True))

    async def _ser_encounter(self, session: AsyncSession, m: Any) -> Any:
        enc = await self.encounter_flows.get_encounter(
            session, m.id, ["tournament", "stage", "stage_item", "home_team", "away_team"]
        )
        return _dump(enc)

    async def _ser_standing(self, session: AsyncSession, m: Any) -> Any:
        return _dump(await self.standings_flows.to_pydantic(session, m, ["team", "stage", "stage_item", "tournament"]))

    async def _ser_tournament_link(self, session: AsyncSession, m: Any) -> Any:
        return _dump(schemas.TournamentLinkRead.model_validate(m, from_attributes=True))

    # --- list functions ---

    async def _list_stages(self, session: AsyncSession, data: dict[str, Any]) -> Any:
        # `get_stages_read` runs the same query (items+inputs eager, ordered by
        # `order`) and additionally applies the `challonge_source`-derived
        # ids/slugs. Validating the models directly, as this used to, left every
        # `stage.challonge_slug` null — the columns behind them are gone — so the
        # hub's Challonge-source detection and the stage header link both went dead.
        tournament_id = _int_or_400(data.get("tournament_id"), "tournament_id")
        stages = await self.tournament_flows.get_stages_read(session, tournament_id)
        return [_dump(stage) for stage in stages]

    async def _list_tournament_links(self, session: AsyncSession, data: dict[str, Any]) -> Any:
        q = _query(data)
        tournament_id = _int_or_400(q.get("tournament_id"), "tournament_id")
        act_raw = q.get("active_only")
        act = act_raw[0] if isinstance(act_raw, list) else act_raw
        active_only = str(act).lower() in ("1", "true", "yes", "on") if act is not None else False
        rows = await self.tournament_links.list_links(session, tournament_id, active_only=active_only)
        return [_dump(schemas.TournamentLinkRead.model_validate(r, from_attributes=True)) for r in rows]


registry_service = AdminRegistryService()


# --- registry ---

REGISTRY: dict[str, EntityConfig] = {
    "tournament": EntityConfig(
        entity="tournament",
        model=None,  # service hooks own all DB access; model unused
        permission_resource="tournament",
        serializer=registry_service._ser_tournament,
        create_schema=schemas.TournamentCreate,
        update_schema=schemas.TournamentUpdate,
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
        serializer=registry_service._ser_team,
        create_schema=schemas.TeamCreate,
        update_schema=schemas.TeamUpdate,
        resolve_ws_from_id=auth.get_team_workspace_id,
        resolve_ws_for_create=registry_service._ws_via_tournament_body,
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
        serializer=registry_service._ser_player,
        create_schema=schemas.PlayerCreate,
        update_schema=schemas.PlayerUpdate,
        resolve_ws_from_id=auth.get_player_workspace_id,
        resolve_ws_for_create=registry_service._ws_via_team_body,
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
        serializer=registry_service._ser_stage,
        create_schema=schemas.StageCreate,
        update_schema=schemas.StageUpdate,
        resolve_ws_from_id=auth.get_stage_workspace_id,
        resolve_ws_for_create=registry_service._ws_via_tournament_path,
        resolve_ws_for_list=registry_service._ws_via_tournament_path,
        service_create=lambda s, p, d: stage_service.create_stage(
            s, _int_or_400(d.get("tournament_id"), "tournament_id"), p
        ),
        service_get=lambda s, i, d: stage_service.get_stage(s, i),
        service_update=lambda s, i, p, d: stage_service.update_stage(s, i, p),
        service_delete=lambda s, i, d: stage_service.delete_stage(s, i),
        list_fn=registry_service._list_stages,
        not_found_detail="Stage not found",
        actions=frozenset({"create", "get", "update", "delete", "list"}),
    ),
    "stage_item": EntityConfig(
        entity="stage_item",
        model=None,
        permission_resource="stage",
        serializer=registry_service._ser_stage_item,
        create_schema=schemas.StageItemCreate,
        update_schema=schemas.StageItemUpdate,
        resolve_ws_from_id=auth.get_stage_item_workspace_id,
        resolve_ws_for_create=registry_service._ws_via_stage_path,
        service_create=lambda s, p, d: stage_service.create_stage_item(
            s, _int_or_400(d.get("stage_id"), "stage_id"), p
        ),
        service_update=lambda s, i, p, d: stage_service.update_stage_item(s, i, p),
        service_delete=lambda s, i, d: stage_service.delete_stage_item(s, i),
        not_found_detail="Stage item not found",
        actions=frozenset({"create", "update", "delete"}),
    ),
    "stage_item_input": EntityConfig(
        entity="stage_item_input",
        model=None,
        permission_resource="stage",
        serializer=registry_service._ser_stage_item_input,
        create_schema=schemas.StageItemInputCreate,
        update_schema=schemas.StageItemInputUpdate,
        resolve_ws_from_id=auth.get_stage_item_input_workspace_id,
        resolve_ws_for_create=registry_service._ws_via_stage_item_path,
        service_create=lambda s, p, d: stage_service.create_stage_item_input(
            s, _int_or_400(d.get("stage_item_id"), "stage_item_id"), p
        ),
        service_update=lambda s, i, p, d: stage_service.update_stage_item_input(s, i, p),
        service_delete=lambda s, i, d: stage_service.delete_stage_item_input(s, i),
        not_found_detail="Stage item input not found",
        actions=frozenset({"create", "update", "delete"}),
    ),
    "encounter": EntityConfig(
        entity="encounter",
        model=None,
        permission_resource="match",
        serializer=registry_service._ser_encounter,
        create_schema=schemas.EncounterCreate,
        update_schema=schemas.EncounterUpdate,
        resolve_ws_from_id=auth.get_encounter_workspace_id,
        resolve_ws_for_create=registry_service._ws_via_tournament_body,
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
        serializer=registry_service._ser_standing,
        update_schema=schemas.StandingUpdate,
        resolve_ws_from_id=auth.get_standing_workspace_id,
        service_update=lambda s, i, p, d: standing_service.update_standing(s, i, p),
        service_delete=lambda s, i, d: standing_service.delete_standing(s, i),
        not_found_detail="Standing not found",
        actions=frozenset({"update", "delete"}),
    ),
    "player_sub_role": player_sub_role_entity(),
    "tournament_link": EntityConfig(
        entity="tournament_link",
        model=None,
        permission_resource="tournament_link",
        serializer=registry_service._ser_tournament_link,
        create_schema=schemas.TournamentLinkCreate,
        update_schema=schemas.TournamentLinkUpdate,
        resolve_ws_from_id=auth.get_tournament_link_workspace_id,
        resolve_ws_for_create=registry_service._ws_via_tournament_body,
        resolve_ws_for_list=registry_service._ws_via_tournament_query,
        service_create=lambda s, p, d: tlink_service.create_link(s, p),
        service_update=lambda s, i, p, d: tlink_service.update_link(s, i, p),
        service_delete=lambda s, i, d: tlink_service.deactivate_link(s, i),
        list_fn=registry_service._list_tournament_links,
        not_found_detail="Tournament link not found",
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
