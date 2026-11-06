"""A lifecycle node's schedule (``flow_node_schedule``): full-replace write (spec §9).

``starts_at`` of a row is the moment the scheduler (``services/tournament/auto_transitions.py``) moves the node
(``SCHEDULE_TRANSITIONS``); ``ends_at`` only closes the phase's action window and never changes a status.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import FlowNodeKind
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.flow_state import SCHEDULE_PHASES
from shared.core.tournament_state import as_utc
from shared.repository.flow_node import FlowNodeRepository, FlowNodeScheduleRepository
from shared.services.realtime import Resource
from src.schemas.flow import FlowNodeScheduleEntry
from src.services.tournament.events import publish_tournament_invalidation

__all__ = ("FlowNodeScheduleService", "flow_node_schedule_service")


def _unprocessable(code: str, msg: str) -> ApiHTTPException:
    return ApiHTTPException(status_code=422, detail=[ApiExc(code=code, msg=msg)])


class FlowNodeScheduleService:
    def __init__(
        self,
        *,
        nodes: FlowNodeRepository = FlowNodeRepository(),
        schedules: FlowNodeScheduleRepository = FlowNodeScheduleRepository(),
    ) -> None:
        self.nodes = nodes
        self.schedules = schedules

    async def set_schedule(
        self, session: AsyncSession, node_id: int, entries: list[FlowNodeScheduleEntry]
    ) -> models.FlowNode:
        """Replace the node's schedule with ``entries``; flushes, never commits."""
        node = await self.nodes.get(session, node_id)
        if node is None:
            raise ApiHTTPException(
                status_code=404, detail=[ApiExc(code="flow_node_not_found", msg="Flow node not found")]
            )
        kind = FlowNodeKind(node.kind)
        allowed = SCHEDULE_PHASES.get(kind, frozenset())
        seen: dict[str, FlowNodeScheduleEntry] = {}
        for entry in entries:
            if entry.phase not in allowed:
                raise _unprocessable("invalid_schedule_phase", f"A {kind} node has no '{entry.phase}' phase")
            if entry.phase in seen:
                raise _unprocessable("invalid_schedule", f"Duplicate schedule entry for phase '{entry.phase}'")
            if entry.ends_at is not None and as_utc(entry.ends_at) <= as_utc(entry.starts_at):
                raise _unprocessable("invalid_schedule", f"Phase '{entry.phase}' must end after it starts")
            seen[entry.phase] = entry
        opens, check_in = seen.get("open"), seen.get("check_in")
        if opens is not None and check_in is not None and as_utc(check_in.starts_at) <= as_utc(opens.starts_at):
            raise _unprocessable("invalid_schedule", "Check-in must start after registration opens")

        await self.schedules.replace_for_node(
            session,
            node_id,
            [
                models.FlowNodeSchedule(node_id=node_id, phase=e.phase, starts_at=e.starts_at, ends_at=e.ends_at)
                for e in entries
            ],
        )
        await publish_tournament_invalidation(
            session, node.tournament_id, (Resource.TOURNAMENT_FLOW, Resource.TOURNAMENT_STRUCTURE)
        )
        return node


flow_node_schedule_service = FlowNodeScheduleService()
