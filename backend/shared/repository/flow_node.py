"""``tournament.flow_node`` reads for services that do not own the flow graph (balancer, draft)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.base import BaseRepository

__all__ = ("FlowNodeRepository",)


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
