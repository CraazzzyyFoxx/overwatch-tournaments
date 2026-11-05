"""A tournament's flow graph over RPC (spec §6.1, §8): the public read and the admin read."""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.rpc.identity import ensure_workspace_permission, rehydrate_user_optional
from shared.services.tournament.visibility import ensure_tournament_viewable
from src.core import auth
from src.rpc._helpers import _identity, _read, _require_id
from src.services.flow.service import flow_service


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.get_flow")
    async def _get_flow(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament_id = _require_id(data)
            await ensure_tournament_viewable(session, rehydrate_user_optional(data.get("identity")), tournament_id)
            return await flow_service.get_read(session, tournament_id)

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.flow_get")
    async def _flow_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ensure_workspace_permission(
                user, await auth.get_tournament_workspace_id(session, tournament_id), "tournament", "read"
            )
            return await flow_service.get_admin_read(session, tournament_id)

        return await _read(logger, op)
