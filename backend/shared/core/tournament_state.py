from shared.core.enums import TournamentStatus
from shared.core.errors import ApiExc, ApiHTTPException

_VALID_TRANSITIONS: dict[TournamentStatus, frozenset[TournamentStatus]] = {
    TournamentStatus.REGISTRATION: frozenset({TournamentStatus.DRAFT}),
    TournamentStatus.DRAFT: frozenset({TournamentStatus.CHECK_IN, TournamentStatus.LIVE}),
    TournamentStatus.CHECK_IN: frozenset({TournamentStatus.LIVE}),
    TournamentStatus.LIVE: frozenset({TournamentStatus.PLAYOFFS, TournamentStatus.COMPLETED}),
    TournamentStatus.PLAYOFFS: frozenset({TournamentStatus.COMPLETED}),
    TournamentStatus.COMPLETED: frozenset({TournamentStatus.ARCHIVED}),
    TournamentStatus.ARCHIVED: frozenset({TournamentStatus.COMPLETED}),
}

_FINISHED_STATUSES: frozenset[TournamentStatus] = frozenset(
    {TournamentStatus.COMPLETED, TournamentStatus.ARCHIVED}
)


def can_transition(current: TournamentStatus, target: TournamentStatus) -> bool:
    return target in _VALID_TRANSITIONS.get(current, frozenset())


def validate_transition(current: TournamentStatus, target: TournamentStatus) -> None:
    if not can_transition(current, target):
        allowed = _VALID_TRANSITIONS.get(current, frozenset())
        raise ApiHTTPException(
            status_code=400,
            detail=[
                ApiExc(
                    code="invalid_status_transition",
                    msg=(
                        f"Cannot transition from '{current}' to '{target}'. "
                        f"Allowed transitions: {sorted(s.value for s in allowed)}"
                    ),
                )
            ],
        )


def is_finished_for_status(status: TournamentStatus) -> bool:
    return status in _FINISHED_STATUSES
