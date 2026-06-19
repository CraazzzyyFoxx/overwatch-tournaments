"""Workspace typed-RPC subscribers.

Phase 1: public reads (list + get). Phase 2 adds CRUD (via the shared CRUD
engine) + member management here.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage
from fastapi import HTTPException

from src import schemas
from src.core import db
from src.rpc import _common as c
from src.services.workspace import service as workspace_service

_SF = db.async_session_maker


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.workspaces.list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspaces = await workspace_service.get_all(session)
            return [schemas.WorkspaceRead.model_validate(w, from_attributes=True) for w in workspaces]

        return await c.envelope(logger, "workspaces.list", op, session_factory=_SF)

    @broker.subscriber("rpc.app.workspaces.get")
    async def _get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace = await workspace_service.get_by_id(session, c.require_id(data))
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")
            return schemas.WorkspaceRead.model_validate(workspace, from_attributes=True)

        return await c.envelope(logger, "workspaces.get", op, session_factory=_SF)
