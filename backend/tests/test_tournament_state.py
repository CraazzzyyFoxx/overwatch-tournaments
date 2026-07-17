from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from shared.core.enums import TournamentStatus  # noqa: E402
from shared.core.tournament_state import (  # noqa: E402
    can_transition,
    is_within_phase_window,
    next_due_status,
)

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _row(status: TournamentStatus, starts_in: timedelta, ends_in: timedelta | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        starts_at=NOW + starts_in,
        ends_at=NOW + ends_in if ends_in is not None else None,
    )


# ─── next_due_status ─────────────────────────────────────────────────────────


def test_next_due_status_picks_latest_due_phase_skipping_intermediates() -> None:
    # DRAFT and LIVE are both overdue -> jump straight to LIVE (skip DRAFT).
    schedule = [
        _row(TournamentStatus.DRAFT, timedelta(hours=-2)),
        _row(TournamentStatus.LIVE, timedelta(hours=-1)),
    ]
    assert next_due_status(TournamentStatus.REGISTRATION, schedule, NOW) == TournamentStatus.LIVE


def test_next_due_status_ignores_phases_not_yet_due() -> None:
    schedule = [
        _row(TournamentStatus.CHECK_IN, timedelta(minutes=-5)),
        _row(TournamentStatus.LIVE, timedelta(hours=1)),
    ]
    assert next_due_status(TournamentStatus.REGISTRATION, schedule, NOW) == TournamentStatus.CHECK_IN


def test_next_due_status_ignores_non_schedulable_rows() -> None:
    # PLAYOFFS/COMPLETED are manual phases; a (bogus) due row never drives automation.
    schedule = [
        _row(TournamentStatus.PLAYOFFS, timedelta(hours=-1)),
        _row(TournamentStatus.COMPLETED, timedelta(hours=-1)),
    ]
    assert next_due_status(TournamentStatus.LIVE, schedule, NOW) is None


def test_next_due_status_returns_none_when_nothing_due() -> None:
    schedule = [_row(TournamentStatus.CHECK_IN, timedelta(minutes=10))]
    assert next_due_status(TournamentStatus.REGISTRATION, schedule, NOW) is None
    assert next_due_status(TournamentStatus.REGISTRATION, [], NOW) is None


def test_next_due_status_never_goes_backward_or_sideways() -> None:
    # Only backward (REGISTRATION) and same-phase (CHECK_IN) rows are due.
    schedule = [
        _row(TournamentStatus.REGISTRATION, timedelta(hours=-3)),
        _row(TournamentStatus.CHECK_IN, timedelta(hours=-1)),
    ]
    assert next_due_status(TournamentStatus.CHECK_IN, schedule, NOW) is None


def test_next_due_status_handles_naive_datetimes_as_utc() -> None:
    schedule = [
        SimpleNamespace(
            status=TournamentStatus.LIVE,
            starts_at=NOW.replace(tzinfo=None) - timedelta(minutes=1),
            ends_at=None,
        )
    ]
    assert next_due_status(TournamentStatus.CHECK_IN, schedule, NOW) == TournamentStatus.LIVE


# ─── is_within_phase_window ──────────────────────────────────────────────────


def test_window_defaults_to_whole_phase_without_a_row() -> None:
    assert is_within_phase_window(TournamentStatus.CHECK_IN, [], NOW) is True
    # A row for a *different* phase does not narrow this phase's window.
    other = [_row(TournamentStatus.REGISTRATION, timedelta(hours=1))]
    assert is_within_phase_window(TournamentStatus.CHECK_IN, other, NOW) is True


def test_window_closed_before_starts_at() -> None:
    schedule = [_row(TournamentStatus.CHECK_IN, timedelta(minutes=5))]
    assert is_within_phase_window(TournamentStatus.CHECK_IN, schedule, NOW) is False


def test_window_closed_after_ends_at() -> None:
    schedule = [_row(TournamentStatus.CHECK_IN, timedelta(hours=-2), ends_in=timedelta(hours=-1))]
    assert is_within_phase_window(TournamentStatus.CHECK_IN, schedule, NOW) is False


def test_window_open_between_starts_and_ends() -> None:
    schedule = [_row(TournamentStatus.CHECK_IN, timedelta(hours=-1), ends_in=timedelta(hours=1))]
    assert is_within_phase_window(TournamentStatus.CHECK_IN, schedule, NOW) is True


def test_window_with_null_ends_at_spans_rest_of_phase() -> None:
    schedule = [_row(TournamentStatus.CHECK_IN, timedelta(hours=-1))]
    assert is_within_phase_window(TournamentStatus.CHECK_IN, schedule, NOW) is True


# ─── can_transition ──────────────────────────────────────────────────────────


def test_forward_transitions_allow_phase_skips() -> None:
    assert can_transition(TournamentStatus.REGISTRATION, TournamentStatus.DRAFT)
    assert can_transition(TournamentStatus.REGISTRATION, TournamentStatus.CHECK_IN)
    assert can_transition(TournamentStatus.REGISTRATION, TournamentStatus.LIVE)
    assert can_transition(TournamentStatus.DRAFT, TournamentStatus.LIVE)
    assert can_transition(TournamentStatus.LIVE, TournamentStatus.PLAYOFFS)
    assert can_transition(TournamentStatus.LIVE, TournamentStatus.COMPLETED)


def test_one_phase_back_rollbacks_are_legal() -> None:
    assert can_transition(TournamentStatus.DRAFT, TournamentStatus.REGISTRATION)
    assert can_transition(TournamentStatus.CHECK_IN, TournamentStatus.DRAFT)
    assert can_transition(TournamentStatus.CHECK_IN, TournamentStatus.REGISTRATION)
    assert can_transition(TournamentStatus.LIVE, TournamentStatus.CHECK_IN)
    assert can_transition(TournamentStatus.COMPLETED, TournamentStatus.ARCHIVED)
    assert can_transition(TournamentStatus.ARCHIVED, TournamentStatus.COMPLETED)


def test_illegal_transitions_rejected() -> None:
    assert not can_transition(TournamentStatus.REGISTRATION, TournamentStatus.PLAYOFFS)
    assert not can_transition(TournamentStatus.PLAYOFFS, TournamentStatus.LIVE)
    assert not can_transition(TournamentStatus.REGISTRATION, TournamentStatus.COMPLETED)
    assert not can_transition(TournamentStatus.PLAYOFFS, TournamentStatus.REGISTRATION)
    assert not can_transition(TournamentStatus.COMPLETED, TournamentStatus.LIVE)
