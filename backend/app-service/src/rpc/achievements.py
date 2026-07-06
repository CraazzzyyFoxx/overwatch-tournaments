"""Bespoke achievement reads (users-who-earned + per-user achievements).

list/get go through the shared read engine (read_registry); these two bespoke
shapes (pagination of earners; per-user aggregation with locked entries) stay
here.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.rpc.query import build_query_model
from src.core import db, errors, pagination
from src.rpc import _common as c
from src.services.achievements import flows_v2 as achievements_flows

_SF = db.async_session_maker


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.achievements.users")
    async def _users(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(pagination.PaginationQueryParams, data.get("query"))
            return await achievements_flows.get_achievement_users(
                session, c.require_id(data), pagination.PaginationParams.from_query_params(qp)
            )

        return await c.envelope(logger, "achievements.users", op, session_factory=_SF)

    @broker.subscriber("rpc.app.achievements.user")
    async def _user(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament_id = c.q1(data, "tournament_id", int)
            without_tournament = c.q1(data, "without_tournament", c.qbool, False)
            if tournament_id is not None and without_tournament:
                raise errors.ApiHTTPException(
                    status_code=400,
                    detail=[
                        errors.ApiExc(
                            code="invalid_request",
                            msg="Use either tournament_id or without_tournament=true, not both.",
                        )
                    ],
                )
            return await achievements_flows.get_user_achievements(
                session,
                c.require_id(data),
                c.q(data, "entities") or [],
                tournament_id=tournament_id,
                without_tournament=without_tournament,
                workspace_id=c.q1(data, "workspace_id", int),
                include_locked=c.q1(data, "include_locked", c.qbool, False),
            )

        return await c.envelope(logger, "achievements.user", op, session_factory=_SF)
