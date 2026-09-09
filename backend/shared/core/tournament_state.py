"""Tournament lifecycle state machine and schedule helpers.

Phases run ANNOUNCEMENT -> REGISTRATION -> [CHECK_IN] -> [DRAFT] -> LIVE ->
[PLAYOFFS] -> COMPLETED <-> ARCHIVED. CHECK_IN is optional and DRAFT is the
team-draft phase (team_formation="draft" only), so forward transitions may skip
phases. Rollback edges cover prior effective phases so admins can e.g. reopen
registration without the superuser ``force`` bypass.

ANNOUNCEMENT is where every tournament starts: public and readable, but with
nothing to do yet. It carries no schedule row of its own — it ends when the
REGISTRATION row comes due, which is the same clock that used to leave a fresh
tournament sitting in REGISTRATION with registration closed.

Time-driven automation (the tournament-worker tick) advances the status
forward only, using ``tournament_phase_schedule`` rows: a row's ``starts_at``
is the moment its phase begins; ``ends_at`` never changes the status — it only
closes the phase's action window early (see ``is_within_phase_window``).
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from shared.core.enums import TournamentStatus
from shared.core.errors import ApiExc, ApiHTTPException

_VALID_TRANSITIONS: dict[TournamentStatus, frozenset[TournamentStatus]] = {
    TournamentStatus.ANNOUNCEMENT: frozenset(
        {
            TournamentStatus.REGISTRATION,
            TournamentStatus.CHECK_IN,
            TournamentStatus.DRAFT,
            TournamentStatus.LIVE,
        }
    ),
    TournamentStatus.REGISTRATION: frozenset(
        {
            TournamentStatus.CHECK_IN,
            TournamentStatus.DRAFT,
            TournamentStatus.LIVE,
            TournamentStatus.ANNOUNCEMENT,
        }
    ),
    TournamentStatus.CHECK_IN: frozenset(
        {TournamentStatus.DRAFT, TournamentStatus.LIVE, TournamentStatus.REGISTRATION}
    ),
    TournamentStatus.DRAFT: frozenset(
        {TournamentStatus.LIVE, TournamentStatus.CHECK_IN, TournamentStatus.REGISTRATION}
    ),
    TournamentStatus.LIVE: frozenset(
        {TournamentStatus.PLAYOFFS, TournamentStatus.COMPLETED, TournamentStatus.DRAFT, TournamentStatus.CHECK_IN}
    ),
    TournamentStatus.PLAYOFFS: frozenset({TournamentStatus.COMPLETED}),
    TournamentStatus.COMPLETED: frozenset({TournamentStatus.ARCHIVED}),
    TournamentStatus.ARCHIVED: frozenset({TournamentStatus.COMPLETED}),
}

# Terminal statuses: the tournament is over. Public because three services used
# to carry their own literal pair of them (rank collection, the registration
# backfill script, the registration gate) — this module owns the fact.
FINISHED_STATUSES: frozenset[TournamentStatus] = frozenset({TournamentStatus.COMPLETED, TournamentStatus.ARCHIVED})

# Matches are being played right now. PLAYOFFS is in and CHECK_IN is not: what
# a visitor reads as "live" is a ball in play, not a lobby filling up.
IN_PLAY_STATUSES: tuple[TournamentStatus, ...] = (TournamentStatus.LIVE, TournamentStatus.PLAYOFFS)

# Canonical ordering of lifecycle phases; automation only ever moves forward
# along this order.
PHASE_ORDER: dict[TournamentStatus, int] = {
    TournamentStatus.ANNOUNCEMENT: 0,
    TournamentStatus.REGISTRATION: 1,
    TournamentStatus.CHECK_IN: 2,
    TournamentStatus.DRAFT: 3,
    TournamentStatus.LIVE: 4,
    TournamentStatus.PLAYOFFS: 5,
    TournamentStatus.COMPLETED: 6,
    TournamentStatus.ARCHIVED: 7,
}

# Phases that may carry a ``tournament_phase_schedule`` row. PLAYOFFS and
# COMPLETED depend on the actual course of play and stay manual/event-driven.
SCHEDULABLE_STATUSES: frozenset[TournamentStatus] = frozenset(
    {
        TournamentStatus.REGISTRATION,
        TournamentStatus.DRAFT,
        TournamentStatus.CHECK_IN,
        TournamentStatus.LIVE,
    }
)

# Statuses the automation tick moves *from* (time drives transitions only up
# to LIVE). ANNOUNCEMENT is in: the REGISTRATION row's ``starts_at`` is what
# opens the tournament, and nobody should have to click for that.
AUTO_TRANSITION_SOURCE_STATUSES: frozenset[TournamentStatus] = frozenset(
    {
        TournamentStatus.ANNOUNCEMENT,
        TournamentStatus.REGISTRATION,
        TournamentStatus.DRAFT,
        TournamentStatus.CHECK_IN,
    }
)


class PhaseScheduleEntry(Protocol):
    """Structural view of a ``tournament_phase_schedule`` row."""

    status: TournamentStatus
    starts_at: datetime
    ends_at: datetime | None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
    return status in FINISHED_STATUSES


def next_due_status(
    current: TournamentStatus,
    schedule: Iterable[PhaseScheduleEntry],
    now: datetime,
) -> TournamentStatus | None:
    """Latest scheduled phase that is due and strictly ahead of ``current``.

    Returns the single target the automation should transition to directly
    (phase skips are legal in the transition matrix), or ``None`` when nothing
    is due. Never returns a backward or same-phase target, so the automation
    is forward-only by construction.
    """
    now = _as_utc(now)
    current_order = PHASE_ORDER[current]
    due = [
        entry.status
        for entry in schedule
        if entry.status in SCHEDULABLE_STATUSES
        and PHASE_ORDER[entry.status] > current_order
        and _as_utc(entry.starts_at) <= now
    ]
    if not due:
        return None
    return max(due, key=lambda status: PHASE_ORDER[status])


def is_within_phase_window(
    status: TournamentStatus,
    schedule: Iterable[PhaseScheduleEntry],
    now: datetime,
) -> bool:
    """Whether ``now`` falls inside ``status``'s action window.

    The window is the phase's schedule row ``[starts_at, ends_at]``; a missing
    row or ``ends_at IS NULL`` means the window spans the whole phase. This
    does NOT check that the tournament currently *is* in ``status`` — callers
    combine it with a status equality check.
    """
    now = _as_utc(now)
    entry = next((e for e in schedule if e.status == status), None)
    if entry is None:
        return True
    if _as_utc(entry.starts_at) > now:
        return False
    return entry.ends_at is None or now <= _as_utc(entry.ends_at)
