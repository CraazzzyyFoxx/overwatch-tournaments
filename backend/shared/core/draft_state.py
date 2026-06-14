from shared.core.enums import DraftStatus
from shared.core.errors import ApiExc, ApiHTTPException

# Legal status transitions for a draft session.
#
# COMPLETED is reachable only from LIVE and only via a *system* transition
# (the final pick is finalized) — never by an admin button, so a half-filled
# board can't be finalized. Export is a side-effect/flag, not a status change.
# PAUSED remembers the current pick so resume re-arms the same pick.
_VALID_TRANSITIONS: dict[DraftStatus, frozenset[DraftStatus]] = {
    DraftStatus.SETUP: frozenset({DraftStatus.READY, DraftStatus.CANCELLED}),
    DraftStatus.READY: frozenset({DraftStatus.SETUP, DraftStatus.LIVE, DraftStatus.CANCELLED}),
    DraftStatus.LIVE: frozenset({DraftStatus.PAUSED, DraftStatus.COMPLETED, DraftStatus.CANCELLED}),
    DraftStatus.PAUSED: frozenset({DraftStatus.LIVE, DraftStatus.PAUSED, DraftStatus.CANCELLED}),
    DraftStatus.COMPLETED: frozenset({DraftStatus.PAUSED}),
    DraftStatus.CANCELLED: frozenset(),
}

_TERMINAL_STATUSES: frozenset[DraftStatus] = frozenset({DraftStatus.COMPLETED, DraftStatus.CANCELLED})


def can_transition(current: DraftStatus, target: DraftStatus) -> bool:
    return target in _VALID_TRANSITIONS.get(current, frozenset())


def validate_transition(current: DraftStatus, target: DraftStatus) -> None:
    if not can_transition(current, target):
        allowed = _VALID_TRANSITIONS.get(current, frozenset())
        raise ApiHTTPException(
            status_code=400,
            detail=[
                ApiExc(
                    code="invalid_draft_transition",
                    msg=(
                        f"Cannot transition draft from '{current}' to '{target}'. "
                        f"Allowed transitions: {sorted(s.value for s in allowed)}"
                    ),
                )
            ],
        )


def is_terminal(status: DraftStatus) -> bool:
    return status in _TERMINAL_STATUSES
