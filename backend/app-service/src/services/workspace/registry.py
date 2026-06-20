"""Workspace CRUD via the shared CRUD engine.

Only update + delete go through the engine — both are workspace-scoped
(``workspace.update`` / ``workspace.delete``, resolved from the path id itself).
``create`` is superuser-global with heavy side-effects (slug check, system roles,
owner member, RBAC cache bust) so it stays a bespoke handler in ``src/rpc/workspaces.py``.
Member management is bespoke too.
"""

from __future__ import annotations

from typing import Any

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.crud import CrudDispatcher, EntityConfig
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import db
from src.services.workspace import service as workspace_service


async def _ser_workspace(session: AsyncSession, obj: Any) -> Any:
    return schemas.WorkspaceRead.model_validate(obj, from_attributes=True).model_dump(mode="json")


async def _ws_self(session: AsyncSession, obj_id: int) -> int:
    # The workspace IS the entity, so the owning workspace id is the path id.
    return obj_id


async def _svc_update(session: AsyncSession, obj_id: int, payload: schemas.WorkspaceUpdate, data: dict[str, Any]) -> Any:
    workspace = await workspace_service.get_by_id(session, obj_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    workspace = await workspace_service.update(session, workspace, payload.model_dump(exclude_unset=True))
    await session.commit()
    return workspace


async def _svc_delete(session: AsyncSession, obj_id: int, data: dict[str, Any]) -> None:
    workspace = await workspace_service.get_by_id(session, obj_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    await workspace_service.delete(session, workspace)
    await session.commit()


REGISTRY: dict[str, EntityConfig] = {
    "workspace": EntityConfig(
        entity="workspace",
        model=models.Workspace,
        permission_resource="workspace",
        serializer=_ser_workspace,
        update_schema=schemas.WorkspaceUpdate,
        resolve_ws_from_id=_ws_self,
        service_update=_svc_update,
        service_delete=_svc_delete,
        not_found_detail="Workspace not found",
        actions=frozenset({"update", "delete"}),
    ),
}

dispatcher = CrudDispatcher(REGISTRY, db.async_session_maker)
