"""Status/schedule gating for registration-surface actions.

Tournament status is the single source of truth for what is currently
possible; ``tournament_phase_schedule`` rows only narrow the action window
inside a phase (a missing row or ``ends_at IS NULL`` spans the whole phase).

Registration is the one exception: it is governed *solely* by its schedule row,
where a missing row means closed. See
:mod:`shared.services.registration_window` for why that inversion lives there
rather than in ``tournament_state.is_within_phase_window``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums, tournament_state
from shared.services.registration_window import (
    is_registration_late,
    is_registration_window_open,
    registration_late_clause,
    registration_open_clause,
)
from src import models


def is_check_in_window_active(
    tournament: models.Tournament,
    *,
    now: datetime | None = None,
) -> bool:
    """Check-in is possible iff the tournament is in CHECK_IN and ``now`` is
    inside the CHECK_IN schedule row's window (if one exists)."""
    if tournament.status != enums.TournamentStatus.CHECK_IN:
        return False
    return tournament_state.is_within_phase_window(
        enums.TournamentStatus.CHECK_IN,
        tournament.phase_schedule,
        now or datetime.now(UTC),
    )


def is_registration_open(
    tournament: models.Tournament,
    *,
    now: datetime | None = None,
) -> bool:
    """Whether self-service registration is currently open.

    The tournament's REGISTRATION schedule window plus one override: no row means
    closed, COMPLETED/ARCHIVED is always closed, and ``allow_late_registration``
    lifts the window's ``ends_at`` so latecomers can be admitted without editing
    away the intended closing time. The former
    ``BalancerRegistrationForm.is_open`` kill switch is gone, and the tournament's
    own phase no longer participates.

    ``form`` is no longer a parameter: keeping it would imply the form still has
    a say.
    """
    return is_registration_window_open(
        tournament.status,
        tournament.phase_schedule,
        now,
        allow_late=tournament.allow_late_registration,
    )


def is_late_registration(
    tournament: models.Tournament,
    *,
    now: datetime | None = None,
) -> bool:
    """Whether a sign-up right now is only possible past the announced closing time.

    Deliberately not ``not is_registration_open(...)``: closed is closed, late is
    open-BY-OVERRIDE (``allow_late_registration``). A window with no ``ends_at``
    is never late, and neither is one that has not started.

    A late sign-up is written as a RESERVE -- see
    ``service.submit_public_registration``.
    """
    return is_registration_late(tournament.status, tournament.phase_schedule, now)


class RegistrationWindowService:
    """The one session-taking window read; the three predicates above stay pure."""

    async def load_registration_open(self, session: AsyncSession, tournament_id: int) -> bool:
        """Openness for a tournament we hold only the id of.

        One scalar read of the *same* SQL clause the aggregate readers use, so the
        per-tournament and in-query answers cannot drift apart. Prefer
        :func:`is_registration_open` when a ``Tournament`` is already loaded.
        """
        return bool(
            await session.scalar(sa.select(registration_open_clause()).where(models.Tournament.id == tournament_id))
        )

    async def load_registration_state(
        self, session: AsyncSession, tournament_id: int
    ) -> tuple[bool, bool]:
        """``(is_open, is_late)`` in ONE round trip.

        The public form read needs both — openness to show the form at all, and
        lateness to tell the registrant *before* they submit that they are signing
        up into the reserve. Two scalars off one row rather than two calls, and
        both off the same clauses the write path evaluates in Python.
        """
        row = (
            await session.execute(
                sa.select(registration_open_clause(), registration_late_clause()).where(
                    models.Tournament.id == tournament_id
                )
            )
        ).first()
        return (bool(row[0]), bool(row[1])) if row is not None else (False, False)


windows_service = RegistrationWindowService()
