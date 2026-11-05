"""The formation node a balancer or draft request names (plan Decision 1, Decision 8).

A balance, a balancer config, a draft and every export belong to one formation node of the tournament.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import FlowNodeKind, FlowNodeStatus
from shared.models.tournament.flow import FlowNode
from shared.repository.flow_node import FlowNodeRepository
from src.domain.draft.errors import err

__all__ = ("require_formation_node", "require_forming")

_nodes = FlowNodeRepository()


async def require_formation_node(session: AsyncSession, tournament_id: int, node_id: int) -> FlowNode:
    """The formation node ``node_id`` of this tournament; 404 ``flow_node_not_found`` for any other id."""
    node = await _nodes.get(session, node_id)
    if node is None or node.tournament_id != tournament_id or node.kind != FlowNodeKind.FORMATION:
        raise err("flow_node_not_found", "Flow node not found", status_code=404)
    return node


async def require_forming(session: AsyncSession, node_id: int) -> FlowNode:
    """The formation node, 409 ``formation_not_forming`` unless it is ``forming``: teams are written only then."""
    node = await _nodes.get(session, node_id)
    if node is None:
        raise err("flow_node_not_found", "Flow node not found", status_code=404)
    if node.status != FlowNodeStatus.FORMING:
        raise err("formation_not_forming", f"Formation node {node_id} is {node.status!r}, not forming")
    return node
