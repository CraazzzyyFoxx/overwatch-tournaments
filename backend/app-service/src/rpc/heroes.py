"""Bespoke hero reads (lookup + playtime + leaderboard).

get/list go through the shared read engine (see read_registry); only the
aggregations and the lookup projection live here.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.rpc.query import build_query_model
from src import schemas
from src.core import db
from src.core.workspace import resolve_workspace_context
from src.rpc import _common as c
from src.services.hero.service import heroes as hero_service

_SF = db.async_session_maker


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.heroes.lookup")
    async def _lookup(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await hero_service.lookup(session)

        return await c.envelope(logger, "heroes.lookup", op, session_factory=_SF)

    @broker.subscriber("rpc.app.heroes.playtime")
    async def _playtime(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            await c.gate_tournament(session, data, c.q1(data, "tournament_id", int))
            qp = build_query_model(schemas.HeroPlaytimeQueryPaginationParams, data.get("query"))
            return await hero_service.get_playtime(
                session,
                schemas.HeroPlaytimePaginationParams.from_query_params(qp),
                workspace_id=c.q1(data, "workspace_id", int),
            )

        return await c.envelope(logger, "heroes.playtime", op, session_factory=_SF)

    @broker.subscriber("rpc.app.heroes.leaderboard")
    async def _leaderboard(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            await c.gate_tournament(session, data, c.q1(data, "tournament_id", int))
            ws = await resolve_workspace_context(session, c.q_workspace_scope(data))
            qp = build_query_model(schemas.HeroLeaderboardQueryParams, data.get("query"))
            return await hero_service.get_hero_leaderboard(
                session,
                hero_id=c.require_id(data),
                params=schemas.HeroLeaderboardParams.from_query_params(qp),
                workspace_id=ws.id,
                grid=ws.grid,
            )

        return await c.envelope(logger, "heroes.leaderboard", op, session_factory=_SF)
