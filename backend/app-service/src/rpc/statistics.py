"""Bespoke statistics + dashboard reads (all public, workspace-filtered)."""

from __future__ import annotations

import typing
from typing import Any

from faststream.rabbit import RabbitMessage

from shared.rpc.query import build_query_model
from src.core import db, pagination
from src.rpc import _common as c
from src.services.dashboard import flows as dashboard_flows
from src.services.statistics import flows as statistics_flows

_SF = db.async_session_maker
_STAT_SORT = typing.Literal["id", "name", "value"]


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.statistics.dashboard")
    async def _dashboard(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await dashboard_flows.get_dashboard_stats(session, workspace_id=c.q1(data, "workspace_id", int))

        return await c.envelope(logger, "statistics.dashboard", op, session_factory=_SF)

    @broker.subscriber("rpc.app.statistics.champion")
    async def _champion(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(pagination.PaginationSortQueryParams[_STAT_SORT], data.get("query"))
            return await statistics_flows.get_most_champions(
                session,
                pagination.PaginationSortParams.from_query_params(qp),
                workspace_id=c.q1(data, "workspace_id", int),
            )

        return await c.envelope(logger, "statistics.champion", op, session_factory=_SF)

    @broker.subscriber("rpc.app.statistics.winrate")
    async def _winrate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(pagination.PaginationSortQueryParams[_STAT_SORT], data.get("query"))
            return await statistics_flows.get_to_winrate_players(
                session,
                pagination.PaginationSortParams.from_query_params(qp),
                workspace_id=c.q1(data, "workspace_id", int),
            )

        return await c.envelope(logger, "statistics.winrate", op, session_factory=_SF)

    @broker.subscriber("rpc.app.statistics.won_maps")
    async def _won_maps(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(pagination.PaginationSortQueryParams[_STAT_SORT], data.get("query"))
            return await statistics_flows.get_to_won_players(
                session,
                pagination.PaginationSortParams.from_query_params(qp),
                workspace_id=c.q1(data, "workspace_id", int),
            )

        return await c.envelope(logger, "statistics.won_maps", op, session_factory=_SF)
