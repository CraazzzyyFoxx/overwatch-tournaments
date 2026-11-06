"""A tournament's flow graph over RPC (spec §6.1, §8): the public read and the admin read."""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.rpc.identity import ensure_workspace_permission, rehydrate_user_optional
from shared.services.audit import record_admin_audit
from shared.services.tournament.visibility import ensure_tournament_viewable
from src.core import auth
from src.rpc._helpers import _dump, _identity, _payload, _read, _require_id, _run
from src.schemas import flow as flow_schemas
from src.services.flow.lifecycle import flow_node_service
from src.services.flow.schedule import flow_node_schedule_service
from src.services.flow.service import flow_service


async def _node_scope(session: Any, node_id: int) -> tuple[int, int]:
    """The node's tournament and that tournament's workspace; 404 for a missing node."""
    tournament_id = await flow_service.node_tournament_id(session, node_id)
    return tournament_id, await auth.get_tournament_workspace_id(session, tournament_id)


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

    @broker.subscriber("rpc.tournament.flow_node_transition")
    async def _flow_node_transition(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            node_id = _require_id(data)
            tournament_id, ws_id = await _node_scope(session, node_id)
            ensure_workspace_permission(user, ws_id, "tournament", "update")
            body = flow_schemas.FlowNodeTransition.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="flow_node.transition",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="flow_node",
                entity_id=node_id,
                after={"status": body.status.value},
            )
            await flow_node_service.transition(session, node_id, body.status, actor=user)
            await session.commit()
            return _dump(await flow_service.get_node_read(session, tournament_id, node_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.flow_node_schedule_set")
    async def _flow_node_schedule_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            node_id = _require_id(data)
            tournament_id, ws_id = await _node_scope(session, node_id)
            ensure_workspace_permission(user, ws_id, "tournament", "update")
            body = flow_schemas.FlowNodeScheduleSet.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="flow_node.schedule",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="flow_node",
                entity_id=node_id,
                after=body.model_dump(mode="json"),
            )
            await flow_node_schedule_service.set_schedule(session, node_id, body.schedule)
            await session.commit()
            return _dump(await flow_service.get_node_read(session, tournament_id, node_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.flow_apply")
    async def _flow_apply(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "tournament", "update")
            body = flow_schemas.FlowChanges.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="tournament.flow_apply",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after=body.model_dump(mode="json"),
            )
            read = await flow_service.apply_changes(session, tournament_id, body, actor=user)
            await session.commit()
            return _dump(read)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.flow_validate")
    async def _flow_validate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ensure_workspace_permission(
                user, await auth.get_tournament_workspace_id(session, tournament_id), "tournament", "update"
            )
            body = flow_schemas.FlowChanges.model_validate(_payload(data))
            return _dump(await flow_service.validate_changes(session, tournament_id, body))

        return await _run(logger, op)
