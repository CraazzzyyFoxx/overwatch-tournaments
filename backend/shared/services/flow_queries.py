"""Reads over a tournament's flow graph that more than one service needs (spec §5, §8.3)."""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.core.enums import FlowNodeKind, FlowNodeStatus
from shared.core.flow_state import FINAL_STATUSES, LIFECYCLE_KINDS
from shared.domain.flow.config import RegistrationNodeConfig, parse_node_config
from shared.models.registration.registration import Registration, RegistrationEntry, RegistrationTeam
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.team import Player

__all__ = (
    "downstream_lifecycle_started",
    "input_boundary_tied",
    "input_member_ids",
    "registration_output_rows",
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


async def registration_output_rows(session: AsyncSession, node: FlowNode) -> list[tuple[int, int | None]]:
    """A registration node's ``participants`` output, live: ``(workspace_member_id, registration_team_id)`` in output
    order. The flow engine stores these rows; a reader that must not lag a check-in or approval reads them here."""
    config = parse_node_config(FlowNodeKind.REGISTRATION, node.config)
    assert isinstance(config, RegistrationNodeConfig)

    def qualifies(entry: Any) -> sa.ColumnElement[bool]:
        """The entry is approved (and checked in when the node asks for check-in): it is on the node's output."""
        clause = sa.and_(entry.status == "approved", entry.deleted_at.is_(None))
        return sa.and_(clause, entry.checked_in.is_(True)) if config.check_in else clause

    query = (
        sa.select(Registration.workspace_member_id, Registration.registration_team_id)
        .join(RegistrationEntry, RegistrationEntry.registration_id == Registration.id)
        .where(
            RegistrationEntry.registration_node_id == node.id,
            qualifies(RegistrationEntry),
            Registration.deleted_at.is_(None),
            Registration.workspace_member_id.is_not(None),
        )
        .order_by(RegistrationEntry.reviewed_at.asc().nulls_last(), Registration.id)
    )
    if config.intake == "team":
        # Whole teams only: a complete team none of whose live members is left out (a pending or unchecked member
        # holds the whole team back), emitted with the team id so a registered formation can rebuild it.
        member = aliased(Registration)
        other = aliased(RegistrationEntry)
        held_back = (
            sa.select(sa.literal(1))
            .select_from(member)
            .join(other, other.registration_id == member.id)
            .where(
                member.registration_team_id == RegistrationTeam.id,
                member.deleted_at.is_(None),
                other.registration_node_id == node.id,
                other.deleted_at.is_(None),
                other.status.notin_(("withdrawn", "rejected")),
                ~qualifies(other),
            )
            .exists()
        )
        query = query.join(RegistrationTeam, RegistrationTeam.id == Registration.registration_team_id).where(
            RegistrationTeam.registration_node_id == node.id,
            RegistrationTeam.status == "complete",
            RegistrationTeam.deleted_at.is_(None),
            ~held_back,
        )
    return [(member_id, team_id) for member_id, team_id in await session.execute(query)]


async def input_member_ids(session: AsyncSession, node_id: int) -> list[int]:
    """The members of ``node_id``'s input results, deduplicated in first-seen order.

    Incoming edges in ``FlowEdge.id`` order, each source port's rows by ``rank``; a ``team_id`` row stands for the
    team's players, non-substitutes first. A registration source is read live (:func:`registration_output_rows`):
    its stored rows only move on a flow recompute, which a check-in or an approval does not trigger.
    """
    member = sa.func.coalesce(FlowNodeResult.workspace_member_id, Player.workspace_member_id)
    edges = (
        await session.execute(
            sa.select(FlowEdge.source_node_id, FlowEdge.source_port, FlowNode)
            .join(FlowNode, FlowNode.id == FlowEdge.source_node_id)
            .where(FlowEdge.target_node_id == node_id)
            .order_by(FlowEdge.id)
        )
    ).all()
    members: list[int] = []
    for source_id, source_port, source in edges:
        if source.kind == FlowNodeKind.REGISTRATION:
            members += [member_id for member_id, _team_id in await registration_output_rows(session, source)]
            continue
        members += await session.scalars(
            sa.select(member)
            .select_from(FlowNodeResult)
            .outerjoin(Player, Player.team_id == FlowNodeResult.team_id)
            .where(FlowNodeResult.node_id == source_id, FlowNodeResult.port == source_port, member.is_not(None))
            .order_by(FlowNodeResult.rank, Player.is_substitution.nulls_first(), Player.id.nulls_first())
        )
    return list(dict.fromkeys(members))


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
