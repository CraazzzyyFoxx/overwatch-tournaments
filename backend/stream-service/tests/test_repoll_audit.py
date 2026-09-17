"""The audit-scope invariant for ``rpc.stream.repoll``.

Three properties, in descending order of how quietly they break:

1. **The recorded workspace is the authorized workspace.** Both values are
   captured and compared against each other, not each against a constant — an
   implementation that re-derived the workspace for the audit row (from the
   tournament, say) could satisfy two separate constant assertions while recording
   an action as authorized in a workspace where it was not. The fake session's
   tournament lookup drifts on every call precisely so that a second resolution
   would show up.
2. **The row lands before the commit.** ``record_audit`` never commits, so the row
   rides the caller's transaction (``shared/services/audit.py``). Placed after
   ``commit()`` it goes into a separate transaction and atomicity is gone — while
   the naive test "a row appeared" stays green. So the ORDER is asserted, not just
   the count.
3. **A rejected re-poll leaves no trail.** The journal records writes, not
   attempts: neither a permission denial nor a cross-workspace tournament may
   produce a row, a commit, or a cleared poll cursor.

Runs under stdlib unittest with a fake session and a fake Redis: no database, no
broker, and real ``ensure_workspace_permission``/``record_audit`` so the rejection
paths are the production ones.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "stream-service"))


from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.platform.audit import AuditLog  # noqa: E402
from shared.rpc import identity as shared_identity  # noqa: E402
from src.rpc import admin  # noqa: E402
from src.services import state  # noqa: E402

TOURNAMENT_ID = 5
AUTHORIZED_WORKSPACE = 7

#: Workspace admin holding exactly stream.update in AUTHORIZED_WORKSPACE.
OPERATOR: dict[str, Any] = {
    "user_id": 3,
    "username": "operator",
    "is_superuser": False,
    "is_active": True,
    "roles": [],
    "permissions": [],
    "workspaces": [
        {
            "workspace_id": AUTHORIZED_WORKSPACE,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "stream", "action": "update"}],
        }
    ],
}

#: Same workspace, read-only: stream.read is not stream.update.
SPECTATOR: dict[str, Any] = {
    "user_id": 4,
    "username": "spectator",
    "is_superuser": False,
    "is_active": True,
    "roles": [],
    "permissions": [],
    "workspaces": [
        {
            "workspace_id": AUTHORIZED_WORKSPACE,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "stream", "action": "read"}],
        }
    ],
}


def _request(identity: dict[str, Any] | None, *, workspace_id: int = AUTHORIZED_WORKSPACE) -> dict[str, Any]:
    """The gateway envelope: path param at the top level, query under ``query``,
    and ``ip_address``/``user_agent`` at the top level too — NOT inside a payload."""
    data: dict[str, Any] = {
        "tournament_id": str(TOURNAMENT_ID),
        "query": {"workspace_id": [str(workspace_id)]},
        "ip_address": "203.0.113.7",
        "user_agent": "curl/8",
    }
    if identity is not None:
        data["identity"] = identity
    return data


class _DriftingTournamentWorkspace:
    """A tournament-ownership lookup that answers differently on every call.

    The drift is the point: the handler must resolve the owning workspace once, for
    the ownership check, and then reuse the value the permission check ran against
    for the audit row. An implementation that asked again would record ``97`` while
    authorization ran against ``7``, and the equality assertion below catches it.
    """

    def __init__(self, first: int = AUTHORIZED_WORKSPACE) -> None:
        self.first = first
        self.calls = 0

    def next(self) -> int:
        self.calls += 1
        return self.first if self.calls == 1 else self.first + 90


class _FakeSession:
    """Collects the staged rows and the commit, in order."""

    def __init__(self, owner: _DriftingTournamentWorkspace | None) -> None:
        self._owner = owner
        self.log: list[str] = []
        self.added: list[Any] = []

    def add(self, row: Any) -> None:
        self.added.append(row)
        self.log.append("add")

    async def scalar(self, statement: Any) -> Any:
        return None if self._owner is None else self._owner.next()

    async def commit(self) -> None:
        self.log.append("commit")


class _FakeRedis:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, *keys: str) -> int:
        self.deleted.extend(keys)
        return len(keys)


class _RepollCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.owner = _DriftingTournamentWorkspace()
        self.session = _FakeSession(self.owner)
        self.redis = _FakeRedis()
        #: Every workspace ``ensure_workspace_permission`` was actually checked
        #: against, captured by delegating to the real gate rather than replacing it.
        self.authorized_workspaces: list[int] = []

        real_gate = shared_identity.ensure_workspace_permission

        def spy(user: Any, workspace_id: int, resource: str, action: str) -> None:
            real_gate(user, workspace_id, resource, action)
            self.authorized_workspaces.append(workspace_id)

        patcher = patch.object(admin, "ensure_workspace_permission", spy)
        patcher.start()
        self.addCleanup(patcher.stop)

        redis_patcher = patch.object(admin, "realtime_redis", self.redis)
        redis_patcher.start()
        self.addCleanup(redis_patcher.stop)

        #: The gate is a process-global configured at service startup, which these
        #: tests never run. Kept as a handle so the rejection cases can assert the
        #: call was refused before any quota was spent.
        self.charge = AsyncMock()
        quota_patcher = patch.object(admin, "quota", SimpleNamespace(charge=self.charge))
        quota_patcher.start()
        self.addCleanup(quota_patcher.stop)

    @property
    def rows(self) -> list[AuditLog]:
        return [row for row in self.session.added if isinstance(row, AuditLog)]


class RepollSuccessTests(_RepollCase):
    async def test_records_exactly_one_row_in_the_authorized_workspace(self) -> None:
        result = await admin.repoll(self.session, _request(OPERATOR))

        self.assertEqual(result.tournament_id, TOURNAMENT_ID)
        self.assertEqual(len(self.rows), 1)
        # Two captured lists compared against each other, never against 7.
        self.assertEqual([row.workspace_id for row in self.rows], self.authorized_workspaces)
        # Resolved once and reused: a second lookup would have drifted to 97.
        self.assertEqual(self.owner.calls, 1)

    async def test_row_is_staged_before_the_commit(self) -> None:
        await admin.repoll(self.session, _request(OPERATOR))

        self.assertEqual(self.session.log, ["add", "commit"])

    async def test_row_names_the_action_actor_and_entity(self) -> None:
        await admin.repoll(self.session, _request(OPERATOR))

        row = self.rows[0]
        self.assertEqual(row.action, "stream.repoll")
        self.assertEqual(row.source, "admin")
        self.assertEqual(row.entity_type, "tournament")
        self.assertEqual(row.entity_id, TOURNAMENT_ID)
        self.assertEqual(row.actor_auth_user_id, 3)
        # Snapshotted, not joined: the row must still name the actor once the
        # account behind actor_auth_user_id is gone (there is no FK).
        self.assertEqual(row.actor_label, "operator")
        self.assertEqual(row.ip_address, "203.0.113.7")
        self.assertEqual(row.user_agent, "curl/8")

    async def test_poll_cursor_is_cleared_so_the_next_heartbeat_is_due(self) -> None:
        await admin.repoll(self.session, _request(OPERATOR))

        self.assertEqual(self.redis.deleted, [state.LAST_RUN_KEY])

    async def test_no_before_after_diff_is_recorded(self) -> None:
        await admin.repoll(self.session, _request(OPERATOR))

        # A re-poll changes no domain row; a diff here would be invented state.
        self.assertIsNone(self.rows[0].before_json)
        self.assertIsNone(self.rows[0].after_json)


class RepollRejectionTests(_RepollCase):
    """No row, no commit, no cleared cursor, no quota spent on any rejected path."""

    def _assert_nothing_happened(self) -> None:
        self.assertEqual(self.rows, [])
        self.assertEqual(self.session.log, [])
        self.assertEqual(self.redis.deleted, [])
        # Metering a call that was refused would bill the caller for nothing.
        self.charge.assert_not_awaited()

    async def test_permission_denied_writes_nothing(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await admin.repoll(self.session, _request(SPECTATOR))

        self.assertEqual(ctx.exception.status_code, 403)
        self._assert_nothing_happened()

    async def test_anonymous_caller_writes_nothing(self) -> None:
        with self.assertRaises(shared_identity.MissingIdentityError):
            await admin.repoll(self.session, _request(None))

        self._assert_nothing_happened()
        self.assertEqual(self.authorized_workspaces, [])

    async def test_foreign_tournament_writes_nothing(self) -> None:
        # Authorized in workspace 7, but the tournament belongs to 42: without this
        # guard an admin of their own workspace could trigger polling for someone
        # else's tournament by passing a foreign tournament_id.
        self.session = _FakeSession(_DriftingTournamentWorkspace(first=42))

        with self.assertRaises(HTTPException) as ctx:
            await admin.repoll(self.session, _request(OPERATOR))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Tournament does not belong to this workspace")
        self._assert_nothing_happened()

    async def test_missing_tournament_writes_nothing(self) -> None:
        self.session = _FakeSession(None)

        with self.assertRaises(HTTPException) as ctx:
            await admin.repoll(self.session, _request(OPERATOR))

        self.assertEqual(ctx.exception.status_code, 404)
        self._assert_nothing_happened()

    async def test_missing_workspace_id_writes_nothing(self) -> None:
        data = _request(OPERATOR)
        data["query"] = {}

        with self.assertRaises(HTTPException) as ctx:
            await admin.repoll(self.session, data)

        self.assertEqual(ctx.exception.status_code, 422)
        self._assert_nothing_happened()
