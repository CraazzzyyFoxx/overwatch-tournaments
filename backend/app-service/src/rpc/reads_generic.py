"""Generic public-read subscribers backed by the shared CRUD engine.

hero/map/gamemode/achievement get+list are dispatched here via
``rpc.app.read.{get,list}`` (the gateway sets ``data["entity"]``). See
``src/services/read_registry.py`` for the EntityConfig table.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from src.services.read_registry import dispatcher


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.read.get")
    async def _read_get(data: dict, msg: RabbitMessage) -> dict:
        return await dispatcher.do_get(data)

    @broker.subscriber("rpc.app.read.list")
    async def _read_list(data: dict, msg: RabbitMessage) -> dict:
        return await dispatcher.do_list(data)
