"""Bespoke map reads (lookup). get/list go through the shared read engine."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from faststream.rabbit import RabbitMessage

from src import models, schemas
from src.core import db
from src.rpc import _common as c

_SF = db.async_session_maker


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.maps.lookup")
    async def _lookup(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            query = sa.select(models.Map.id, models.Map.name).order_by(models.Map.name)
            result = await session.execute(query)
            return [schemas.LookupItem(id=row.id, name=row.name) for row in result.all()]

        return await c.envelope(logger, "maps.lookup", op, session_factory=_SF)
