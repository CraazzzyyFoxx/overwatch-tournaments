"""Tournament status derived from the status of its flow nodes (spec §9)."""

from collections.abc import Sequence
from dataclasses import dataclass

from shared.core.enums import FlowNodeKind, FlowNodeStatus, TournamentStatus

LIFECYCLE_KINDS: frozenset[FlowNodeKind] = frozenset(
    {FlowNodeKind.REGISTRATION, FlowNodeKind.FORMATION, FlowNodeKind.STAGE}
)
PURE_KINDS: frozenset[FlowNodeKind] = frozenset(FlowNodeKind) - LIFECYCLE_KINDS

_DONE: frozenset[FlowNodeStatus] = frozenset({FlowNodeStatus.COMPLETED, FlowNodeStatus.FINAL})


@dataclass(frozen=True, slots=True)
class FlowNodeState:
    kind: FlowNodeKind
    status: FlowNodeStatus
    is_sink: bool


def derive_tournament_status(nodes: Sequence[FlowNodeState]) -> TournamentStatus:
    """ANNOUNCEMENT while no lifecycle node has left draft, COMPLETED once every sink is done, else LIVE.

    ARCHIVED is a manual overlay and is never derived.
    """
    if all(x.status is FlowNodeStatus.DRAFT for x in nodes if x.kind in LIFECYCLE_KINDS):
        return TournamentStatus.ANNOUNCEMENT
    if all(x.status in _DONE for x in nodes if x.is_sink):
        return TournamentStatus.COMPLETED
    return TournamentStatus.LIVE
