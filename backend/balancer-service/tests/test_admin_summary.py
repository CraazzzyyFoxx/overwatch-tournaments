"""Contract tests for ``rpc.balancer.admin.tournament_summary_get`` (D29).

The summary RPC resolves the balancer tool's tournament context: id/name/
status/workspace_id, gated by workspace ``team.read``. Hidden (preview)
tournaments MUST stay resolvable — the tool is staff-facing and the
``team.read`` gate already scopes access to workspace members.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402
from src.rpc import admin as admin_rpc  # noqa: E402
from src.services.admin.balancer import balancer_admin_service  # noqa: E402

SUBJECT = "rpc.balancer.admin.tournament_summary_get"


class _CapturingBroker:
    """FakeBroker that keeps the registered handlers so tests can invoke them."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def subscriber(self, subject: str):
        def decorator(function):
            self.handlers[subject] = function
            return function

        return decorator


class _FakeLogger:
    def warning(self, *args, **kwargs) -> None:
        return None

    def exception(self, *args, **kwargs) -> None:
        return None


def _summary_handler():
    broker = _CapturingBroker()
    admin_rpc.register(broker, _FakeLogger())
    return broker.handlers[SUBJECT]


def _identity_with_team_read(workspace_id: int) -> dict:
    """Organizer-style rehydrated identity: workspace ``team.read`` plus a
    non-read permission (grants the admin-panel gate)."""
    return {
        "user_id": 501,
        "is_superuser": False,
        "is_active": True,
        "roles": [],
        "permissions": [],
        "workspaces": [
            {
                "workspace_id": workspace_id,
                "role": "organizer",
                "rbac_roles": ["organizer"],
                "rbac_permissions": [
                    {"resource": "team", "action": "read"},
                    {"resource": "tournament", "action": "update"},
                ],
            }
        ],
    }


def test_rpc_registers_tournament_summary_subject() -> None:
    broker = _CapturingBroker()
    admin_rpc.register(broker, _FakeLogger())
    assert SUBJECT in broker.handlers


class _FakeResult:
    def __init__(self, row) -> None:
        self._row = row

    def one_or_none(self):
        return self._row


class _FakeSession:
    """Session double for handler wire-up tests: records issued statements."""

    def __init__(self, workspace_id: int, row) -> None:
        self._workspace_id = workspace_id
        self._row = row
        self.statements: list = []

    async def scalar(self, stmt):
        self.statements.append(stmt)
        return self._workspace_id

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult(self._row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class TournamentSummaryHandlerUnitTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def test_summary_returns_non_nullable_tournament_fields(self) -> None:
        handler = _summary_handler()
        fake = _FakeSession(workspace_id=9, row=SimpleNamespace(id=7, name="Hidden Cup", status="registration"))
        with patch.object(admin_rpc, "_SF", lambda: fake):
            resp = await handler({"id": 7, "identity": _identity_with_team_read(9)}, None)

        assert resp == {
            "ok": True,
            "data": {"id": 7, "name": "Hidden Cup", "status": "registration", "workspace_id": 9},
        }

    async def test_summary_forbidden_for_other_workspace_membership(self) -> None:
        handler = _summary_handler()
        fake = _FakeSession(workspace_id=9, row=SimpleNamespace(id=7, name="Hidden Cup", status="registration"))
        with patch.object(admin_rpc, "_SF", lambda: fake):
            resp = await handler({"id": 7, "identity": _identity_with_team_read(10)}, None)

        assert resp["ok"] is False
        assert resp["error"]["code"] == "forbidden"

    async def test_tournament_row_query_does_not_filter_hidden(self) -> None:
        """Hidden (preview) tournaments must stay resolvable — the row query
        may key on the tournament id only, never on ``is_hidden``."""
        fake = _FakeSession(workspace_id=9, row=SimpleNamespace(id=7, name="x", status="registration"))
        await balancer_admin_service.get_tournament_row(fake, 7)

        sql = str(fake.statements[-1].compile(compile_kwargs={"literal_binds": True}))
        assert "is_hidden" not in sql
        assert "tournament.id = 7" in sql


class TournamentSummaryRpcTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        # psycopg async cannot run on the Proactor loop (Windows default).
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        suffix = f"summary-it-{os.getpid()}"
        async with self.Session() as s:
            ws = Workspace(slug=f"ws-{suffix}", name=f"WS {suffix}")
            s.add(ws)
            await s.flush()
            # ``slug`` is NOT NULL and globally unique (migration tslug0001), so
            # it carries the same per-run suffix the workspace slug does.
            hidden = Tournament(
                workspace_id=ws.id,
                name=f"Hidden T {suffix}",
                slug=f"hidden-t-{suffix}",
                is_hidden=True,
            )
            s.add(hidden)
            await s.flush()
            self.workspace_id = ws.id
            self.tournament_id = hidden.id
            self.tournament_name = hidden.name
            await s.commit()

    async def asyncTearDown(self) -> None:
        if not hasattr(self, "Session"):
            await self.engine.dispose()
            return
        async with self.Session() as s:
            await s.execute(sa.delete(Tournament).where(Tournament.id == self.tournament_id))
            await s.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await s.commit()
        await self.engine.dispose()

    async def test_summary_returns_hidden_tournament_for_team_read(self) -> None:
        handler = _summary_handler()
        data = {
            "id": self.tournament_id,
            "identity": _identity_with_team_read(self.workspace_id),
        }
        with patch.object(admin_rpc, "_SF", self.Session):
            resp = await handler(data, None)

        assert resp == {
            "ok": True,
            "data": {
                "id": self.tournament_id,
                "name": self.tournament_name,
                "status": "registration",
                "workspace_id": self.workspace_id,
            },
        }

    async def test_summary_forbidden_without_workspace_membership(self) -> None:
        handler = _summary_handler()
        data = {
            "id": self.tournament_id,
            # membership in an unrelated workspace only
            "identity": _identity_with_team_read(self.workspace_id + 999_999),
        }
        with patch.object(admin_rpc, "_SF", self.Session):
            resp = await handler(data, None)

        assert resp["ok"] is False
        assert resp["error"]["code"] == "forbidden"
