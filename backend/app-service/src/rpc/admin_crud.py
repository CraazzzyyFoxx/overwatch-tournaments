"""Generic workspace CRUD subscribers (shared engine).

rpc.app.admin.{update,delete} dispatch to the workspace EntityConfig via the
CrudDispatcher (workspace-scoped permission enforced by the engine). create +
member management are bespoke (see src/rpc/workspaces.py).
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from src.services.workspace.registry import dispatcher


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.admin.update")
    async def _admin_update(data: dict, msg: RabbitMessage) -> dict:
        return await dispatcher.do_update(data)

    @broker.subscriber("rpc.app.admin.delete")
    async def _admin_delete(data: dict, msg: RabbitMessage) -> dict:
        return await dispatcher.do_delete(data)
