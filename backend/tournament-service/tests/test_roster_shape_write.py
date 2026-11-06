"""The active-draft guard of the roster-shape/team-format writes; the draft format's own lock is the flow's
(``test_flow_apply_changes.py``)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.errors import BaseAPIException  # noqa: E402
from src.services.draft_guards import assert_no_active_draft_session  # noqa: E402


class _FakeSession:
    """Just enough of AsyncSession for the guard.

    ``scalar`` mirrors the guard's ``status NOT IN (cancelled, completed)``
    filter: a terminal status is invisible to the query, exactly as in Postgres.
    """

    _TERMINAL = {"cancelled", "completed"}

    def __init__(self, draft_status=None):
        self._draft_status = draft_status
        self.scalar_stmts: list = []

    async def scalar(self, stmt):
        self.scalar_stmts.append(stmt)
        if self._draft_status in self._TERMINAL:
            return None
        return self._draft_status


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
