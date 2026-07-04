"""Workspace-scoped per-user permission denies (negative RBAC).

Covers the admin CRUD surface added on top of the existing (Phase A/B)
``UserPermissionDeny.workspace_id`` column: ``add_user_deny``/``remove_user_deny``
now accept an optional ``workspace_id`` (``None`` = global deny, a concrete id =
scoped to that workspace only), and ``list_user_denies`` surfaces the scope of
every deny row. The critical invariant under test is the NULL-safe scope match
(``_workspace_scope_filter``): a global deny and a workspace-scoped deny for the
same permission must never be conflated by add's idempotency check or by
remove's delete, mirroring the ``COALESCE(workspace_id, 0)`` partial-unique
index in ``shared.models.identity.rbac.UserPermissionDeny``.
"""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from shared.core.errors import BaseAPIException as HTTPException


def _ensure_test_env() -> None:
    env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "auth_test",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
        "JWT_SECRET_KEY": "test-secret",
        "DISCORD_CLIENT_ID": "discord-client",
        "DISCORD_CLIENT_SECRET": "discord-secret",
        "TWITCH_CLIENT_ID": "twitch-client",
        "TWITCH_CLIENT_SECRET": "twitch-secret",
        "BATTLENET_CLIENT_ID": "battlenet-client",
        "BATTLENET_CLIENT_SECRET": "battlenet-secret",
        "OAUTH_REDIRECT": "http://localhost:3000/auth/callback",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)


_ensure_test_env()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services import rbac_flows  # noqa: E402


def _current_user(user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, is_superuser=True, has_permission=lambda _r, _a: True)


class _AllResult:
    """Fakes the ``Result`` object returned by ``session.execute(select(...))`` for
    the ``.all()`` (row-tuple) access pattern used by ``list_user_denies``."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _ScalarQueueSession:
    """Fakes ``session.scalar(...)`` as a FIFO queue of canned results (mirrors
    the ``_FakeSession`` pattern in ``test_rbac_admin_users.py``), plus a fixed
    ``execute(...)`` result for the trailing ``list_user_denies`` re-fetch."""

    def __init__(self, scalars: list, list_rows: list[tuple] | None = None) -> None:
        self._scalars = list(scalars)
        self._list_result = _AllResult(list_rows or [])
        self.added: list = []
        self.commit_called = False

    async def scalar(self, _query):
        return self._scalars.pop(0)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commit_called = True

    async def execute(self, _query):
        return self._list_result


class _CapturingSession:
    """Fakes a session whose ``execute(...)`` calls are all recorded, so the
    compiled SQL of a ``delete(...)`` statement can be inspected directly."""

    def __init__(self, list_rows: list[tuple] | None = None) -> None:
        self.executed: list = []
        self.commit_called = False
        self._list_result = _AllResult(list_rows or [])

    async def execute(self, query):
        self.executed.append(query)
        return self._list_result

    async def commit(self) -> None:
        self.commit_called = True


def _compiled(clause) -> str:
    return str(clause.compile(compile_kwargs={"literal_binds": True}))


# --- _workspace_scope_filter: the NULL-safe scope predicate ---


def test_workspace_scope_filter_global_renders_is_null() -> None:
    clause = rbac_flows._workspace_scope_filter(None)
    assert "IS NULL" in _compiled(clause)


def test_workspace_scope_filter_scoped_renders_equality() -> None:
    clause = rbac_flows._workspace_scope_filter(42)
    compiled = _compiled(clause)
    assert "= 42" in compiled
    assert "IS NULL" not in compiled


# --- list_user_denies: surfaces workspace_id per row ---


def test_list_user_denies_returns_workspace_id_per_row(monkeypatch: pytest.MonkeyPatch) -> None:
    global_permission = SimpleNamespace(
        id=1, name="account.avatar", resource="account", action="avatar", description=None
    )
    scoped_permission = SimpleNamespace(
        id=2,
        name="registration.self_register",
        resource="registration",
        action="self_register",
        description=None,
    )

    class _Session:
        async def execute(self, _query):
            return _AllResult([(global_permission, None), (scoped_permission, 7)])

    result = asyncio.run(rbac_flows.list_user_denies(_Session(), _current_user(), 9))

    assert result == [
        {
            "permission_id": 1,
            "name": "account.avatar",
            "resource": "account",
            "action": "avatar",
            "description": None,
            "workspace_id": None,
        },
        {
            "permission_id": 2,
            "name": "registration.self_register",
            "resource": "registration",
            "action": "self_register",
            "description": None,
            "workspace_id": 7,
        },
    ]


# --- add_user_deny: workspace-scoped create ---


def test_add_user_deny_scopes_new_row_to_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(id=9)
    permission = SimpleNamespace(
        id=3,
        name="registration.self_register",
        resource="registration",
        action="self_register",
        description=None,
    )
    workspace = SimpleNamespace(id=7, name="Test Workspace")

    async def fake_invalidate_rbac(_user_id):
        return None

    monkeypatch.setattr("src.services.rbac_flows.invalidate_rbac", fake_invalidate_rbac, raising=False)

    # scalar() call order in add_user_deny: user, permission, workspace, existing-deny.
    session = _ScalarQueueSession(
        scalars=[user, permission, workspace, None],
        list_rows=[(permission, 7)],
    )

    result = asyncio.run(
        rbac_flows.add_user_deny(session, _current_user(), 9, 3, workspace_id=7)
    )

    assert session.commit_called is True
    assert len(session.added) == 1
    created = session.added[0]
    assert created.user_id == 9
    assert created.permission_id == 3
    assert created.workspace_id == 7
    assert result == [
        {
            "permission_id": 3,
            "name": "registration.self_register",
            "resource": "registration",
            "action": "self_register",
            "description": None,
            "workspace_id": 7,
        }
    ]


def test_add_user_deny_defaults_to_global_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(id=9)
    permission = SimpleNamespace(
        id=4, name="account.social", resource="account", action="social", description=None
    )

    async def fake_invalidate_rbac(_user_id):
        return None

    monkeypatch.setattr("src.services.rbac_flows.invalidate_rbac", fake_invalidate_rbac, raising=False)

    # No workspace lookup call is expected when workspace_id is omitted.
    session = _ScalarQueueSession(scalars=[user, permission, None], list_rows=[(permission, None)])

    result = asyncio.run(rbac_flows.add_user_deny(session, _current_user(), 9, 4))

    created = session.added[0]
    assert created.workspace_id is None
    assert result[0]["workspace_id"] is None


def test_add_user_deny_raises_404_for_unknown_workspace() -> None:
    user = SimpleNamespace(id=9)
    permission = SimpleNamespace(
        id=3,
        name="registration.self_register",
        resource="registration",
        action="self_register",
        description=None,
    )

    session = _ScalarQueueSession(scalars=[user, permission, None])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rbac_flows.add_user_deny(session, _current_user(), 9, 3, workspace_id=999))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Workspace not found"
    assert session.added == []


# --- remove_user_deny: scoped delete never crosses scopes ---


def test_remove_user_deny_global_scope_matches_null_only(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_invalidate_rbac(_user_id):
        return None

    monkeypatch.setattr("src.services.rbac_flows.invalidate_rbac", fake_invalidate_rbac, raising=False)

    session = _CapturingSession()

    asyncio.run(rbac_flows.remove_user_deny(session, _current_user(), 9, 3, workspace_id=None))

    assert session.commit_called is True
    delete_stmt = session.executed[0]
    compiled = _compiled(delete_stmt)
    assert "workspace_id IS NULL" in compiled
    assert "workspace_id = " not in compiled


def test_remove_user_deny_workspace_scope_matches_that_workspace_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_invalidate_rbac(_user_id):
        return None

    monkeypatch.setattr("src.services.rbac_flows.invalidate_rbac", fake_invalidate_rbac, raising=False)

    session = _CapturingSession()

    asyncio.run(rbac_flows.remove_user_deny(session, _current_user(), 9, 3, workspace_id=7))

    assert session.commit_called is True
    delete_stmt = session.executed[0]
    compiled = _compiled(delete_stmt)
    assert "workspace_id = 7" in compiled
    assert "IS NULL" not in compiled
