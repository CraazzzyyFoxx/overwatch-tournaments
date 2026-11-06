from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from shared.core.enums import TournamentStatus  # noqa: E402
from shared.core.tournament_state import FINISHED_STATUSES, as_utc, is_finished_for_status  # noqa: E402


def test_finished_statuses() -> None:
    assert frozenset({TournamentStatus.COMPLETED, TournamentStatus.ARCHIVED}) == FINISHED_STATUSES
    assert [is_finished_for_status(s) for s in TournamentStatus] == [False, False, True, True]


def test_tournament_status_has_four_values() -> None:
    assert [s.value for s in TournamentStatus] == ["announcement", "live", "completed", "archived"]


def test_as_utc_reads_naive_as_utc_and_converts_aware() -> None:
    naive = datetime(2026, 7, 17, 12, 0)
    assert as_utc(naive) == datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    plus_two = datetime(2026, 7, 17, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert as_utc(plus_two) == datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
