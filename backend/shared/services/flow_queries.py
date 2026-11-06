"""Reads over a tournament's flow graph that more than one service needs (spec §5, §8.3)."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.core.enums import FlowNodeKind, FlowNodeStatus
from shared.core.flow_state import FINAL_STATUSES, LIFECYCLE_KINDS
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.team import Player

__all__ = (
    "downstream_lifecycle_started",
    "input_boundary_tied",
    "input_member_ids",
    "stage_node_status",
    "upstream_registration_node_ids",
)


def _reached(node_id: int, *, towards_targets: bool) -> sa.CTE:
    """Ids of every node reachable from ``node_id`` along the edges, ``node_id`` excluded. UNION ends a cycle."""
    near, far = (
        (FlowEdge.source_node_id, FlowEdge.target_node_id)
        if towards_targets
        else (FlowEdge.target_node_id, FlowEdge.source_node_id)
    )
    reached = sa.select(far.label("id")).where(near == node_id).cte("reached", recursive=True)
    return reached.union(sa.select(far).where(near == reached.c.id))


async def input_member_ids(session: AsyncSession, node_id: int) -> list[int]:
    """The members of ``node_id``'s input results, deduplicated in first-seen order.

    Incoming edges in ``FlowEdge.id`` order, each source port's rows by ``rank``; a ``team_id`` row stands for the
    team's players, non-substitutes first.
    """
    member = sa.func.coalesce(FlowNodeResult.workspace_member_id, Player.workspace_member_id)
    rows = await session.scalars(
        sa.select(member)
        .select_from(FlowEdge)
        .join(
            FlowNodeResult,
            sa.and_(FlowNodeResult.node_id == FlowEdge.source_node_id, FlowNodeResult.port == FlowEdge.source_port),
        )
        .outerjoin(Player, Player.team_id == FlowNodeResult.team_id)
        .where(FlowEdge.target_node_id == node_id, member.is_not(None))
        .order_by(FlowEdge.id, FlowNodeResult.rank, Player.is_substitution.nulls_first(), Player.id.nulls_first())
    )
    return list(dict.fromkeys(rows))


async def upstream_registration_node_ids(session: AsyncSession, node_id: int) -> list[int]:
    """Registration nodes feeding ``node_id`` through any chain of nodes, newest (highest id) first."""
    reached = _reached(node_id, towards_targets=False)
    return list(
        await session.scalars(
            sa.select(FlowNode.id)
            .where(FlowNode.id.in_(sa.select(reached.c.id)), FlowNode.kind == FlowNodeKind.REGISTRATION)
            .order_by(FlowNode.id.desc())
        )
    )


async def downstream_lifecycle_started(session: AsyncSession, node_id: int) -> bool:
    """Whether a lifecycle node downstream of ``node_id`` has left ``draft`` (its input is frozen, spec §8.3)."""
    reached = _reached(node_id, towards_targets=True)
    return bool(
        await session.scalar(
            sa.select(
                sa.exists().where(
                    FlowNode.id.in_(sa.select(reached.c.id)),
                    FlowNode.kind.in_([k.value for k in LIFECYCLE_KINDS]),
                    FlowNode.status != FlowNodeStatus.DRAFT,
                )
            )
        )
    )


def stage_node_status(stage_id_column: sa.ColumnElement[int]) -> sa.ScalarSelect[str]:
    """The status of the node of the stage ``stage_id_column`` names, for a correlated select."""
    return sa.select(FlowNode.status).where(FlowNode.stage_id == stage_id_column).scalar_subquery()


async def input_boundary_tied(session: AsyncSession, node_id: int) -> bool:
    """Whether a ``filter`` feeding ``node_id`` waits on a tie at its cut (spec §5.4).

    The filter is ``tentative`` although every node wired into it is final: only a pin (or a manual filter) resolves it.
    """
    upstream, source = aliased(FlowEdge), aliased(FlowNode)
    return bool(
        await session.scalar(
            sa.select(
                sa.exists().where(
                    FlowEdge.target_node_id == node_id,
                    FlowNode.id == FlowEdge.source_node_id,
                    FlowNode.kind == FlowNodeKind.FILTER,
                    FlowNode.status == FlowNodeStatus.TENTATIVE,
                    ~sa.exists()
                    .where(
                        upstream.target_node_id == FlowNode.id,
                        source.id == upstream.source_node_id,
                        source.status.not_in([s.value for s in FINAL_STATUSES]),
                    )
                    .correlate(FlowNode),
                )
            )
        )
    )
