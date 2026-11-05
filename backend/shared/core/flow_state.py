"""Tournament status derived from the status of its flow nodes (spec §9)."""

from collections.abc import Sequence
from dataclasses import dataclass

from shared.core.enums import FlowNodeKind, FlowNodeStatus, TournamentStatus
from shared.core.errors import ApiExc, ApiHTTPException

LIFECYCLE_KINDS: frozenset[FlowNodeKind] = frozenset(
    {FlowNodeKind.REGISTRATION, FlowNodeKind.FORMATION, FlowNodeKind.STAGE}
)
PURE_KINDS: frozenset[FlowNodeKind] = frozenset(FlowNodeKind) - LIFECYCLE_KINDS

_DONE: frozenset[FlowNodeStatus] = frozenset({FlowNodeStatus.COMPLETED, FlowNodeStatus.FINAL})

_K = FlowNodeKind
_S = FlowNodeStatus

# Admin-driven lifecycles of the kinds with one (spec §5). Every status is a key so a dead end is refused, not a KeyError.
_VALID_TRANSITIONS: dict[FlowNodeKind, dict[FlowNodeStatus, frozenset[FlowNodeStatus]]] = {
    _K.REGISTRATION: {
        _S.DRAFT: frozenset({_S.OPEN}),
        _S.OPEN: frozenset({_S.CHECK_IN, _S.CLOSED}),
        _S.CHECK_IN: frozenset({_S.CLOSED}),
        _S.CLOSED: frozenset({_S.OPEN}),
    },
    _K.FORMATION: {
        _S.DRAFT: frozenset({_S.FORMING}),
        _S.FORMING: frozenset({_S.DRAFT, _S.COMPLETED}),
        _S.COMPLETED: frozenset({_S.FORMING}),
    },
    _K.STAGE: {
        _S.DRAFT: frozenset({_S.READY}),
        _S.READY: frozenset({_S.DRAFT, _S.LIVE}),
        _S.LIVE: frozenset({_S.COMPLETED}),
        _S.COMPLETED: frozenset({_S.LIVE}),
    },
}

# (source, target) per schedulable phase (Task 9 scheduler).
SCHEDULE_TRANSITIONS: dict[tuple[FlowNodeKind, str], tuple[FlowNodeStatus, FlowNodeStatus]] = {
    (_K.REGISTRATION, "open"): (_S.DRAFT, _S.OPEN),
    (_K.REGISTRATION, "check_in"): (_S.OPEN, _S.CHECK_IN),
    (_K.FORMATION, "start"): (_S.DRAFT, _S.FORMING),
    (_K.STAGE, "start"): (_S.READY, _S.LIVE),
}
SCHEDULE_PHASES: dict[FlowNodeKind, frozenset[str]] = {
    _K.REGISTRATION: frozenset({"open", "check_in"}),
    _K.FORMATION: frozenset({"start"}),
    _K.STAGE: frozenset({"start"}),
}


@dataclass(frozen=True, slots=True)
class FlowNodeState:
    kind: FlowNodeKind
    status: FlowNodeStatus
    is_sink: bool


def derive_tournament_status(nodes: Sequence[FlowNodeState]) -> TournamentStatus:
    """ANNOUNCEMENT while no lifecycle node has left draft, COMPLETED once every sink is done, else LIVE.

    ARCHIVED is a manual overlay and is never derived.
    """
    if all(x.status == FlowNodeStatus.DRAFT for x in nodes if x.kind in LIFECYCLE_KINDS):
        return TournamentStatus.ANNOUNCEMENT
    if all(x.status in _DONE for x in nodes if x.is_sink):
        return TournamentStatus.COMPLETED
    return TournamentStatus.LIVE


def tournament_status_after(current: TournamentStatus, derived: TournamentStatus) -> TournamentStatus:
    """ARCHIVED is sticky while the flow is still complete; any other derived status wins."""
    if current is TournamentStatus.ARCHIVED and derived is TournamentStatus.COMPLETED:
        return TournamentStatus.ARCHIVED
    return derived


def can_transition(kind: FlowNodeKind, current: FlowNodeStatus, target: FlowNodeStatus) -> bool:
    return target in _VALID_TRANSITIONS.get(kind, {}).get(current, frozenset())


def validate_transition(kind: FlowNodeKind, current: FlowNodeStatus, target: FlowNodeStatus) -> None:
    if not can_transition(kind, current, target):
        raise ApiHTTPException(
            status_code=409,
            detail=[
                ApiExc(code="invalid_node_transition", msg=f"A {kind} node cannot move from {current} to {target}")
            ],
        )
