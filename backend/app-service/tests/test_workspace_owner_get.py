"""``rpc.app.workspaces.owner_get`` / ``owner_set`` + ``WorkspaceService.set_owner``
— who is accountable for a workspace, and who may change that.

The gates are the point of this test, and they differ on purpose. The read
resolves ``Workspace.owner_id`` to a username and an email, which
``WorkspaceRead`` deliberately refuses to publish (``GET /api/v1/workspaces/{id}``
is anonymous and the list is cached at the edge), so it sits behind the same
workspace-scoped ``workspace.update`` permission as the ``discord_*`` reads. The
write is stricter still — superuser-only — because ``owner_id`` is what the
per-account create cap is counted over, so an organizer who could reassign it
could hand their own cap away.

Same seams as ``test_workspace_verification_set.py``: the service test runs the
real ``update_fields`` against a namespace workspace with ``record_audit``
patched at the module-level name, while the RPC tests drive the registered
subscriber and only prove the transport wiring.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.factories import make_workspace as _make_workspace  # noqa: E402
from tests.test_audit_workspace import _handler, _workspace  # noqa: E402

workspace_service = importlib.import_module("src.services.workspace.service")
workspaces = workspace_service.workspaces

_GET_SUBJECT = "rpc.app.workspaces.owner_get"
_SET_SUBJECT = "rpc.app.workspaces.owner_set"
_TRANSFER_SUBJECT = "rpc.app.workspaces.owner_transfer"
_ADMIN = {"user_id": 42, "username": "kate", "is_active": True, "is_superuser": True}
_OWNER = {"user_id": 3, "username": "ada", "is_active": True, "is_superuser": False}
_OUTSIDER = {"user_id": 9, "username": "mallory", "is_active": True, "is_superuser": False}


def _actor() -> SimpleNamespace:
    return SimpleNamespace(id=42, username="kate")


def _auth_user(**over) -> SimpleNamespace:
    return SimpleNamespace(
        id=over.get("id", 7),
        username=over.get("username", "ada"),
        email=over.get("email", "ada@example.com"),
        first_name=over.get("first_name", "Ada"),
        last_name=over.get("last_name", "Lovelace"),
        player=SimpleNamespace(avatar_url=over.get("avatar_url", "https://cdn.example.com/ada.webp")),
    )


class OwnerGetRPCTests(IsolatedAsyncioTestCase):
    async def _call(self, data, *, ws=None, auth_user=None, gate=None):
        module = importlib.import_module("src.rpc.workspaces")
        handler = _handler(module, _GET_SUBJECT)
        lookup = AsyncMock(return_value=auth_user)
        with (
            patch("src.rpc.workspaces.workspace_service.get_by_id", AsyncMock(return_value=ws)),
            patch.object(module._auth_user_repo, "get_identity", lookup),
            patch("src.rpc.workspaces.ensure_workspace_permission", gate or MagicMock()),
        ):
            return await handler(data, MagicMock()), lookup

    async def test_returns_the_owner_resolved_to_a_person(self) -> None:
        envelope, lookup = await self._call(
            {"workspace_id": 7, "identity": _ADMIN},
            ws=_workspace(owner_id=7),
            auth_user=_auth_user(),
        )

        self.assertEqual(
            {
                "auth_user_id": 7,
                "username": "ada",
                "email": "ada@example.com",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "avatar_url": "https://cdn.example.com/ada.webp",
            },
            envelope["data"],
        )
        lookup.assert_awaited_once()
        self.assertEqual(7, lookup.await_args.args[1])

    async def test_an_unstamped_workspace_answers_null_without_a_user_read(self) -> None:
        """Pre-self-service workspaces and ``SET NULL``-ed owners are a fact to
        render, not an error: the admin screens show "no owner"."""
        envelope, lookup = await self._call(
            {"workspace_id": 7, "identity": _ADMIN},
            ws=_workspace(owner_id=None),
        )

        self.assertIsNone(envelope["data"])
        lookup.assert_not_awaited()

    async def test_a_vanished_owner_row_still_answers_with_the_id(self) -> None:
        envelope, _ = await self._call(
            {"workspace_id": 7, "identity": _ADMIN},
            ws=_workspace(owner_id=7),
            auth_user=None,
        )

        self.assertEqual(7, envelope["data"]["auth_user_id"])
        self.assertIsNone(envelope["data"]["username"])

    async def test_refuses_a_caller_without_workspace_update(self) -> None:
        """The whole reason owner is not on ``WorkspaceRead``."""
        from shared.core.errors import BaseAPIException

        def deny(*args, **kwargs):
            raise BaseAPIException(status_code=403, detail="Permission denied")

        envelope, lookup = await self._call(
            {"workspace_id": 7, "identity": _OUTSIDER},
            ws=_workspace(owner_id=7),
            auth_user=_auth_user(),
            gate=MagicMock(side_effect=deny),
        )

        self.assertEqual("forbidden", envelope["error"]["code"])
        lookup.assert_not_awaited()

    async def test_404s_a_missing_workspace(self) -> None:
        envelope, lookup = await self._call({"workspace_id": 7, "identity": _ADMIN}, ws=None)

        self.assertEqual("not_found", envelope["error"]["code"])
        lookup.assert_not_awaited()


class SetOwnerTests(IsolatedAsyncioTestCase):
    async def test_stamps_the_new_owner_and_records_the_before_and_after(self) -> None:
        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
        workspace = _make_workspace(owner_id=None)

        with patch.object(workspace_service, "record_audit", AsyncMock()) as audit:
            result = await workspaces.set_owner(session, workspace, 11, actor=_actor())

        self.assertIs(result, workspace)
        self.assertEqual(11, workspace.owner_id)
        session.flush.assert_awaited_once()
        session.commit.assert_awaited_once()
        kwargs = audit.await_args.kwargs
        self.assertEqual("workspace.owner_set", kwargs["action"])
        self.assertEqual({"owner_id": None}, kwargs["before"])
        self.assertEqual({"owner_id": 11}, kwargs["after"])
        self.assertEqual(7, kwargs["entity_id"])

    async def test_clearing_the_stamp_is_a_reachable_state(self) -> None:
        """A workspace with nobody on the hook is where every pre-self-service
        row already sits, so ``None`` has to be assignable, not only escapable."""
        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
        workspace = _make_workspace(owner_id=11)

        with patch.object(workspace_service, "record_audit", AsyncMock()) as audit:
            await workspaces.set_owner(session, workspace, None, actor=_actor())

        self.assertIsNone(workspace.owner_id)
        self.assertEqual({"owner_id": 11}, audit.await_args.kwargs["before"])
        self.assertEqual({"owner_id": None}, audit.await_args.kwargs["after"])


class TransferOwnershipTests(IsolatedAsyncioTestCase):
    """The service half: stamp plus RBAC, in an order that never leaves the
    workspace ownerless."""

    async def _transfer(self, workspace, *, roles_of_previous=("owner", "admin")):
        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
        calls: list[tuple] = []

        async def grant(_session, *, user_id, workspace_id, role_name):
            calls.append(("grant", user_id, role_name))

        async def replace(_session, *, user_id, workspace_id, role_ids):
            calls.append(("replace", user_id, tuple(role_ids)))

        async def default_if_roleless(_session, *, user_id, workspace_id):
            calls.append(("default_if_roleless", user_id))
            return False

        roles = [SimpleNamespace(id=index, name=name) for index, name in enumerate(roles_of_previous, start=1)]
        with (
            patch.object(
                workspaces, "add_member", AsyncMock(side_effect=lambda *a: calls.append(("add_member", a[2])))
            ),
            patch.object(workspaces, "get_member_workspace_roles", AsyncMock(return_value=roles)),
            patch.object(workspace_service, "assign_workspace_system_role", grant),
            patch.object(workspace_service, "replace_user_workspace_roles", replace),
            patch.object(workspace_service, "assign_default_member_role_if_roleless", default_if_roleless),
            patch.object(workspace_service, "record_audit", AsyncMock()) as audit,
            patch.object(workspace_service, "enqueue_outbox_event", AsyncMock()) as self.outbox,
        ):
            await workspaces.transfer_ownership(session, workspace, 11, actor=_actor())
        return calls, audit, session

    async def test_grants_the_recipient_owner_before_demoting_the_previous_one(self) -> None:
        """Two owners in between, never zero — otherwise the "last owner"
        invariant the members screen enforces is momentarily violated."""
        workspace = _make_workspace(owner_id=3)

        calls, _, _ = await self._transfer(workspace)

        self.assertEqual(("add_member", 11), calls[0])
        self.assertEqual(("grant", 11, "owner"), calls[1])
        self.assertEqual(("replace", 3, (2,)), calls[2])  # keeps "admin" (id 2), drops "owner"
        self.assertEqual(("default_if_roleless", 3), calls[3])
        self.assertEqual(11, workspace.owner_id)

    async def test_the_outgoing_owner_keeps_membership_and_falls_back_to_member(self) -> None:
        """Losing the workspace is not being thrown out of it."""
        workspace = _make_workspace(owner_id=3)

        calls, _, _ = await self._transfer(workspace, roles_of_previous=("owner",))

        self.assertIn(("replace", 3, ()), calls)
        self.assertIn(("default_if_roleless", 3), calls)

    async def test_an_unowned_workspace_touches_no_previous_owner(self) -> None:
        workspace = _make_workspace(owner_id=None)

        calls, audit, session = await self._transfer(workspace)

        self.assertEqual([("add_member", 11), ("grant", 11, "owner")], calls)
        self.assertEqual({"owner_id": None}, audit.await_args.kwargs["before"])
        self.assertEqual({"owner_id": 11}, audit.await_args.kwargs["after"])
        session.commit.assert_awaited_once()

    async def test_records_the_hand_off_under_its_own_action(self) -> None:
        workspace = _make_workspace(owner_id=3)

        _, audit, _ = await self._transfer(workspace)

        self.assertEqual("workspace.ownership_transferred", audit.await_args.kwargs["action"])
        self.assertEqual({"owner_id": 3}, audit.await_args.kwargs["before"])
        self.assertEqual({"owner_id": 11}, audit.await_args.kwargs["after"])

    async def test_both_sides_rbac_caches_are_dropped_in_the_same_transaction(self) -> None:
        workspace = _make_workspace(owner_id=3)

        await self._transfer(workspace)

        event = self.outbox.await_args.args[1]
        self.assertEqual(([3, 11], "owner_transferred"), (event.auth_user_ids, event.change))


class OwnerSetRPCTests(IsolatedAsyncioTestCase):
    async def _call(self, data, *, ws=None, auth_user=None):
        module = importlib.import_module("src.rpc.workspaces")
        handler = _handler(module, _SET_SUBJECT)
        setter = AsyncMock(return_value=ws)
        with (
            patch("src.rpc.workspaces.workspace_service.get_by_id", AsyncMock(return_value=ws)),
            patch("src.rpc.workspaces.workspace_service.set_owner", setter),
            patch.object(module._auth_user_repo, "get", AsyncMock(return_value=auth_user)),
            patch.object(module._auth_user_repo, "get_identity", AsyncMock(return_value=auth_user)),
        ):
            return await handler(data, MagicMock()), setter

    async def test_a_superuser_assigns_an_owner_and_gets_the_resolved_person_back(self) -> None:
        envelope, setter = await self._call(
            {"workspace_id": 7, "identity": _ADMIN, "payload": {"auth_user_id": 7}},
            ws=_workspace(owner_id=7),
            auth_user=_auth_user(),
        )

        self.assertEqual("ada", envelope["data"]["username"])
        setter.assert_awaited_once()
        self.assertEqual(7, setter.await_args.args[2])

    async def test_a_workspace_admin_may_not_reassign_accountability(self) -> None:
        """``owner_id`` is what the per-account create cap is counted over, so
        this write is superuser-only even though the matching read is not."""
        envelope, setter = await self._call(
            {"workspace_id": 7, "identity": _OUTSIDER, "payload": {"auth_user_id": 7}},
            ws=_workspace(owner_id=None),
            auth_user=_auth_user(),
        )

        self.assertEqual("forbidden", envelope["error"]["code"])
        setter.assert_not_awaited()

    async def test_404s_an_unknown_target_account_instead_of_an_integrity_error(self) -> None:
        envelope, setter = await self._call(
            {"workspace_id": 7, "identity": _ADMIN, "payload": {"auth_user_id": 4242}},
            ws=_workspace(owner_id=None),
            auth_user=None,
        )

        self.assertEqual("not_found", envelope["error"]["code"])
        setter.assert_not_awaited()

    async def test_a_null_target_clears_without_looking_up_an_account(self) -> None:
        envelope, setter = await self._call(
            {"workspace_id": 7, "identity": _ADMIN, "payload": {"auth_user_id": None}},
            ws=_workspace(owner_id=None),
        )

        self.assertIsNone(envelope["data"])
        self.assertIsNone(setter.await_args.args[2])

    async def test_404s_a_missing_workspace(self) -> None:
        envelope, setter = await self._call(
            {"workspace_id": 7, "identity": _ADMIN, "payload": {"auth_user_id": 7}}, ws=None
        )

        self.assertEqual("not_found", envelope["error"]["code"])
        setter.assert_not_awaited()


class OwnerTransferRPCTests(IsolatedAsyncioTestCase):
    """The gate is what differs from ``owner_set``: the workspace's own owner may
    hand it off, a mere ``workspace.update`` holder may not, and the recipient's
    ownership cap is what stops create-then-transfer from looping past it."""

    async def _call(self, data, *, ws=None, recipient=_auth_user(), limit=None):
        module = importlib.import_module("src.rpc.workspaces")
        handler = _handler(module, _TRANSFER_SUBJECT)
        transfer = AsyncMock(return_value=ws)
        with (
            patch("src.rpc.workspaces.workspace_service.get_by_id", AsyncMock(return_value=ws)),
            patch("src.rpc.workspaces.workspace_service.transfer_ownership", transfer),
            patch(
                "src.rpc.workspaces.workspace_service.ensure_create_limit",
                limit or AsyncMock(),
            ) as cap,
            patch.object(module._auth_user_repo, "get", AsyncMock(return_value=recipient)),
            patch.object(module._auth_user_repo, "get_identity", AsyncMock(return_value=recipient)),
        ):
            return await handler(data, MagicMock()), transfer, cap

    async def test_the_current_owner_may_hand_the_workspace_off(self) -> None:
        envelope, transfer, cap = await self._call(
            {"workspace_id": 7, "identity": _OWNER, "payload": {"auth_user_id": 7}},
            ws=_workspace(owner_id=_OWNER["user_id"]),
        )

        self.assertEqual("ada", envelope["data"]["username"])
        transfer.assert_awaited_once()
        self.assertEqual(7, transfer.await_args.args[2])
        cap.assert_awaited_once()

    async def test_a_workspace_admin_who_is_not_the_owner_is_refused(self) -> None:
        envelope, transfer, _ = await self._call(
            {"workspace_id": 7, "identity": _OUTSIDER, "payload": {"auth_user_id": 7}},
            ws=_workspace(owner_id=_OWNER["user_id"]),
        )

        self.assertEqual("forbidden", envelope["error"]["code"])
        transfer.assert_not_awaited()

    async def test_a_superuser_may_transfer_a_workspace_they_do_not_own(self) -> None:
        """And skips the recipient's cap: a superuser assignment is its override,
        exactly as on ``owner_set``."""
        envelope, transfer, cap = await self._call(
            {"workspace_id": 7, "identity": _ADMIN, "payload": {"auth_user_id": 7}},
            ws=_workspace(owner_id=_OWNER["user_id"]),
        )

        self.assertNotIn("error", envelope)
        transfer.assert_awaited_once()
        cap.assert_not_awaited()

    async def test_an_unowned_workspace_is_not_up_for_grabs(self) -> None:
        """Nobody is on the hook, so nobody but a superuser has standing."""
        envelope, transfer, _ = await self._call(
            {"workspace_id": 7, "identity": _OWNER, "payload": {"auth_user_id": 7}},
            ws=_workspace(owner_id=None),
        )

        self.assertEqual("forbidden", envelope["error"]["code"])
        transfer.assert_not_awaited()

    async def test_a_recipient_at_their_cap_blocks_the_transfer(self) -> None:
        from shared.core.errors import BaseAPIException

        def deny(*args, **kwargs):
            raise BaseAPIException(status_code=403, detail="workspace_owner_limit_reached")

        envelope, transfer, _ = await self._call(
            {"workspace_id": 7, "identity": _OWNER, "payload": {"auth_user_id": 7}},
            ws=_workspace(owner_id=_OWNER["user_id"]),
            limit=AsyncMock(side_effect=deny),
        )

        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertEqual("workspace_owner_limit_reached", envelope["error"]["message"])
        transfer.assert_not_awaited()

    async def test_404s_an_unknown_recipient(self) -> None:
        envelope, transfer, _ = await self._call(
            {"workspace_id": 7, "identity": _OWNER, "payload": {"auth_user_id": 4242}},
            ws=_workspace(owner_id=_OWNER["user_id"]),
            recipient=None,
        )

        self.assertEqual("not_found", envelope["error"]["code"])
        transfer.assert_not_awaited()

    async def test_rejects_a_transfer_to_nobody(self) -> None:
        """``None`` is the superuser-only clear on ``owner_set``, not a hand-off."""
        envelope, transfer, _ = await self._call(
            {"workspace_id": 7, "identity": _OWNER, "payload": {"auth_user_id": None}},
            ws=_workspace(owner_id=_OWNER["user_id"]),
        )

        self.assertEqual("unprocessable", envelope["error"]["code"])
        transfer.assert_not_awaited()


class ManifestTests(IsolatedAsyncioTestCase):
    """Registered, documented and typed: an unregistered subject only shows up
    as a gateway timeout, and one missing from ``OPERATIONS`` degrades to a
    generic ``object`` in the published manifest."""

    def test_registered_documented_and_typed(self) -> None:
        from src import openapi_docs, openapi_schemas

        registered: dict[str, object] = {}

        def subscriber(name, *args, **kwargs):
            def decorator(fn):
                registered[name] = fn
                return fn

            return decorator

        broker = MagicMock()
        broker.subscriber = subscriber
        importlib.import_module("src.rpc.workspaces").register(broker, MagicMock())

        for subject in (_GET_SUBJECT, _SET_SUBJECT, _TRANSFER_SUBJECT):
            with self.subTest(subject=subject):
                self.assertIn(subject, registered)
                self.assertTrue(openapi_docs.DOCS[subject]["summary"])
                self.assertIn(subject, openapi_schemas.OPERATIONS)
