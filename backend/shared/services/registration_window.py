"""Whether self-service registration is open — the single source of truth.

Registration openness used to be a conjunction of three knobs across two owners::

    form.is_open                                   # BalancerRegistrationForm
    AND not is_finished_for_status(status)
    AND ( (status == REGISTRATION AND is_within_phase_window(REGISTRATION, ...))
          OR tournament.allow_late_registration )  # Tournament

Two of those three are gone. ``form.is_open`` was a second open/closed switch
standing beside the schedule, and the tournament's own *phase* no longer
participates at all: a window reaching past the LIVE start keeps registration
open by itself, so openness never has to consult ``status`` except as a floor.

What remains is the ``REGISTRATION`` row of ``tournament_phase_schedule`` plus one
override: ``Tournament.allow_late_registration``, which lifts ``ends_at`` and
nothing else.

Three deliberate properties
---------------------------
**A missing row means CLOSED.** This inverts
``tournament_state.is_within_phase_window``, whose documented contract is that a
missing row "spans the whole phase". That contract is load-bearing for
``is_check_in_window_active``, so it is NOT changed — the inversion lives here,
for registration only. Without the inversion the default would flip from closed
(``is_open`` defaulted to ``false``) to open, and a freshly created tournament
would accept registrations before its form was configured.

**Terminal statuses are a floor, not a knob.** COMPLETED/ARCHIVED is always
closed regardless of the window, so a mis-set ``ends_at`` can never reopen an
archived tournament.

**The late-registration override lifts ``ends_at`` ONLY.** It is deliberately the
narrowest knob that still does the job — admit latecomers without editing away
the intended closing time, which is the one thing an ``ends_at`` edit cannot do
(it destroys the very date the organizer wants to keep on the page). It therefore
does NOT open a tournament with no REGISTRATION row (that would flip a fresh
tournament's default to open and defeat the inversion above), does NOT open one
whose window has not started yet (*late* means after the end, never before the
start), and cannot beat the terminal floor. ``allow_late`` is a REQUIRED argument
rather than a defaulted one: a caller holding only ``(status, schedule)`` cannot
know the flag, and defaulting it to ``False`` would silently answer "closed" for
exactly the tournaments this override exists to keep open.

Both a Python predicate and a SQL clause are provided because openness is read
both per-tournament and inside aggregate queries in three different services
(dashboard readiness, dashboard counts, subscription-collection targeting,
subscription-config preview).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import sqlalchemy as sa

from shared.core.enums import TournamentStatus
from shared.core.tournament_state import PhaseScheduleEntry, is_finished_for_status
from shared.models.tournament.tournament import Tournament, TournamentPhaseSchedule

__all__ = (
    "is_registration_late",
    "is_registration_window_open",
    "registration_late_clause",
    "registration_open_clause",
)


def is_registration_window_open(
    status: TournamentStatus,
    schedule: Iterable[PhaseScheduleEntry],
    now: datetime | None = None,
    *,
    allow_late: bool,
) -> bool:
    """``True`` while ``now`` is inside the REGISTRATION row's window.

    Deliberately takes the status, schedule and flag rather than a ``Tournament``
    so it can be unit-tested without a mapped instance, and so callers holding
    only a projection can use it.
    """
    if is_finished_for_status(status):
        return False

    entry = next((e for e in schedule if e.status == TournamentStatus.REGISTRATION), None)
    if entry is None:
        # The inversion: no schedule row => registration was never opened.
        return False

    moment = now or datetime.now(UTC)
    starts_at = _as_utc(entry.starts_at)
    if starts_at > moment:
        return False
    if entry.ends_at is None or allow_late:
        return True
    return moment <= _as_utc(entry.ends_at)


def is_registration_late(
    status: TournamentStatus,
    schedule: Iterable[PhaseScheduleEntry],
    now: datetime | None = None,
) -> bool:
    """``True`` when a sign-up right now is only possible past the closing time.

    Deliberately NOT ``not is_registration_window_open(...)``: closed is closed,
    late is open-BY-OVERRIDE. A window with no ``ends_at`` is therefore never
    late (nothing was announced to be past), one that has not started yet is
    never late (*late* means after the end), and neither is a tournament with no
    REGISTRATION row at all.

    ``allow_late`` is not a parameter: whether the override is armed decides
    whether the sign-up happens, not whether it is late. Callers that only admit
    open tournaments have already consulted
    :func:`is_registration_window_open`.
    """
    if is_finished_for_status(status):
        return False

    entry = next((e for e in schedule if e.status == TournamentStatus.REGISTRATION), None)
    if entry is None or entry.ends_at is None:
        return False

    moment = now or datetime.now(UTC)
    return _as_utc(entry.starts_at) <= moment and moment > _as_utc(entry.ends_at)


def registration_open_clause(now: datetime | None = None) -> sa.ColumnElement[bool]:
    """SQL form of :func:`is_registration_window_open`, correlated on ``Tournament``.

    Usable anywhere ``tournament.tournament`` is already in the FROM list, e.g.::

        sa.select(sa.func.count(Tournament.id)).where(registration_open_clause())

    Mirrors the Python predicate exactly, including "missing row => closed"
    (``EXISTS`` fails when there is no row), the terminal-status floor, and the
    ``allow_late_registration`` override of ``ends_at``. The override is a
    correlated reference to the outer ``Tournament`` — it sits INSIDE the
    ``EXISTS`` next to the ``ends_at`` test on purpose, because lifting it to the
    top level would also bypass "missing row => closed" and ``starts_at``.
    """
    moment = now or datetime.now(UTC)
    window = (
        sa.select(sa.literal(1))
        .select_from(TournamentPhaseSchedule)
        .where(
            TournamentPhaseSchedule.tournament_id == Tournament.id,
            TournamentPhaseSchedule.status == TournamentStatus.REGISTRATION,
            TournamentPhaseSchedule.starts_at <= moment,
            sa.or_(
                TournamentPhaseSchedule.ends_at.is_(None),
                TournamentPhaseSchedule.ends_at >= moment,
                Tournament.allow_late_registration.is_(True),
            ),
        )
        .exists()
    )
    return sa.and_(
        Tournament.status.notin_([TournamentStatus.COMPLETED, TournamentStatus.ARCHIVED]),
        window,
    )


def registration_late_clause(now: datetime | None = None) -> sa.ColumnElement[bool]:
    """SQL form of :func:`is_registration_late`, correlated on ``Tournament``.

    Exists for the same reason ``registration_open_clause`` does: the answer is
    read both per-tournament and inside a query, and one of the two drifting
    would mean a registrant told they are on time landing in the reserve.
    """
    moment = now or datetime.now(UTC)
    past_end = (
        sa.select(sa.literal(1))
        .select_from(TournamentPhaseSchedule)
        .where(
            TournamentPhaseSchedule.tournament_id == Tournament.id,
            TournamentPhaseSchedule.status == TournamentStatus.REGISTRATION,
            TournamentPhaseSchedule.starts_at <= moment,
            TournamentPhaseSchedule.ends_at.is_not(None),
            TournamentPhaseSchedule.ends_at < moment,
        )
        .exists()
    )
    return sa.and_(
        Tournament.status.notin_([TournamentStatus.COMPLETED, TournamentStatus.ARCHIVED]),
        past_end,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
