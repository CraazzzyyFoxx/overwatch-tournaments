"""Bespoke typed-RPC read subscribers for the /users/* surface.

Each handler mirrors a route in ``src/routes/user.py`` 1:1: it rebuilds the
route's query-params model via ``build_query_model`` (or pulls ad-hoc scalars
with ``_common.q*``), reconstructs the WorkspaceContext without FastAPI DI, and
calls the same flow. No route sets ``response_model_exclude_none`` -> default
``exclude_none=False`` serialization (byte-identical to FastAPI).
"""

from __future__ import annotations

import typing
from typing import Any

from faststream.rabbit import RabbitMessage
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.query import build_query_model

from src import schemas
from src.core import db, enums, pagination
from src.core.workspace import get_division_grid, resolve_workspace_context
from src.rpc import _common as c
from src.services.map import flows as map_flows
from src.services.user import flows as user_flows

_SF = db.async_session_maker

_USERS_SORT = typing.Literal["id", "name", "similarity:name"]
_ENCOUNTER_SORT = typing.Literal["id", "name", "home_team_id", "away_team_id", "closeness", "round"]
_MAPS_SORT = typing.Literal["id", "count", "win", "loss", "draw", "winrate", "gamemode_id", "slug", "name"]
_TEAMMATES_SORT = typing.Literal["id", "name", "winrate", "tournaments"]


def _ws_id(data: dict[str, Any]) -> int:
    """Fail-closed workspace scope for the ``/users/*`` domain reads.

    Every ``/users/*`` read is workspace-scoped and the frontend always sends
    ``workspace_id``. A missing scope is treated as a bug: returning unfiltered
    rows would span every workspace (cross-tenant leak — see H8), so raise 400
    instead of defaulting to ``None``. A deliberate cross-workspace read must go
    through ``resolve_workspace_context(..., ALL_WORKSPACES)`` explicitly, not
    this helper.
    """
    workspace_id = c.q1(data, "workspace_id", int)
    if workspace_id is None:
        raise HTTPException(status_code=400, detail="workspace_id query parameter is required")
    return workspace_id


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.users.list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(pagination.PaginationSortSearchQueryParams[_USERS_SORT], data.get("query"))
            return await user_flows.get_all(session, pagination.PaginationSortSearchParams.from_query_params(qp))

        return await c.envelope(logger, "users.list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.search")
    async def _search(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            query = c.q1(data, "query", str, "")
            fields = c.q(data, "fields") or []
            return await user_flows.search_by_name(session, query, fields)

        return await c.envelope(logger, "users.search", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.overview")
    async def _overview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ws = await resolve_workspace_context(session, _ws_id(data))
            qp = build_query_model(schemas.UserOverviewQueryParams, data.get("query"))
            return await user_flows.get_overview(
                session,
                schemas.UserOverviewParams.from_query_params(qp),
                workspace_id=ws.id,
                grid=ws.grid,
                normalizer=ws.normalizer,
            )

        return await c.envelope(logger, "users.overview", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.overview_stats")
    async def _overview_stats(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ws = await resolve_workspace_context(session, _ws_id(data))
            # Route passes the QueryParams model straight to the flow (no from_query_params).
            params = build_query_model(schemas.UserOverviewStatsQueryParams, data.get("query"))
            return await user_flows.get_overview_stats(session, params, grid=ws.grid, workspace_id=ws.id)

        return await c.envelope(logger, "users.overview_stats", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.overview_catalog")
    async def _overview_catalog(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ws = await resolve_workspace_context(session, _ws_id(data))
            qp = build_query_model(schemas.UserCatalogQueryParams, data.get("query"))
            return await user_flows.get_catalog(
                session,
                schemas.UserCatalogParams.from_query_params(qp),
                grid=ws.grid,
                normalizer=ws.normalizer,
                workspace_id=ws.id,
            )

        return await c.envelope(logger, "users.overview_catalog", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.compare")
    async def _compare(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            grid = await get_division_grid(session, None)
            qp = build_query_model(schemas.UserCompareQueryParams, data.get("query"))
            return await user_flows.get_compare(
                session, c.require_id(data), schemas.UserCompareParams.from_query_params(qp), grid=grid
            )

        return await c.envelope(logger, "users.compare", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.compare_heroes")
    async def _compare_heroes(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            grid = await get_division_grid(session, None)
            qp = build_query_model(schemas.UserHeroCompareQueryParams, data.get("query"))
            return await user_flows.get_hero_compare(
                session, c.require_id(data), schemas.UserHeroCompareParams.from_query_params(qp), grid=grid
            )

        return await c.envelope(logger, "users.compare_heroes", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.by_name")
    async def _by_name(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            name = str(data.get("name", "")).replace("-", "#")
            entities = c.q(data, "entities") or []
            if "#" in name:
                return await user_flows.get_by_battle_tag(session, name, entities)
            return await user_flows.get_by_discord(session, name, entities)

        return await c.envelope(logger, "users.by_name", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.get_profile")
    async def _get_profile(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ws = await resolve_workspace_context(session, _ws_id(data))
            return await user_flows.get_profile(session, c.require_id(data), workspace_id=ws.id, grid=ws.grid)

        return await c.envelope(logger, "users.get_profile", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.tournaments")
    async def _tournaments(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ws = await resolve_workspace_context(session, _ws_id(data))
            return await user_flows.get_tournaments(session, c.require_id(data), workspace_id=ws.id, grid=ws.grid)

        return await c.envelope(logger, "users.tournaments", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.tournament")
    async def _tournament(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament_id = int(data["tournament_id"])
            grid = await get_division_grid(session, None, tournament_id)
            return await user_flows.get_tournament_with_stats(session, c.require_id(data), tournament_id, grid=grid)

        return await c.envelope(logger, "users.tournament", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.maps")
    async def _maps(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(schemas.UserMapsSearchQueryParams[_MAPS_SORT], data.get("query"))
            return await map_flows.get_top_user(
                session, c.require_id(data), schemas.UserMapsSearchParams.from_query_params(qp), workspace_id=_ws_id(data)
            )

        return await c.envelope(logger, "users.maps", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.maps_summary")
    async def _maps_summary(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(schemas.UserMapsSearchQueryParams[_MAPS_SORT], data.get("query"))
            return await map_flows.get_top_user_summary(
                session, c.require_id(data), schemas.UserMapsSearchParams.from_query_params(qp), workspace_id=_ws_id(data)
            )

        return await c.envelope(logger, "users.maps_summary", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.encounters")
    async def _encounters(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(pagination.PaginationSortQueryParams[_ENCOUNTER_SORT], data.get("query"))
            return await user_flows.get_encounters_by_user(
                session,
                c.require_id(data),
                pagination.PaginationSortParams.from_query_params(qp),
                workspace_id=_ws_id(data),
                result=c.q1(data, "result", str, None),
                stage=c.q1(data, "stage", str, None),
                mvp1=c.q1(data, "mvp1", c.qbool, False),
                has_logs=c.q1(data, "has_logs", c.qbool, None),
                opponent=c.q1(data, "opponent", str, None),
            )

        return await c.envelope(logger, "users.encounters", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.matches_summary")
    async def _matches_summary(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await user_flows.get_matches_summary(session, c.require_id(data), workspace_id=_ws_id(data))

        return await c.envelope(logger, "users.matches_summary", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.heroes")
    async def _heroes(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(pagination.PaginationQueryParams, data.get("query"))
            raw_stats = c.q(data, "stats") or []
            try:
                stats = [enums.LogStatsName(s) for s in raw_stats]
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"invalid stats value: {exc}") from exc
            return await user_flows.get_heroes(
                session,
                c.require_id(data),
                pagination.PaginationParams.from_query_params(qp),
                stats,
                tournament_id=c.q1(data, "tournament_id", int),
                workspace_id=_ws_id(data),
            )

        return await c.envelope(logger, "users.heroes", op, session_factory=_SF)

    @broker.subscriber("rpc.app.users.teammates")
    async def _teammates(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(pagination.PaginationSortQueryParams[_TEAMMATES_SORT], data.get("query"))
            return await user_flows.get_best_teammates(
                session, c.require_id(data), pagination.PaginationSortParams.from_query_params(qp), workspace_id=_ws_id(data)
            )

        return await c.envelope(logger, "users.teammates", op, session_factory=_SF)
