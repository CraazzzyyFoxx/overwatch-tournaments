"""A tournament's team format over typed RPC: read it with its slot projection, replace it."""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.rpc.identity import ensure_workspace_permission
from shared.schemas.team_format import TeamFormatWrite
from shared.services.audit import record_admin_audit
from shared.services.team_format import team_format_read, tournament_format
from src.core import auth
from src.rpc._helpers import _dump, _identity, _payload, _require_id, _run
from src.services.admin.tournament import tournament_service


async def _read(session: Any, tournament: Any) -> Any:
    team_format, source = await tournament_format(session, tournament)
    return _dump(await team_format_read(session, team_format, source=source, workspace_id=tournament.workspace_id))


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.team_format.get")
    async def _get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, tournament_id = _identity(data), _require_id(data)
            ensure_workspace_permission(
                user, await auth.get_tournament_workspace_id(session, tournament_id), "tournament", "read"
            )
            tournament = await tournament_service.get_team_format_scope(session, tournament_id)
            return await _read(session, tournament)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.team_format.put")
    async def _put(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, tournament_id = _identity(data), _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "tournament", "update")
            body = TeamFormatWrite.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="tournament.team_format_set",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after=body.model_dump(mode="json"),
            )
            tournament = await tournament_service.replace_team_format(session, tournament_id, body)
            return await _read(session, tournament)

        return await _run(logger, op)
