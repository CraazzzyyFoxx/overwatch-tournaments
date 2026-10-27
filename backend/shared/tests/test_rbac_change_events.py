"""Every shared writer of memberships or workspace role grants stages the RBAC-change event in its own transaction.

identity caches a user's RBAC payload for minutes and drops it only on a ``WorkspaceMemberChangedEvent``, so a writer
that commits without staging one leaves the payload stale. Nothing here commits: each event row is read back through
the session that made the write, and the session closes with a rollback. Needs the test Postgres; skips otherwise.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.models.identity.auth_user import AuthUser
from shared.models.identity.user import User
from shared.models.platform.outbox import EventOutbox
from shared.models.tenancy.workspace import Workspace
from shared.rbac import assign_workspace_system_role, ensure_workspace_system_roles, get_workspace_system_role
from shared.repository import UserRoleRepository, get_or_create_workspace_member
from shared.repository.workspace import insert_missing_workspace_members
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres

_TAG = itertools.count()


class RbacChangeEventTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg/asyncpg cannot run on the Proactor loop here

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        engine = create_test_async_engine()
        self.addAsyncCleanup(engine.dispose)
        self.Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _seed(self, session, players: int = 1) -> tuple[Workspace, list[int], list[User]]:
        tag = f"rce-{os.getpid()}-{next(_TAG)}"
        workspace = Workspace(slug=tag, name=tag)
        accounts = [
            AuthUser(email=f"{tag}-{i}@example.com", username=f"{tag}-{i}", hashed_password="x") for i in range(players)
        ]
        session.add_all([workspace, *accounts])
        await session.flush()
        linked = [User(name=f"{tag}-{i}", auth_user_id=account.id) for i, account in enumerate(accounts)]
        session.add_all(linked)
        await session.flush()
        return workspace, [account.id for account in accounts], linked

    async def _since(self, session) -> int:
        return await session.scalar(sa.select(sa.func.coalesce(sa.func.max(EventOutbox.id), 0)))

    async def _staged(self, session, since: int, auth_user_ids: list[int]) -> list[tuple[str, int | None, list[int]]]:
        """The member-changed events staged after ``since`` that name any of ``auth_user_ids``."""
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

    async def test_admission_and_revival_stage_added_and_an_idempotent_hit_stages_nothing(self) -> None:
        async with self.Session() as s:
            workspace, [account], [player] = await self._seed(s)
            since = await self._since(s)

            member = await get_or_create_workspace_member(s, workspace_id=workspace.id, player_id=player.id)
            await get_or_create_workspace_member(s, workspace_id=workspace.id, player_id=player.id)
            member.removed_at = datetime.now(UTC)
            await s.flush()
            await get_or_create_workspace_member(s, workspace_id=workspace.id, player_id=player.id)

            self.assertEqual([("added", workspace.id, [account])] * 2, await self._staged(s, since, [account]))

    async def test_a_role_grant_stages_only_when_it_grants(self) -> None:
        async with self.Session() as s:
            workspace, [account], _ = await self._seed(s)
            since = await self._since(s)

            for _ in range(2):
                await assign_workspace_system_role(s, user_id=account, workspace_id=workspace.id, role_name="player")

            self.assertEqual([("roles_changed", workspace.id, [account])], await self._staged(s, since, [account]))

    async def test_the_bulk_role_autofill_stages_every_user_it_granted(self) -> None:
        async with self.Session() as s:
            workspace, accounts, players = await self._seed(s, players=2)
            await ensure_workspace_system_roles(s, workspace.id)
            # Bare anchors: no role is granted with them.
            await insert_missing_workspace_members(s, [(workspace.id, player.id) for player in players])
            since = await self._since(s)

            granted = await UserRoleRepository().grant_missing_workspace_member_role(s, workspace.id)
            again = await UserRoleRepository().grant_missing_workspace_member_role(s, workspace.id)

            self.assertEqual((2, 0), (granted, again))
            self.assertEqual(
                [("roles_changed", workspace.id, sorted(accounts))], await self._staged(s, since, accounts)
            )

    async def test_permission_reconciliation_stages_the_holders_of_the_changed_role(self) -> None:
        async with self.Session() as s:
            workspace, [holder, bystander], _ = await self._seed(s, players=2)
            await assign_workspace_system_role(s, user_id=holder, workspace_id=workspace.id, role_name="player")
            await assign_workspace_system_role(s, user_id=bystander, workspace_id=workspace.id, role_name="admin")
            player_role = await get_workspace_system_role(s, workspace.id, "player")
            admin_role = await get_workspace_system_role(s, workspace.id, "admin")
            # Drift the player role away from the catalog, as a catalog release does from the other side.
            extra = next(p for p in admin_role.permissions if p not in player_role.permissions)
            player_role.permissions = [*player_role.permissions, extra]
            await s.flush()
            since = await self._since(s)

            await ensure_workspace_system_roles(s, workspace.id)
            await ensure_workspace_system_roles(s, workspace.id)  # back in sync: nothing more to say

            self.assertEqual(
                [("role_permissions_changed", workspace.id, [holder])],
                await self._staged(s, since, [holder, bystander]),
            )
