"""Workspace-level default roster shape: schema + write path (Phase 1, Task 6).

``default_roster_slots_json`` deliberately goes through the ordinary
``WorkspaceUpdate`` -> ``workspace_service.update`` path. Its neighbour
``default_division_grid_version_id`` does not -- ``update`` rejects that one with
a 400 because grid versions carry activation semantics and own an endpoint. A
roster shape has no activation: it is three to six integers an admin edits in
place, so a second write path would be pure ceremony. Both halves of that
asymmetry are pinned below so neither drifts by accident.

DB-free: the write path runs against a fake session.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from shared.core.errors import BaseAPIException
from src import schemas
from src.services.workspace import registry as workspace_registry
from src.services.workspace.service import workspaces as workspace_service

_STORED = {"tank": 1, "damage": 2, "support": 2}

_INVALID_SLOTS = [
    ({"healer": 2}, "roster_slots_unknown_code"),
    ({"flex": 99}, "roster_slots_out_of_range"),
    ({}, "roster_slots_empty"),
    ({"tank": -1}, "roster_slots_invalid_count"),
]


# ─── Schema ──────────────────────────────────────────────────────────────────


def test_read_exposes_the_raw_default() -> None:
    assert "default_roster_slots_json" in schemas.WorkspaceRead.model_fields


def test_update_accepts_a_flex_only_default() -> None:
    model = schemas.WorkspaceUpdate(default_roster_slots_json={"flex": 6})
    assert model.default_roster_slots_json == {"flex": 6}


def test_update_normalizes_zero_counts_away() -> None:
    model = schemas.WorkspaceUpdate(default_roster_slots_json={"tank": 0, "damage": 0, "support": 0, "flex": 6})
    assert model.default_roster_slots_json == {"flex": 6}


def test_create_accepts_and_normalizes_a_default() -> None:
    created = schemas.WorkspaceCreate(
        slug="ws", name="WS", default_roster_slots_json={"support": 2, "tank": 1, "damage": 2}
    )
    assert list(created.default_roster_slots_json) == ["tank", "damage", "support"]


def test_create_defaults_to_the_builtin_shape() -> None:
    assert schemas.WorkspaceCreate(slug="ws", name="WS").default_roster_slots_json is None


@pytest.mark.parametrize(("raw", "code"), _INVALID_SLOTS)
def test_update_rejects_invalid_slots_with_the_machine_readable_code(raw, code) -> None:
    with pytest.raises(ValidationError) as exc_info:
        schemas.WorkspaceUpdate(default_roster_slots_json=raw)
    assert code in str(exc_info.value)


@pytest.mark.parametrize(("raw", "code"), _INVALID_SLOTS)
def test_create_rejects_invalid_slots_with_the_machine_readable_code(raw, code) -> None:
    with pytest.raises(ValidationError) as exc_info:
        schemas.WorkspaceCreate(slug="ws", name="WS", default_roster_slots_json=raw)
    assert code in str(exc_info.value)


def test_explicit_none_clears_the_default_and_is_distinct_from_omission() -> None:
    cleared = schemas.WorkspaceUpdate(default_roster_slots_json=None)
    assert cleared.model_dump(exclude_unset=True) == {"default_roster_slots_json": None}
    assert schemas.WorkspaceUpdate(name="x").model_dump(exclude_unset=True) == {"name": "x"}


# ─── Write path ──────────────────────────────────────────────────────────────


class _FakeWorkspace:
    def __init__(self, slots=None) -> None:
        self.id = 7
        self.default_roster_slots_json = slots


class _FakeLockResult:
    def __init__(self, row) -> None:
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    """``lock_rows`` answers ``roster_shape_guards``' two shape-lock reads."""

    def __init__(self, *lock_rows) -> None:
        self.committed = False
        self._lock_rows = list(lock_rows)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def execute(self, _statement) -> _FakeLockResult:
        return _FakeLockResult(self._lock_rows.pop(0) if self._lock_rows else None)


class _InvalidationSpy:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session
        self.calls: list[tuple[dict, bool]] = []

    async def __call__(self, **kwargs) -> None:
        self.calls.append((kwargs, self._session.committed))


def test_service_update_accepts_the_roster_default() -> None:
    # The deliberate difference from ``default_division_grid_version_id``: this
    # field is edited in place, so it needs no activation endpoint.
    workspace = _FakeWorkspace(dict(_STORED))
    asyncio.run(workspace_service.update(_FakeSession(), workspace, {"default_roster_slots_json": {"flex": 6}}))
    assert workspace.default_roster_slots_json == {"flex": 6}


def test_service_update_still_rejects_the_division_grid_version() -> None:
    with pytest.raises(BaseAPIException) as exc_info:
        asyncio.run(workspace_service.update(_FakeSession(), _FakeWorkspace(), {"default_division_grid_version_id": 3}))
    assert exc_info.value.status_code == 400


def _run_registry_update(monkeypatch, payload: schemas.WorkspaceUpdate, *, stored=None, lock_rows=()):
    workspace = _FakeWorkspace(stored)
    session = _FakeSession(*lock_rows)
    spy = _InvalidationSpy(session)

    async def _get_by_id(_session, _workspace_id):
        return workspace

    monkeypatch.setattr(workspace_service, "get_by_id", _get_by_id)
    monkeypatch.setattr(workspace_registry, "invalidate_roster_shape_cache", spy)

    asyncio.run(workspace_registry._svc_update(session, workspace.id, payload, {}))
    return session, workspace, spy


def test_changing_the_default_invalidates_the_workspace_cache_after_commit(monkeypatch) -> None:
    session, workspace, spy = _run_registry_update(
        monkeypatch,
        schemas.WorkspaceUpdate(default_roster_slots_json={"flex": 6}),
        stored=dict(_STORED),
    )
    assert workspace.default_roster_slots_json == {"flex": 6}
    assert session.committed is True
    assert spy.calls == [({"workspace_id": 7}, True)]


def test_resending_the_same_default_does_not_invalidate(monkeypatch) -> None:
    session, _, spy = _run_registry_update(
        monkeypatch,
        schemas.WorkspaceUpdate(default_roster_slots_json={"support": 2, "damage": 2, "tank": 1}),
        stored=dict(_STORED),
    )
    assert session.committed is True
    assert spy.calls == []


def test_unrelated_edits_do_not_invalidate(monkeypatch) -> None:
    _, _, spy = _run_registry_update(monkeypatch, schemas.WorkspaceUpdate(name="renamed"), stored=dict(_STORED))
    assert spy.calls == []


def test_a_draft_inheriting_the_default_blocks_the_change(monkeypatch) -> None:
    # The change would re-shape that draft's rosters mid-pick: a 1/2/2 team would
    # start accepting a second tank because the slot rule is asked about a shape
    # nobody drafted into. Nothing is written and nothing is invalidated.
    with pytest.raises(BaseAPIException) as exc_info:
        _run_registry_update(
            monkeypatch,
            schemas.WorkspaceUpdate(default_roster_slots_json={"flex": 6}),
            stored=dict(_STORED),
            lock_rows=[(42, "live")],
        )

    assert exc_info.value.status_code == 400
    assert "42" in str(exc_info.value.detail)


def test_an_unrelated_edit_is_not_gated_by_the_shape_lock(monkeypatch) -> None:
    # Renaming a workspace whose tournament has a live draft stays allowed: only
    # the shape moves rosters.
    session, _, spy = _run_registry_update(
        monkeypatch,
        schemas.WorkspaceUpdate(name="renamed"),
        stored=dict(_STORED),
        lock_rows=[(42, "live")],
    )
    assert session.committed is True
    assert spy.calls == []
