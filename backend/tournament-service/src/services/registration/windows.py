"""Status/schedule gating for registration-surface actions.

Tournament status is the single source of truth for what is currently
possible; ``tournament_phase_schedule`` rows only narrow the action window
inside a phase (a missing row or ``ends_at IS NULL`` spans the whole phase).
"""

from __future__ import annotations

from datetime import UTC, datetime

from shared.core import enums, tournament_state
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
    form: models.BalancerRegistrationForm,
    *,
    now: datetime | None = None,
) -> bool:
    """Whether self-service registration is currently open.

    ``form.is_open`` is the admin kill switch; COMPLETED/ARCHIVED tournaments
    are always closed. Otherwise registration is open while the tournament is
    in REGISTRATION and inside the REGISTRATION row's window, or at any
    pre-terminal phase when ``allow_late_registration`` is set.
    """
    if not form.is_open:
        return False
    if tournament_state.is_finished_for_status(tournament.status):
        return False
    if tournament.status == enums.TournamentStatus.REGISTRATION and tournament_state.is_within_phase_window(
        enums.TournamentStatus.REGISTRATION,
        tournament.phase_schedule,
        now or datetime.now(UTC),
    ):
        return True
    return tournament.allow_late_registration
