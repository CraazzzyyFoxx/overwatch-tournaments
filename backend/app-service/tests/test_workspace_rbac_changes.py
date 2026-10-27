"""Who may hand out or take away ``owner`` (Q2), and the app-service writers that must tell identity (Q9).

Only an owner of the workspace, or a superuser, grants or revokes the ``owner`` role through the member screens;
``workspace_member.*`` alone covers every other role change. Deleting a workspace or a linked player stages the
RBAC-change event in the delete's own transaction. Nothing here commits: the session closes with a rollback. Needs the
test Postgres; skips otherwise.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

import sqlalchemy as sa

from shared.core.errors import BaseAPIException
from shared.models.identity.auth_user import AuthUser
from shared.models.identity.user import User
from shared.models.platform.outbox import EventOutbox
from shared.models.tenancy.workspace import Workspace
from shared.rbac import ensure_workspace_system_roles
from shared.rbac.bootstrap import OWNER_ROLE_CHANGE_FORBIDDEN
from shared.testing.db import real_db_sessionmaker
from src.rpc import workspaces as workspaces_rpc
from src.services.admin.user import users as user_admin
from src.services.workspace.service import workspaces as workspace_service
from tests.test_audit_workspace import _handler

_TAG = itertools.count()


class _Case(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg/asyncpg cannot run on the Proactor loop here

    async def asyncSetUp(self) -> None:
        ctx = real_db_sessionmaker()
        self.Session = await ctx.__aenter__()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)

    async def _seed(self, session):
        """A workspace whose ``owner``, ``admin`` and plain ``target`` are members with those roles."""
        tag = f"wrc-{os.getpid()}-{next(_TAG)}"
        workspace = Workspace(slug=tag, name=tag)
        accounts = {
            name: AuthUser(email=f"{tag}-{name}@example.com", username=f"{tag}-{name}", hashed_password="x")
            for name in ("owner", "admin", "target")
        }
        session.add_all([workspace, *accounts.values()])
        await session.flush()
        session.add_all([User(name=f"{tag}-{name}", auth_user_id=account.id) for name, account in accounts.items()])
        await session.flush()
        roles = {name: role.id for name, role in (await ensure_workspace_system_roles(session, workspace.id)).items()}
        for name, account in accounts.items():
            role = "player" if name == "target" else name
            await workspace_service.add_member_with_roles(session, workspace.id, account.id, role_ids=[roles[role]])
        return workspace, roles, {name: account.id for name, account in accounts.items()}


class OwnerRoleGateTests(_Case):
    async def test_an_admin_can_neither_grant_nor_revoke_owner(self) -> None:
        async with self.Session() as s:
            workspace, roles, ids = await self._seed(s)
            admin = SimpleNamespace(id=ids["admin"], is_superuser=False)
            refused = (
                (ids["target"], [roles["owner"]]),  # grant
                (ids["owner"], [roles["admin"]]),  # revoke by update
                (ids["owner"], None),  # revoke by removal
            )
            for target, role_ids in refused:
                with self.subTest(target=target, role_ids=role_ids), self.assertRaises(BaseAPIException) as caught:
                    await workspace_service.ensure_owner_role_change_allowed(
                        s, workspace.id, admin, target_auth_user_id=target, role_ids=role_ids
                    )
                self.assertEqual(
                    (403, OWNER_ROLE_CHANGE_FORBIDDEN), (caught.exception.status_code, caught.exception.detail)
                )

            # A write that leaves ``owner`` where it is stays the workspace_member permission's call.
            for target, role_ids in (
                (ids["target"], [roles["referee"]]),
                (ids["target"], None),
                (ids["owner"], [roles["owner"], roles["admin"]]),
            ):
                await workspace_service.ensure_owner_role_change_allowed(
                    s, workspace.id, admin, target_auth_user_id=target, role_ids=role_ids
                )

    async def test_an_owner_and_a_superuser_can_grant_and_revoke_owner(self) -> None:
        async with self.Session() as s:
            workspace, roles, ids = await self._seed(s)
            for actor in (
                SimpleNamespace(id=ids["owner"], is_superuser=False),
                SimpleNamespace(id=ids["target"], is_superuser=True),  # holds no owner role here
            ):
                for target, role_ids in (
                    (ids["target"], [roles["owner"]]),
                    (ids["owner"], [roles["admin"]]),
                    (ids["owner"], None),
                ):
                    await workspace_service.ensure_owner_role_change_allowed(
                        s, workspace.id, actor, target_auth_user_id=target, role_ids=role_ids
                    )

    async def test_an_admin_asking_member_add_or_update_for_owner_gets_403(self) -> None:
        @asynccontextmanager
        async def _borrowed(session):
            yield session  # the handlers share the test's uncommitted session and leave it open

        async with self.Session() as s:
            workspace, _roles, ids = await self._seed(s)
            tag = f"wrc-new-{os.getpid()}-{next(_TAG)}"
            newcomer = AuthUser(email=f"{tag}@example.com", username=tag, hashed_password="x")
            s.add(newcomer)
            await s.flush()
            admin = {
                "user_id": ids["admin"],
                "username": "admin",
                "is_active": True,
                "is_superuser": False,
                "workspaces": [{"workspace_id": workspace.id, "slug": workspace.slug, "rbac_roles": ["admin"]}],
            }
            calls = (
                ("rpc.app.workspaces.member_add", {"payload": {"auth_user_id": newcomer.id, "role": "owner"}}),
                ("rpc.app.workspaces.member_update", {"auth_user_id": ids["target"], "payload": {"role": "owner"}}),
            )
            with patch.object(workspaces_rpc, "_SF", lambda: _borrowed(s)):
                for topic, data in calls:
                    envelope = await _handler(workspaces_rpc, topic)(
                        {"workspace_id": workspace.id, "identity": admin, **data}, MagicMock()
                    )
                    with self.subTest(topic=topic):
                        self.assertEqual(
                            {"ok": False, "error": {"code": "forbidden", "message": OWNER_ROLE_CHANGE_FORBIDDEN}},
                            envelope,
                        )

            roles = await workspace_service.get_member_workspace_roles(s, workspace.id, ids["target"])
            self.assertEqual(["player"], [role.name for role in roles])
            self.assertIsNone(await workspace_service.get_member(s, workspace.id, newcomer.id))


class DeleteStagesRbacChangeTests(_Case):
    async def _staged(self, session, since: int, auth_user_ids) -> list[tuple[str, int | None, list[int]]]:
        rows = await session.scalars(
            sa.select(EventOutbox)
            .where(EventOutbox.id > since, EventOutbox.routing_key == "workspace_member_changed")
            .order_by(EventOutbox.id)
        )
        return [
            (row.payload_json["change"], row.payload_json["workspace_id"], row.payload_json["auth_user_ids"])
            for row in rows
            if set(row.payload_json["auth_user_ids"]) & set(auth_user_ids)
        ]

    async def _since(self, session) -> int:
        return await session.scalar(sa.select(sa.func.coalesce(sa.func.max(EventOutbox.id), 0)))

    async def test_deleting_a_workspace_stages_every_member(self) -> None:
        async with self.Session() as s:
            workspace, _roles, ids = await self._seed(s)
            since = await self._since(s)

            await workspace_service.delete(s, workspace)

            self.assertEqual(
                [("workspace_deleted", workspace.id, sorted(ids.values()))],
                await self._staged(s, since, ids.values()),
            )

    async def test_deleting_a_linked_player_stages_its_account(self) -> None:
        async with self.Session() as s:
            _workspace, _roles, ids = await self._seed(s)
            player_id = await s.scalar(sa.select(User.id).where(User.auth_user_id == ids["target"]))
            since = await self._since(s)

            with patch.object(s, "commit", s.flush):  # keep the delete's transaction open to read it back
                await user_admin.delete_user(s, player_id)

            self.assertEqual([("player_deleted", None, [ids["target"]])], await self._staged(s, since, ids.values()))
