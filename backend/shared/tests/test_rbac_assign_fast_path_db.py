"""Granting a role in an already seeded workspace never hydrates the permission catalog.

Every self-registration grants ``player``; the full seeding loads all ~131 ``Permission``
rows and every system role's grants just to find one role id. Nothing commits: the
session closes with a rollback. Needs the test Postgres; skips otherwise.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.models.identity.auth_user import AuthUser
from shared.models.identity.rbac import Permission, user_roles
from shared.models.tenancy.workspace import Workspace
from shared.rbac import assign_workspace_system_role, ensure_workspace_system_roles
from shared.rbac.catalog import permission_names_for_workspace_role
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres

_TAG = itertools.count()


class AssignFastPathTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg/asyncpg cannot run on the Proactor loop here

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        engine = create_test_async_engine()
        self.addAsyncCleanup(engine.dispose)
        self.Session = async_sessionmaker(engine, expire_on_commit=False)

    async def test_a_seeded_workspace_grants_without_loading_the_catalog(self) -> None:
        async with self.Session() as s:
            tag = f"rbacfast-{os.getpid()}-{next(_TAG)}"
            workspace = Workspace(slug=tag, name=tag)
            account = AuthUser(email=f"{tag}@example.com", username=tag, hashed_password="x")
            s.add_all([workspace, account])
            await s.flush()
            workspace_id, user_id = workspace.id, account.id
            await ensure_workspace_system_roles(s, workspace_id)
            s.expunge_all()  # from here on the session holds only what the grant loads

            role = await assign_workspace_system_role(s, user_id=user_id, workspace_id=workspace_id, role_name="player")

            loaded = {obj.name for obj in s.identity_map.values() if isinstance(obj, Permission)}
            self.assertEqual(set(permission_names_for_workspace_role("player")), loaded)
            granted = await s.scalars(sa.select(user_roles.c.role_id).where(user_roles.c.user_id == user_id))
            self.assertIn(role.id, list(granted))
