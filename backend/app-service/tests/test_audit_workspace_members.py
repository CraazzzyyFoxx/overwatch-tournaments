"""Audit instrumentation of the workspace create + member mutations in app-service.

Each of these flows calls a ``workspaces`` service method that owns its own
``session.commit()``, so the assertion that matters is ordering: the row is
staged on the same session *before* that commit, never after it (which would
put the journal entry in a second transaction that nothing commits).

``member_roles_backfill`` carries no ``after`` on purpose -- the assigned count
only exists once ``backfill_member_roles`` has already committed.

Harness (``_RecordingSession``, ``_handler``, ``_workspace``) is shared with
``test_audit_workspace.py``, which covers the custom-domain and icon writes.
"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from src.rpc import workspaces as workspaces_rpc
from tests.test_audit_workspace import _handler, _RecordingSession, _workspace

_ID = {"user_id": 42, "username": "kate", "is_active": True, "is_superuser": True}
_WS = 7


def _committing(result=None):
    async def _fn(session, *a, **kw):
        await session.commit()
        return result

    return _fn


class NewRowsTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        for target in ("ensure_workspace_permission",):
            p = patch.object(workspaces_rpc, target, MagicMock())
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(workspaces_rpc, "_member_payload", AsyncMock(return_value=None))
        p.start()
        self.addCleanup(p.stop)
        # Role resolution moved onto ``WorkspaceService`` (the module-level
        # ``_resolve_role_ids`` helper is gone); stub it where the handlers
        # actually call it.
        p = patch.object(workspaces_rpc.workspace_service, "resolve_member_role_ids", AsyncMock(return_value=[5]))
        p.start()
        self.addCleanup(p.stop)
        # The owner-role gate reads the database; its behavior is covered in test_workspace_rbac_changes.py.
        p = patch.object(workspaces_rpc.workspace_service, "ensure_owner_role_change_allowed", AsyncMock())
        p.start()
        self.addCleanup(p.stop)

    def _assert(self, session, action, after, *, events=("add", "commit")):
        rows = session.audit_rows
        self.assertEqual(1, len(rows), f"rows={rows} events={session.events}")
        self.assertEqual(action, rows[0].action)
        self.assertEqual("admin", rows[0].source)
        self.assertEqual(42, rows[0].actor_auth_user_id)
        self.assertEqual(after, rows[0].after_json)
        self.assertEqual(list(events), session.events[:2], f"events={session.events}")

    async def test_create(self) -> None:
        session = _RecordingSession()
        handler = _handler(workspaces_rpc, "rpc.app.workspaces.create")
        with (
            patch.object(workspaces_rpc, "_SF", lambda: session),
            patch.object(workspaces_rpc.workspace_service, "provision", _committing(_workspace())),
        ):
            envelope = await handler({"identity": _ID, "payload": {"slug": "acme", "name": "Acme Cup"}}, MagicMock())
        self.assertIn("data", envelope)
        # ``create`` is the one flow whose row lands in a SECOND transaction --
        # the id it names does not exist until ``provision`` has committed. The
        # documented ceiling (see the handler): a crash between the two commits
        # loses the trail, never the workspace.
        self._assert(session, "workspace.create", {"name": "Acme Cup", "slug": "acme"}, events=("commit", "add"))
        # Scoped to the workspace it just created, not left global: the id is
        # what makes the row findable from that workspace's own journal.
        self.assertEqual(_workspace().id, session.audit_rows[0].workspace_id)
        self.assertEqual("Acme Cup", session.audit_rows[0].entity_label)

    async def test_member_add(self) -> None:
        session = _RecordingSession()
        handler = _handler(workspaces_rpc, "rpc.app.workspaces.member_add")
        with (
            patch.object(workspaces_rpc, "_SF", lambda: session),
            patch.object(workspaces_rpc.workspace_service, "get_by_id", AsyncMock(return_value=_workspace())),
            patch.object(workspaces_rpc._auth_user_repo, "get", AsyncMock(return_value=MagicMock())),
            patch.object(workspaces_rpc.workspace_service, "get_member", AsyncMock(return_value=None)),
            patch.object(workspaces_rpc.workspace_service, "invite_member", _committing(MagicMock())),
        ):
            await handler({"workspace_id": _WS, "identity": _ID, "payload": {"auth_user_id": 22}}, MagicMock())
        self._assert(session, "workspace.member_add", {"auth_user_id": 22, "role_ids": [5]})
        self.assertEqual(_WS, session.audit_rows[0].workspace_id)

    async def test_member_update(self) -> None:
        session = _RecordingSession()
        handler = _handler(workspaces_rpc, "rpc.app.workspaces.member_update")
        with (
            patch.object(workspaces_rpc, "_SF", lambda: session),
            patch.object(workspaces_rpc.workspace_service, "get_member", AsyncMock(return_value=MagicMock())),
            patch.object(workspaces_rpc.workspace_service, "change_member_roles", _committing(MagicMock())),
        ):
            await handler(
                {"workspace_id": _WS, "auth_user_id": 22, "identity": _ID, "payload": {"role_ids": [5]}},
                MagicMock(),
            )
        self._assert(session, "workspace.member_update", {"auth_user_id": 22, "role_ids": [5]})

    async def test_member_remove(self) -> None:
        session = _RecordingSession()
        handler = _handler(workspaces_rpc, "rpc.app.workspaces.member_remove")
        with (
            patch.object(workspaces_rpc, "_SF", lambda: session),
            patch.object(workspaces_rpc.workspace_service, "get_member", AsyncMock(return_value=MagicMock())),
            patch.object(workspaces_rpc.workspace_service, "can_remove_member", AsyncMock(return_value=True)),
            patch.object(workspaces_rpc.workspace_service, "revoke_member", _committing()),
        ):
            envelope = await handler({"workspace_id": _WS, "auth_user_id": 22, "identity": _ID}, MagicMock())
        self.assertIn("data", envelope)
        self._assert(session, "workspace.member_remove", {"auth_user_id": 22})

    async def test_autofill(self) -> None:
        session = _RecordingSession()
        handler = _handler(workspaces_rpc, "rpc.app.workspaces.members_autofill_roles")
        with (
            patch.object(workspaces_rpc, "_SF", lambda: session),
            patch.object(workspaces_rpc.workspace_service, "get_by_id", AsyncMock(return_value=_workspace())),
            patch.object(workspaces_rpc.workspace_service, "backfill_member_roles", _committing(3)),
        ):
            envelope = await handler({"workspace_id": _WS, "identity": _ID}, MagicMock())
        self.assertIn("data", envelope)
        self._assert(session, "workspace.member_roles_backfill", None)
        self.assertEqual(_WS, session.audit_rows[0].entity_id)
