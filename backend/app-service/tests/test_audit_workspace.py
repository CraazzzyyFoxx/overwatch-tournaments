"""Audit instrumentation of the bespoke workspace mutations in app-service.

Only the flows that own their own ``session.commit()`` live here: the custom-domain
set/verify/clear trio (``WorkspaceService``) and the two icon writes
(``WorkspaceBinaryService``), driven through their RPC subscribers. Every
field-level workspace edit — settings, SEO, the
branding palette, ``subdomain``, ``discord_guild_id``, the roster shape — travels
``PATCH /api/v1/workspaces/{id}`` -> ``rpc.app.admin.update`` -> the shared CRUD
engine, which records it at its single hook; a second row from here would make one
action look like two.

Each case pins the three things a wrong instrumentation gets wrong silently:

* exactly one row, so an action is never double-counted;
* the workspace and entity the permission check ran against, not a re-derived one;
* the row staged BEFORE the flow's commit. This is the load-bearing assertion —
  a ``record_audit`` placed after the commit lands in its own transaction, and the
  naive "a row appeared" check stays green while a rolled-back mutation keeps a
  trail of having happened.

The verification token is asserted absent from both sides of every domain row: the
journal records that a token was issued, never its value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from shared.models.platform.audit import AuditLog
from src import models
from src.rpc import binary as binary_rpc
from src.rpc import workspaces as workspaces_rpc
from src.services.workspace import binary as workspace_binary_service

_WORKSPACE_ID = 7
# ``username`` is what ``rehydrate_user`` turns into the actor label snapshot.
_IDENTITY = {"user_id": 42, "username": "kate", "is_active": True, "is_superuser": False}


class _RecordingSession:
    """A session that logs the mutating calls in the order they happen.

    ``events`` is what the ordering assertions read: ``add`` is the audit row
    landing in the transaction, ``commit`` is the transaction closing. Nothing here
    talks to a database — the flows under test reach it only through
    ``update_fields`` (setattr + flush) and their own commit.
    """

    def __init__(self) -> None:
        self.events: list[str] = []
        self.added: list[object] = []

    async def flush(self) -> None:
        self.events.append("flush")

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")

    def add(self, obj: object) -> None:
        self.events.append("add")
        self.added.append(obj)

    async def __aenter__(self) -> _RecordingSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    @property
    def audit_rows(self) -> list[AuditLog]:
        return [obj for obj in self.added if isinstance(obj, AuditLog)]


def _workspace(**overrides) -> models.Workspace:
    """A transient ``Workspace`` complete enough for ``WorkspaceRead``.

    A real model, not a namespace: the handlers end by serializing it, and the
    columns whose defaults are server-side (``timezone``, ``branding_enabled``,
    ``is_active``, ``is_hidden``, ``newcomer_scope``, ``verification_status``)
    are None on a transient row, which ``WorkspaceRead`` rejects.
    """
    base = {
        "id": _WORKSPACE_ID,
        "slug": "acme",
        "name": "Acme Cup",
        "description": None,
        "icon_url": None,
        "is_active": True,
        "is_hidden": False,
        "timezone": "Europe/Moscow",
        "branding_enabled": False,
        "newcomer_scope": "global",
        "verification_status": "unverified",
    }
    base.update(overrides)
    return models.Workspace(**base)


def _handler(module, topic: str):
    """Register ``module``'s subscribers against a capture broker, return one."""
    handlers: dict[str, object] = {}

    def subscriber(name: str, *args, **kwargs):
        def decorator(fn):
            handlers[name] = fn
            return fn

        return decorator

    broker = MagicMock()
    broker.subscriber = subscriber
    module.register(broker, MagicMock())
    return handlers[topic]


def _serialized(row: AuditLog) -> str:
    """Everything the row would carry into the journal, as one string to search."""
    return repr((row.before_json, row.after_json, row.reason, row.entity_label))


class _AuditCase(IsolatedAsyncioTestCase):
    """Shared gate stub + the assertions every workspace audit row must satisfy."""

    module = workspaces_rpc

    def setUp(self) -> None:
        # The permission gate has its own tests on every one of these endpoints;
        # here it must pass so the flow reaches its mutation.
        patcher = patch.object(self.module, "ensure_workspace_permission", MagicMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_one_row(self, session: _RecordingSession, action: str) -> AuditLog:
        self.assertEqual(1, len(session.audit_rows), f"expected exactly one audit row, got {session.events}")
        row = session.audit_rows[0]
        self.assertEqual(action, row.action)
        self.assertEqual("admin", row.source)
        self.assertEqual(_IDENTITY["user_id"], row.actor_auth_user_id)
        self.assertEqual("kate", row.actor_label)  # snapshot, not a live join
        self.assertEqual(_WORKSPACE_ID, row.workspace_id)  # == the authorized workspace
        self.assertEqual("workspace", row.entity_type)
        self.assertEqual(_WORKSPACE_ID, row.entity_id)
        self.assertEqual("acme", row.entity_label)
        return row

    def assert_staged_before_commit(self, session: _RecordingSession) -> None:
        """The row is added, then the transaction closes, with nothing between.

        Fails both ways a call site can be wrong: staged after ``commit()`` (its
        own transaction, atomicity gone) or committed twice.
        """
        self.assertEqual(["add", "commit"], session.events[-2:], f"audit row not inside the mutation: {session.events}")


class SetCustomDomainAuditTests(_AuditCase):
    def setUp(self) -> None:
        super().setUp()
        # The duplicate-claim pre-check is the only query in this flow; the
        # conflict path is covered in test_workspace_custom_domain.py.
        patcher = patch.object(
            workspaces_rpc.workspace_service.workspace_repo, "get_by_custom_domain_any", AsyncMock(return_value=None)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _call(self, workspace: models.Workspace) -> _RecordingSession:
        session = _RecordingSession()
        handler = _handler(workspaces_rpc, "rpc.app.workspaces.set_custom_domain")
        with (
            patch.object(workspaces_rpc, "_SF", lambda: session),
            patch.object(workspaces_rpc.workspace_service, "get_by_id", AsyncMock(return_value=workspace)),
        ):
            envelope = await handler(
                {
                    "workspace_id": _WORKSPACE_ID,
                    "identity": _IDENTITY,
                    "payload": {"custom_domain": "Tourney.Customer.com"},
                },
                MagicMock(),
            )
        self.assertIn("data", envelope)
        return session

    async def test_records_one_row_inside_the_mutation(self) -> None:
        workspace = _workspace()
        session = await self._call(workspace)

        row = self.assert_one_row(session, "workspace.domain_set")
        self.assert_staged_before_commit(session)
        self.assertEqual({"custom_domain": None, "custom_domain_verified_at": None}, row.before_json)
        # Re-pointing always resets verification, so the after side says so.
        self.assertEqual({"custom_domain": "tourney.customer.com", "custom_domain_verified_at": None}, row.after_json)

    async def test_the_previous_domain_and_its_verified_stamp_are_the_before_side(self) -> None:
        verified_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        workspace = _workspace(
            custom_domain="old.example.com",
            custom_domain_verification_token="owt-verify-stale",
            custom_domain_verified_at=verified_at,
        )

        row = self.assert_one_row(await self._call(workspace), "workspace.domain_set")

        self.assertEqual(
            {"custom_domain": "old.example.com", "custom_domain_verified_at": verified_at.isoformat()},
            row.before_json,
        )

    async def test_the_verification_token_never_reaches_the_journal(self) -> None:
        """The row says a token was issued; the value stays out of an append-only
        store that is never purged and could not use it for anything."""
        workspace = _workspace(custom_domain_verification_token="owt-verify-stale")
        session = await self._call(workspace)
        issued = workspace.custom_domain_verification_token
        self.assertTrue(issued.startswith("owt-verify-"))  # a fresh one really was minted

        row = session.audit_rows[0]
        self.assertNotIn("custom_domain_verification_token", row.before_json)
        self.assertNotIn("custom_domain_verification_token", row.after_json)
        self.assertNotIn(issued, _serialized(row))
        self.assertNotIn("owt-verify-stale", _serialized(row))


class VerifyCustomDomainAuditTests(_AuditCase):
    async def _call(self, workspace: models.Workspace) -> _RecordingSession:
        session = _RecordingSession()
        handler = _handler(workspaces_rpc, "rpc.app.workspaces.verify_custom_domain")
        with (
            patch.object(workspaces_rpc, "_SF", lambda: session),
            patch.object(workspaces_rpc.workspace_service, "get_by_id", AsyncMock(return_value=workspace)),
            patch.object(workspaces_rpc.workspace_service, "_dns_txt_contains", AsyncMock(return_value=True)),
        ):
            envelope = await handler({"workspace_id": _WORKSPACE_ID, "identity": _IDENTITY}, MagicMock())
        self.assertIn("data", envelope)
        return session

    async def test_records_one_row_after_the_dns_proof_and_before_the_commit(self) -> None:
        """``verify_custom_domain`` commits once mid-flow to release the connection
        across the DNS lookup, so this also pins that the row is not staged before
        that commit — where a failed verification would still have left a trail."""
        workspace = _workspace(
            custom_domain="tourney.customer.com",
            custom_domain_verification_token="owt-verify-abc123",
        )

        session = await self._call(workspace)

        row = self.assert_one_row(session, "workspace.domain_verified")
        self.assert_staged_before_commit(session)
        self.assertEqual(2, session.events.count("commit"))  # the read release, then the write
        self.assertIsNone(row.before_json["custom_domain_verified_at"])
        self.assertEqual(workspace.custom_domain_verified_at.isoformat(), row.after_json["custom_domain_verified_at"])
        # Unchanged, on both sides on purpose: without it the row would say a
        # domain was verified without saying which one.
        self.assertEqual("tourney.customer.com", row.before_json["custom_domain"])
        self.assertEqual("tourney.customer.com", row.after_json["custom_domain"])

    async def test_the_verification_token_never_reaches_the_journal(self) -> None:
        workspace = _workspace(
            custom_domain="tourney.customer.com",
            custom_domain_verification_token="owt-verify-abc123",
        )

        row = (await self._call(workspace)).audit_rows[0]

        self.assertNotIn("custom_domain_verification_token", row.before_json)
        self.assertNotIn("custom_domain_verification_token", row.after_json)
        self.assertNotIn("owt-verify-abc123", _serialized(row))

    async def test_a_failed_dns_proof_records_nothing(self) -> None:
        """No trail of a verification that did not happen."""
        session = _RecordingSession()
        handler = _handler(workspaces_rpc, "rpc.app.workspaces.verify_custom_domain")
        workspace = _workspace(
            custom_domain="tourney.customer.com",
            custom_domain_verification_token="owt-verify-abc123",
        )
        with (
            patch.object(workspaces_rpc, "_SF", lambda: session),
            patch.object(workspaces_rpc.workspace_service, "get_by_id", AsyncMock(return_value=workspace)),
            patch.object(workspaces_rpc.workspace_service, "_dns_txt_contains", AsyncMock(return_value=False)),
        ):
            envelope = await handler({"workspace_id": _WORKSPACE_ID, "identity": _IDENTITY}, MagicMock())

        self.assertNotIn("data", envelope)
        self.assertEqual([], session.audit_rows)


class ClearCustomDomainAuditTests(_AuditCase):
    async def test_records_one_row_inside_the_mutation_without_the_token(self) -> None:
        session = _RecordingSession()
        handler = _handler(workspaces_rpc, "rpc.app.workspaces.clear_custom_domain")
        verified_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        workspace = _workspace(
            custom_domain="tourney.customer.com",
            custom_domain_verification_token="owt-verify-abc123",
            custom_domain_verified_at=verified_at,
        )
        with (
            patch.object(workspaces_rpc, "_SF", lambda: session),
            patch.object(workspaces_rpc.workspace_service, "get_by_id", AsyncMock(return_value=workspace)),
        ):
            envelope = await handler({"workspace_id": _WORKSPACE_ID, "identity": _IDENTITY}, MagicMock())

        self.assertIn("data", envelope)
        row = self.assert_one_row(session, "workspace.domain_clear")
        self.assert_staged_before_commit(session)
        self.assertEqual(
            {"custom_domain": "tourney.customer.com", "custom_domain_verified_at": verified_at.isoformat()},
            row.before_json,
        )
        self.assertEqual({"custom_domain": None, "custom_domain_verified_at": None}, row.after_json)
        # The dropped token is implied by the domain going away; its value is not
        # written, the same discipline as domain_set.
        self.assertNotIn("owt-verify-abc123", _serialized(row))


class WorkspaceIconAuditTests(_AuditCase):
    """The two icon writes are branding edits with their own commit — the CRUD
    engine never sees them, so they are audited here."""

    module = binary_rpc

    def setUp(self) -> None:
        super().setUp()
        # The upload is metered, and ``shared.quota`` is unconfigured in this
        # process; the gate's own behaviour belongs to test_quota_admin.py.
        patcher = patch.object(binary_rpc, "quota", MagicMock(charge=AsyncMock()))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_icon_upload_records_one_branding_row_inside_the_mutation(self) -> None:
        session = _RecordingSession()
        handler = _handler(binary_rpc, "rpc.app.workspaces.icon_upload")
        workspace = _workspace(icon_url="https://cdn.test/old.png")
        upload = AsyncMock(return_value=MagicMock(success=True, public_url="https://cdn.test/new.png"))
        with (
            patch.object(binary_rpc, "_SF", lambda: session),
            patch.object(binary_rpc.workspace_binary.workspaces, "get_by_id", AsyncMock(return_value=workspace)),
            patch.object(workspace_binary_service, "upload_avatar", upload),
        ):
            envelope = await handler(
                {"id": _WORKSPACE_ID, "identity": _IDENTITY, "content_b64": "AAAA", "content_type": "image/png"},
                MagicMock(),
            )

        self.assertIn("data", envelope)
        row = self.assert_one_row(session, "workspace.branding_update")
        self.assert_staged_before_commit(session)
        self.assertEqual({"icon_url": "https://cdn.test/old.png"}, row.before_json)
        self.assertEqual({"icon_url": "https://cdn.test/new.png"}, row.after_json)

    async def test_a_failed_upload_records_nothing(self) -> None:
        session = _RecordingSession()
        handler = _handler(binary_rpc, "rpc.app.workspaces.icon_upload")
        upload = AsyncMock(return_value=MagicMock(success=False, error="too large"))
        with (
            patch.object(binary_rpc, "_SF", lambda: session),
            patch.object(binary_rpc.workspace_binary.workspaces, "get_by_id", AsyncMock(return_value=_workspace())),
            patch.object(workspace_binary_service, "upload_avatar", upload),
        ):
            envelope = await handler(
                {"id": _WORKSPACE_ID, "identity": _IDENTITY, "content_b64": "AAAA", "content_type": "image/png"},
                MagicMock(),
            )

        self.assertNotIn("data", envelope)
        self.assertEqual([], session.audit_rows)

    async def test_icon_delete_records_the_removal(self) -> None:
        session = _RecordingSession()
        handler = _handler(binary_rpc, "rpc.app.workspaces.icon_delete")
        workspace = _workspace(icon_url="https://cdn.test/old.png")
        with (
            patch.object(binary_rpc, "_SF", lambda: session),
            patch.object(binary_rpc.workspace_binary.workspaces, "get_by_id", AsyncMock(return_value=workspace)),
            patch.object(workspace_binary_service, "s3_client", MagicMock(delete_prefix=AsyncMock())),
        ):
            envelope = await handler({"id": _WORKSPACE_ID, "identity": _IDENTITY}, MagicMock())

        self.assertIn("data", envelope)
        row = self.assert_one_row(session, "workspace.branding_update")
        self.assert_staged_before_commit(session)
        self.assertEqual({"icon_url": "https://cdn.test/old.png"}, row.before_json)
        self.assertEqual({"icon_url": None}, row.after_json)
