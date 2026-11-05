"""``tournament.flow_node`` reads for services that do not own the flow graph (balancer, draft)."""

from __future__ import annotations

from shared import models
from shared.repository.base import BaseRepository

__all__ = ("FlowNodeRepository",)


class FlowNodeRepository(BaseRepository[models.FlowNode]):
    def __init__(self) -> None:
        super().__init__(models.FlowNode)
