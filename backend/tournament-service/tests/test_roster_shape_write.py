"""Write path for the tournament-level roster shape (Phase 1, Task 6).

Four things are pinned here:

* the schema **normalizes on the way in**, so the JSONB column never stores a
  zero count -- ``RosterShape.has_role_slots`` would become ambiguous if it did;
* every ``RosterShapeError.code`` surfaces as a Pydantic validation error (a 422
  at the wire boundary, not a 500) with the code inside the message, because the
  frontend localizes off the code and not off the prose;
* the draft guard fires only on an **actual** change. The admin Settings tab
  submits every field it renders, so re-sending the current shape mid-draft must
  not block an unrelated rename;
* the roster-shape cache is dropped **after** the commit. Invalidating first
  leaves a window where a concurrent read repopulates the cache from the
  pre-commit row, and that stale entry then survives for the full hour TTL.

DB-free: ``update_tournament`` runs against a fake session.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

from shared.core.errors import BaseAPIException  # noqa: E402
from shared.services.draft_guards import assert_no_active_draft_session  # noqa: E402
from src import schemas  # noqa: E402
from src.services.admin import tournament as admin_tournament  # noqa: E402

# The exact detail the guard produced before it took a ``change`` argument. Its
# two existing callers pass no ``change``, so this string must stay byte-identical.
_LEGACY_DETAIL = (
    "Cannot change team formation while a draft session is active (status: live). Cancel or complete the draft first."
)

_STORED_ROLE_SHAPE = {"tank": 1, "dps": 2, "support": 2}

_INVALID_SLOTS = [
    ({"healer": 2}, "roster_slots_unknown_code"),
    ({"flex": 99}, "roster_slots_out_of_range"),
    ({"flex": 1}, "roster_slots_out_of_range"),
    ({}, "roster_slots_empty"),
    ({"tank": -1}, "roster_slots_invalid_count"),
]


# ─── Schema validation ───────────────────────────────────────────────────────


def test_update_accepts_a_flex_only_shape() -> None:
    assert schemas.TournamentUpdate(roster_slots_json={"flex": 6}).roster_slots_json == {"flex": 6}


def test_update_normalizes_zero_counts_away() -> None:
    # A role-less roster arrives from the form as "every role zero, flex six".
    # Storing the zeros would make ``has_role_slots`` answer on key presence
    # instead of on real slots.
    model = schemas.TournamentUpdate(roster_slots_json={"tank": 0, "dps": 0, "support": 0, "flex": 6})
    assert model.roster_slots_json == {"flex": 6}


def test_update_normalizes_key_order() -> None:
    model = schemas.TournamentUpdate(roster_slots_json={"support": 2, "tank": 1, "dps": 2})
    assert list(model.roster_slots_json) == ["tank", "dps", "support"]


@pytest.mark.parametrize(("raw", "code"), _INVALID_SLOTS)
def test_update_rejects_invalid_slots_with_the_machine_readable_code(raw, code) -> None:
    with pytest.raises(ValidationError) as exc_info:
        schemas.TournamentUpdate(roster_slots_json=raw)
    assert code in str(exc_info.value)


@pytest.mark.parametrize(("raw", "code"), _INVALID_SLOTS)
def test_create_rejects_invalid_slots_with_the_machine_readable_code(raw, code) -> None:
    with pytest.raises(ValidationError) as exc_info:
        schemas.TournamentCreate(
            workspace_id=1,
            name="T",
            start_date="2026-01-01",
            end_date="2026-01-02",
            roster_slots_json=raw,
        )
    assert code in str(exc_info.value)


def test_create_defaults_to_inheriting() -> None:
    created = schemas.TournamentCreate(workspace_id=1, name="T", start_date="2026-01-01", end_date="2026-01-02")
    assert created.roster_slots_json is None


def test_explicit_none_clears_the_override_and_is_distinct_from_omission() -> None:
    # None means "drop the override, inherit the workspace default"; an absent
    # field means "don't touch it". ``exclude_unset`` is what keeps them apart.
    cleared = schemas.TournamentUpdate(roster_slots_json=None)
    assert cleared.model_dump(exclude_unset=True) == {"roster_slots_json": None}
    assert "roster_slots_json" not in schemas.TournamentUpdate(name="x").model_dump(exclude_unset=True)


# ─── Guard ───────────────────────────────────────────────────────────────────


class _FakeResult:
    """Mirrors the two shapes the code under test reads a result through:
    the guard's ``scalar_one_or_none`` and the repository's
    ``.unique().scalars().first()``."""

    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def unique(self):
        return self

    def scalars(self):
        return self

    def first(self):
        return self._value

    def all(self):
        return [] if self._value is None else [self._value]


class _FakeSession:
    """Just enough of AsyncSession to drive ``update_tournament`` without a DB.

    ``scalar`` mirrors the guard's ``status NOT IN (cancelled, completed)``
    filter: a terminal status is invisible to the query, exactly as in Postgres.
    """

    _TERMINAL = {"cancelled", "completed"}

    def __init__(self, tournament=None, draft_status=None):
        self._tournament = tournament
        self._draft_status = draft_status
        self.scalar_stmts: list = []
        self.committed = False

    async def execute(self, stmt):
        return _FakeResult(self._tournament)

    async def scalar(self, stmt):
        self.scalar_stmts.append(stmt)
        if self._draft_status in self._TERMINAL:
            return None
        return self._draft_status

    async def commit(self):
        self.committed = True


def test_guard_keeps_the_legacy_message_when_no_change_is_named() -> None:
    session = _FakeSession(draft_status="live")
    with pytest.raises(BaseAPIException) as exc_info:
        asyncio.run(assert_no_active_draft_session(session, 1))
    assert exc_info.value.detail == _LEGACY_DETAIL


def test_guard_names_the_roster_shape_and_the_blocking_status() -> None:
    session = _FakeSession(draft_status="picking")
    with pytest.raises(BaseAPIException) as exc_info:
        asyncio.run(assert_no_active_draft_session(session, 1, change="roster shape"))
    assert "roster shape" in exc_info.value.detail
    assert "picking" in exc_info.value.detail
    assert exc_info.value.status_code == 400


def test_guard_query_excludes_terminal_statuses() -> None:
    session = _FakeSession(draft_status=None)
    asyncio.run(assert_no_active_draft_session(session, 1, change="roster shape"))
    compiled = str(session.scalar_stmts[0].compile(compile_kwargs={"literal_binds": True}))
    assert "cancelled" in compiled and "completed" in compiled


# ─── update_tournament: guard + cache invalidation ───────────────────────────


class _InvalidationSpy:
    """Records every invalidation call together with the commit state at that moment."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session
        self.calls: list[tuple[dict, bool]] = []

    async def __call__(self, **kwargs) -> None:
        self.calls.append((kwargs, self._session.committed))


def _run_update(
    monkeypatch,
    *,
    draft_status: str | None,
    update: schemas.TournamentUpdate,
    stored_slots: dict[str, int] | None = None,
):
    """Return (error, session, tournament, invalidation spy)."""
    tournament = SimpleNamespace(
        id=1,
        workspace_id=1,
        team_formation="draft",
        division_grid_version_id=None,
        roster_slots_json=stored_slots,
    )
    session = _FakeSession(tournament=tournament, draft_status=draft_status)
    spy = _InvalidationSpy(session)

    async def _noop(*args, **kwargs):
        return tournament

    monkeypatch.setattr(admin_tournament, "publish_tournament_invalidation", _noop)
    monkeypatch.setattr(admin_tournament.tournament_service, "get_tournament", _noop)
    monkeypatch.setattr(admin_tournament, "invalidate_roster_shape_cache", spy)

    error: BaseAPIException | None = None
    try:
        asyncio.run(admin_tournament.tournament_service.update_tournament(session, tournament.id, update))
    except BaseAPIException as exc:
        error = exc
    return error, session, tournament, spy


def test_roster_shape_change_blocked_by_unfinished_draft(monkeypatch) -> None:
    error, session, tournament, spy = _run_update(
        monkeypatch,
        draft_status="live",
        update=schemas.TournamentUpdate(roster_slots_json={"flex": 6}),
        stored_slots=dict(_STORED_ROLE_SHAPE),
    )
    assert error is not None and error.status_code == 400
    assert "roster shape" in error.detail
    assert session.committed is False
    assert tournament.roster_slots_json == _STORED_ROLE_SHAPE  # unchanged
    assert spy.calls == []


@pytest.mark.parametrize("terminal", ["cancelled", "completed"])
def test_roster_shape_change_allowed_when_draft_is_terminal(monkeypatch, terminal) -> None:
    error, session, tournament, spy = _run_update(
        monkeypatch,
        draft_status=terminal,
        update=schemas.TournamentUpdate(roster_slots_json={"flex": 6}),
        stored_slots=dict(_STORED_ROLE_SHAPE),
    )
    assert error is None
    assert tournament.roster_slots_json == {"flex": 6}
    assert session.committed is True


def test_unchanged_roster_shape_does_not_trip_the_guard(monkeypatch) -> None:
    # THE test of this task: the Settings tab submits every field, so an admin
    # renaming a tournament mid-draft resends the current shape untouched.
    error, session, tournament, spy = _run_update(
        monkeypatch,
        draft_status="live",
        update=schemas.TournamentUpdate(roster_slots_json=dict(_STORED_ROLE_SHAPE), name="renamed"),
        stored_slots=dict(_STORED_ROLE_SHAPE),
    )
    assert error is None
    assert session.scalar_stmts == []  # guard query never issued
    assert session.committed is True
    assert tournament.name == "renamed"
    assert spy.calls == []


def test_reordered_and_padded_resend_still_counts_as_unchanged(monkeypatch) -> None:
    # The form emits its own key order and explicit zeros; normalization at the
    # schema edge is what makes the equality check meaningful.
    error, session, _, spy = _run_update(
        monkeypatch,
        draft_status="live",
        update=schemas.TournamentUpdate(roster_slots_json={"support": 2, "dps": 2, "tank": 1, "flex": 0}),
        stored_slots=dict(_STORED_ROLE_SHAPE),
    )
    assert error is None
    assert session.scalar_stmts == []
    assert session.committed is True
    assert spy.calls == []


def test_other_fields_are_editable_mid_draft(monkeypatch) -> None:
    error, session, _, spy = _run_update(
        monkeypatch,
        draft_status="live",
        update=schemas.TournamentUpdate(name="renamed"),
        stored_slots=dict(_STORED_ROLE_SHAPE),
    )
    assert error is None
    assert session.scalar_stmts == []
    assert session.committed is True
    assert spy.calls == []


def test_successful_change_invalidates_the_cache_once_after_commit(monkeypatch) -> None:
    _, session, _, spy = _run_update(
        monkeypatch,
        draft_status=None,
        update=schemas.TournamentUpdate(roster_slots_json={"flex": 6}),
        stored_slots=dict(_STORED_ROLE_SHAPE),
    )
    assert session.committed is True
    assert spy.calls == [({"tournament_id": 1}, True)]


def test_clearing_the_override_invalidates_the_cache(monkeypatch) -> None:
    _, _, tournament, spy = _run_update(
        monkeypatch,
        draft_status=None,
        update=schemas.TournamentUpdate(roster_slots_json=None),
        stored_slots=dict(_STORED_ROLE_SHAPE),
    )
    assert tournament.roster_slots_json is None
    assert spy.calls == [({"tournament_id": 1}, True)]


def test_resending_the_same_shape_does_not_invalidate_the_cache(monkeypatch) -> None:
    # Mirrors ``should_invalidate_grid``: a no-op write must not drop a warm cache.
    _, session, _, spy = _run_update(
        monkeypatch,
        draft_status=None,
        update=schemas.TournamentUpdate(roster_slots_json=dict(_STORED_ROLE_SHAPE)),
        stored_slots=dict(_STORED_ROLE_SHAPE),
    )
    assert session.committed is True
    assert spy.calls == []
