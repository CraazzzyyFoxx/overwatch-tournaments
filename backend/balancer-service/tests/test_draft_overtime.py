"""Overtime on a pick, and the admin's "add seconds" button.

Two mechanisms, one column each:

* ``draft_session.overtime_seconds`` turns an expired main clock into a grace
  period instead of an immediate autopick, and ``draft_pick.overtime_started_at``
  records that this pick already consumed it -- so the grace period is granted
  exactly once, and survives a pause/resume that only moves the deadline.
* ``lifecycle.extend_pick`` adds time to whichever representation of the clock
  is authoritative: the absolute deadline while LIVE, the frozen remainder while
  PAUSED.

No database: the clock reads through two repositories and publishes through one
module-level function, so a fake for each is the whole harness.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.core.enums import (  # noqa: E402
    DraftFormat,
    DraftPickStatus,
    DraftStatus,
)
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.models.balancer.draft import DraftPick, DraftSession  # noqa: E402
from src.domain.draft.entities import DraftResult  # noqa: E402
from src.services.draft import clock as draft_clock  # noqa: E402
from src.services.draft import realtime as draft_rt  # noqa: E402
from src.services.draft.lifecycle import lifecycle_service  # noqa: E402
from src.services.draft.selection import selection_service  # noqa: E402


class _FakeSession:
    """Just enough AsyncSession for the clock/lifecycle write paths."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakeRepo:
    def __init__(self, row: Any) -> None:
        self.row = row

    async def get(self, _session: Any, row_id: int) -> Any:
        return self.row if self.row is not None and self.row.id == row_id else None


def _draft(**overrides: Any) -> DraftSession:
    fields: dict[str, Any] = {
        "id": 1,
        "tournament_id": 2,
        "workspace_id": 3,
        "status": DraftStatus.LIVE.value,
        "format": DraftFormat.SNAKE.value,
        "rounds": 4,
        "pick_time_seconds": 45,
        "overtime_seconds": 0,
        "current_pick_id": 10,
        "version": 1,
    }
    fields.update(overrides)
    return DraftSession(**fields)


def _pick(**overrides: Any) -> DraftPick:
    fields: dict[str, Any] = {
        "id": 10,
        "session_id": 1,
        "overall_no": 1,
        "round_no": 1,
        "pick_in_round": 1,
        "draft_team_id": 7,
        "status": DraftPickStatus.ON_CLOCK.value,
        "clock_started_at": datetime.now(UTC) - timedelta(seconds=45),
        "clock_expires_at": datetime.now(UTC) - timedelta(seconds=1),
        "clock_remaining_ms": None,
        "overtime_started_at": None,
        "version": 4,
    }
    fields.update(overrides)
    return DraftPick(**fields)


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []

    async def _publish(_session: Any, *, draft_session: Any, event_type: str, payload: dict, **_kw: Any) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(draft_rt, "publish_draft_event", _publish)
    return events


def _fire(monkeypatch: pytest.MonkeyPatch, draft: DraftSession, pick: DraftPick) -> tuple[bool, list[str]]:
    """Run ``fire_autopick_if_expired`` against fake repos. Returns (fired, autopicks)."""
    autopicks: list[str] = []
    service = draft_clock.DraftClockService(
        sessions_repo=_FakeRepo(draft),  # type: ignore[arg-type]
        picks_repo=_FakeRepo(pick),  # type: ignore[arg-type]
        selection=selection_service,
    )

    async def _autopick(_session: Any, _draft: Any, target: DraftPick, **_kw: Any) -> DraftResult:
        autopicks.append("autopicked")
        target.status = DraftPickStatus.AUTOPICKED.value
        return DraftResult(pick=target, next_pick=None, completed=True, blocked_reason=None)

    monkeypatch.setattr(selection_service, "autopick", _autopick)
    fired = asyncio.run(service.fire_autopick_if_expired(_FakeSession, 1))  # type: ignore[arg-type]
    return fired, autopicks


def test_expired_main_clock_enters_overtime_instead_of_autopicking(
    monkeypatch: pytest.MonkeyPatch, published: list[tuple[str, dict]]
) -> None:
    draft = _draft(overtime_seconds=30)
    pick = _pick(version=4)
    before = datetime.now(UTC)

    fired, autopicks = _fire(monkeypatch, draft, pick)

    assert fired is True
    assert autopicks == []
    assert pick.overtime_started_at is not None
    assert pick.version == 5
    # The deadline is the overtime one, so the loop re-sleeps instead of firing.
    assert before + timedelta(seconds=29) < pick.clock_expires_at <= datetime.now(UTC) + timedelta(seconds=30)
    assert [event for event, _ in published] == ["draft.overtime_started"]
    payload = published[0][1]
    assert payload["session_id"] == 1
    assert payload["pick_id"] == 10
    assert payload["draft_team_id"] == 7
    assert payload["pick_version"] == 5
    assert payload["overtime_started_at"] == pick.overtime_started_at.isoformat()
    assert payload["clock_expires_at"] == pick.clock_expires_at.isoformat()


def test_expiry_during_overtime_autopicks(monkeypatch: pytest.MonkeyPatch, published: list[tuple[str, dict]]) -> None:
    # The grace period is granted once per pick: the second expiry is the end.
    draft = _draft(overtime_seconds=30)
    pick = _pick(overtime_started_at=datetime.now(UTC) - timedelta(seconds=31))

    fired, autopicks = _fire(monkeypatch, draft, pick)

    assert fired is True
    assert autopicks == ["autopicked"]
    assert "draft.overtime_started" not in [event for event, _ in published]


def test_no_overtime_configured_autopicks_immediately(
    monkeypatch: pytest.MonkeyPatch, published: list[tuple[str, dict]]
) -> None:
    draft = _draft(overtime_seconds=0)
    pick = _pick()

    fired, autopicks = _fire(monkeypatch, draft, pick)

    assert fired is True
    assert autopicks == ["autopicked"]
    assert pick.overtime_started_at is None


def test_a_pick_that_is_not_due_yet_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, published: list[tuple[str, dict]]
) -> None:
    draft = _draft(overtime_seconds=30)
    pick = _pick(clock_expires_at=datetime.now(UTC) + timedelta(seconds=20))

    fired, autopicks = _fire(monkeypatch, draft, pick)

    assert (fired, autopicks, published) == (False, [], [])
    assert pick.overtime_started_at is None


def _extend(draft: DraftSession, pick: DraftPick, *, seconds: int, expected_version: int) -> DraftPick:
    return asyncio.run(
        lifecycle_service.extend_pick(
            _FakeSession(),  # type: ignore[arg-type]
            draft,
            pick,
            seconds=seconds,
            expected_version=expected_version,
        )
    )


def test_extend_pushes_the_live_deadline_and_bumps_the_version() -> None:
    draft = _draft()
    deadline = datetime.now(UTC) + timedelta(seconds=10)
    pick = _pick(clock_expires_at=deadline, version=4)

    _extend(draft, pick, seconds=30, expected_version=4)

    assert pick.clock_expires_at == deadline + timedelta(seconds=30)
    assert pick.clock_remaining_ms is None
    assert pick.version == 5


def test_extend_while_paused_adds_to_the_frozen_remainder() -> None:
    draft = _draft(status=DraftStatus.PAUSED.value)
    pick = _pick(clock_expires_at=None, clock_remaining_ms=12_000, version=4)

    _extend(draft, pick, seconds=20, expected_version=4)

    assert pick.clock_remaining_ms == 32_000
    assert pick.clock_expires_at is None
    assert pick.version == 5


def test_extend_of_a_paused_pick_with_no_recorded_remainder_starts_from_a_full_timer() -> None:
    # ``_advance`` parks a re-seated pick unarmed; resume gives it a full timer,
    # so an extension before that resume has to start from the same number.
    draft = _draft(status=DraftStatus.PAUSED.value, pick_time_seconds=45)
    pick = _pick(clock_expires_at=None, clock_remaining_ms=None, version=4)

    _extend(draft, pick, seconds=15, expected_version=4)

    assert pick.clock_remaining_ms == 60_000


def test_extend_rejects_a_stale_version() -> None:
    draft = _draft()
    pick = _pick(version=5)

    with pytest.raises(ApiHTTPException) as exc_info:
        _extend(draft, pick, seconds=30, expected_version=4)

    assert exc_info.value.detail[0]["code"] == "pick_already_resolved"
    assert exc_info.value.status_code == 409
    assert pick.version == 5


def test_extend_rejects_a_pick_that_is_not_the_current_one() -> None:
    draft = _draft(current_pick_id=99)
    pick = _pick()

    with pytest.raises(ApiHTTPException) as exc_info:
        _extend(draft, pick, seconds=30, expected_version=4)

    assert exc_info.value.detail[0]["code"] == "pick_not_on_clock"


def test_extend_rejects_a_draft_that_is_neither_live_nor_paused() -> None:
    draft = _draft(status=DraftStatus.COMPLETED.value)
    pick = _pick()

    with pytest.raises(ApiHTTPException) as exc_info:
        _extend(draft, pick, seconds=30, expected_version=4)

    assert exc_info.value.detail[0]["code"] == "draft_not_live"


def test_advance_clears_the_overtime_phase_of_the_pick_it_arms() -> None:
    draft = _draft()
    next_pick = _pick(id=11, overall_no=2, overtime_started_at=datetime.now(UTC), clock_remaining_ms=5_000)

    class _Picks:
        async def next_upcoming_locked(self, _session: Any, _session_id: int) -> DraftPick:
            return next_pick

    service = selection_service
    original_picks = service.picks_repo
    service.picks_repo = _Picks()  # type: ignore[assignment]
    try:
        armed = asyncio.run(service._advance(_FakeSession(), draft))  # type: ignore[arg-type]
    finally:
        service.picks_repo = original_picks

    assert armed is next_pick
    assert next_pick.overtime_started_at is None
    assert next_pick.clock_remaining_ms is None
    assert next_pick.status == DraftPickStatus.ON_CLOCK.value
