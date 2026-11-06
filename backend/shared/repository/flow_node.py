"""``tournament.flow_node`` reads for services that do not own the flow graph (balancer, draft), and the
``flow_node_schedule`` full-replace write."""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.base import BaseRepository

__all__ = ("FlowNodeRepository", "FlowNodeScheduleRepository")


class FlowNodeRepository(BaseRepository[models.FlowNode]):
    def __init__(self) -> None:
        super().__init__(models.FlowNode)

    async def get_for_share(self, session: AsyncSession, node_id: int) -> models.FlowNode | None:
        """The node row ``FOR SHARE``: held to the end of the transaction, it blocks a concurrent status transition
        (``FOR NO KEY UPDATE``) until the caller commits."""
        return await session.scalar(
            self.select()
            .where(self.model.id == node_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )


class FlowNodeScheduleRepository(BaseRepository[models.FlowNodeSchedule]):
    def __init__(self) -> None:
        super().__init__(models.FlowNodeSchedule)

    async def replace_for_node(
        self, session: AsyncSession, node_id: int, rows: Iterable[models.FlowNodeSchedule]
    ) -> None:
        """Drop the node's schedule rows and insert ``rows``; flushes, never commits."""
        await session.execute(sa.delete(self.model).where(self.model.node_id == node_id))
        await self.create_many(session, list(rows))
