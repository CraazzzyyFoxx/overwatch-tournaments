"""The one writer of lifecycle node statuses (spec §5, §8.3, §9).

Registration, formation and stage nodes move only through ``FlowNodeService.transition``; the tournament status is
re-derived from the nodes in the same transaction.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import FlowNodeKind, FlowNodeStatus, TournamentStatus
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.flow_state import FlowNodeState, derive_tournament_status, tournament_status_after, validate_transition
from shared.core.tournament_state import is_finished_for_status
from shared.services.flow_queries import downstream_lifecycle_started
from shared.services.participant_result import write_participant_results
from shared.services.realtime import Resource
from src.services.flow.engine import flow_engine
from src.services.tournament.events import (
    enqueue_achievement_evaluation,
    enqueue_flow_node_state_changed,
    enqueue_tournament_state_changed,
    publish_tournament_invalidation,
)

__all__ = ("FlowNodeService", "flow_node_service")

_S = FlowNodeStatus
#: The status at which a node's output is final: registration closed, formation/stage completed, pure node final.
_FINAL = frozenset({_S.CLOSED, _S.COMPLETED, _S.FINAL})
#: Moving into these stamps ``completed_at``; moving out clears it.
_COMPLETE = frozenset({_S.CLOSED, _S.COMPLETED})
#: Reopening one of these changes an input that downstream nodes froze (spec §8.3).
_REOPENS = frozenset(
    {(FlowNodeKind.REGISTRATION, _S.CLOSED, _S.OPEN), (FlowNodeKind.FORMATION, _S.COMPLETED, _S.FORMING)}
)

#: Side effects of one move, run before the status is written; later tasks register entries.
_HOOKS: dict[
    tuple[FlowNodeKind, FlowNodeStatus, FlowNodeStatus], Callable[[AsyncSession, models.FlowNode], Awaitable[None]]
] = {}


def _conflict(code: str, msg: str) -> ApiHTTPException:
    return ApiHTTPException(status_code=409, detail=[ApiExc(code=code, msg=msg)])


class FlowNodeService:
    async def transition(
        self,
        session: AsyncSession,
        node_id: int,
        target: FlowNodeStatus,
        *,
        automated: bool = False,
        actor: models.AuthUser | None,
    ) -> models.FlowNode:
        """Move a node to ``target``; locks the node row, flushes, never commits."""
        node = await session.scalar(
            sa.select(models.FlowNode)
            .where(models.FlowNode.id == node_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if node is None:
            raise ApiHTTPException(
                status_code=404, detail=[ApiExc(code="flow_node_not_found", msg="Flow node not found")]
            )
        kind, current = FlowNodeKind(node.kind), FlowNodeStatus(node.status)
        validate_transition(kind, current, target)
        if current == _S.DRAFT and kind != FlowNodeKind.REGISTRATION:
            await self._assert_inputs_final(session, node)
        if (kind, current, target) in _REOPENS:
            await self._assert_downstream_not_started(session, node)
        if hook := _HOOKS.get((kind, current, target)):
            await hook(session, node)

        now = datetime.now(UTC)
        node.status = target.value
        if current == _S.DRAFT and node.started_at is None:
            node.started_at = now
        if target in _COMPLETE:
            node.completed_at = now
        elif current in _COMPLETE:
            node.completed_at = None
        workspace_id = await session.scalar(
            sa.select(models.Tournament.workspace_id).where(models.Tournament.id == node.tournament_id)
        )
        await enqueue_flow_node_state_changed(session, node, workspace_id=workspace_id, old_status=current.value)
        await flow_engine.recompute(session, node.tournament_id)
        await self.sync_tournament_status(session, node.tournament_id)
        await publish_tournament_invalidation(
            session, node.tournament_id, (Resource.TOURNAMENT_FLOW, Resource.TOURNAMENT_STRUCTURE)
        )
        return node

    async def sync_tournament_status(self, session: AsyncSession, tournament_id: int) -> TournamentStatus:
        """Write the status the nodes derive (spec §9); emits the state event and the finish effects on a change."""
        tournament = await session.scalar(
            sa.select(models.Tournament)
            .where(models.Tournament.id == tournament_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if tournament is None:
            raise ApiHTTPException(
                status_code=404, detail=[ApiExc(code="tournament_not_found", msg="Tournament not found")]
            )
        has_outgoing = sa.exists().where(models.FlowEdge.source_node_id == models.FlowNode.id)
        rows = await session.execute(
            sa.select(models.FlowNode.kind, models.FlowNode.status, ~has_outgoing).where(
                models.FlowNode.tournament_id == tournament_id
            )
        )
        derived = derive_tournament_status(
            [FlowNodeState(FlowNodeKind(kind), FlowNodeStatus(status), is_sink) for kind, status, is_sink in rows]
        )
        old = tournament.status
        new = tournament_status_after(old, derived)
        if new == old:
            return new
        was_finished = tournament.is_finished
        tournament.status = new
        tournament.is_finished = is_finished_for_status(new)
        if tournament.is_finished != was_finished:
            await write_participant_results(session, tournament_id)
            await enqueue_achievement_evaluation(session, tournament, ["tournament.participant_result"])
        await enqueue_tournament_state_changed(session, tournament, old_status=old.value, new_status=new.value)
        await session.flush()
        return new

    async def _assert_inputs_final(self, session: AsyncSession, node: models.FlowNode) -> None:
        """Every node wired into ``node`` has its final output (a lifecycle input freezes at its first move, §8.3)."""
        not_final = await session.scalar(
            sa.select(
                sa.exists()
                .where(models.FlowEdge.target_node_id == node.id, models.FlowNode.id == models.FlowEdge.source_node_id)
                .where(models.FlowNode.status.not_in([s.value for s in _FINAL]))
            )
        )
        if not_final:
            raise _conflict("input_not_final", "An input of this node is not final yet")

    async def _assert_downstream_not_started(self, session: AsyncSession, node: models.FlowNode) -> None:
        if await downstream_lifecycle_started(session, node.id):
            raise _conflict("downstream_started", "A node downstream of this one has already started")


flow_node_service = FlowNodeService()
