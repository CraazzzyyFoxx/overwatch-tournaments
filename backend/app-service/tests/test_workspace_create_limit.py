"""``WorkspaceService.ensure_create_limit`` + ``count_by_owner`` (workspace
self-service design ``docs/superpowers/specs/2026-08-26-workspace-self-service-design.md``
§4.4).

No DB: the guard is a lock + a count + a comparison, and the two things a wrong
implementation gets wrong silently are both visible from the emitted statements
-- that the actor's row is locked ``FOR UPDATE`` before the count (without it two
concurrent creates both read ``count == 0`` and both succeed), and that the count
goes through ``Workspace.owner_id`` alone rather than joining the RBAC ``owner``
role. The concurrency behaviour those two facts buy is a property of Postgres row
locking, not of this code, so it is pinned by the statement rather than by racing
two real sessions.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from shared.repository import WorkspaceRepository
from shared.schemas.settings import WorkspaceCreationConfig

workspace_service = importlib.import_module("src.services.workspace.service")
workspaces = workspace_service.workspaces


def _actor(*, is_superuser: bool = False, auth_user_id: int = 42) -> SimpleNamespace:
    return SimpleNamespace(id=auth_user_id, username="ada", is_superuser=is_superuser)


class _Session:
    """Records every statement handed to ``scalar``, in order."""

    def __init__(self) -> None:
        self.statements: list[object] = []

    async def scalar(self, statement, *args, **kwargs):
        self.statements.append(statement)
        return None

    def sql(self) -> list[str]:
        return [str(statement) for statement in self.statements]


class EnsureCreateLimitTests(IsolatedAsyncioTestCase):
    async def _ensure(self, *, owned: int, limit: int | None = None, user=None):
        session = _Session()
        config = WorkspaceCreationConfig() if limit is None else WorkspaceCreationConfig(max_owned_per_user=limit)
        count = AsyncMock(return_value=owned)
        with (
            patch.object(workspace_service.settings_provider, "get_workspace_creation_config", AsyncMock(return_value=config)),
            patch.object(workspaces.workspace_repo, "count_by_owner", count),
        ):
            await workspaces.ensure_create_limit(session, user or _actor())
        return session, count

    async def test_allows_an_actor_who_owns_nothing_under_the_default_limit(self) -> None:
        session, count = await self._ensure(owned=0)

        count.assert_awaited_once_with(session, owner_id=42)

    async def test_rejects_an_actor_already_at_the_default_limit_of_one(self) -> None:
        with self.assertRaises(workspace_service.HTTPException) as ctx:
            await self._ensure(owned=1)

        self.assertEqual(403, ctx.exception.status_code)
        self.assertEqual("workspace_create_limit_reached", ctx.exception.detail)

    async def test_a_raised_settings_threshold_lets_a_second_workspace_through(self) -> None:
        await self._ensure(owned=1, limit=2)

    async def test_rejects_at_the_raised_threshold_too(self) -> None:
        with self.assertRaises(workspace_service.HTTPException) as ctx:
            await self._ensure(owned=2, limit=2)

        self.assertEqual(403, ctx.exception.status_code)

    async def test_locks_the_actors_own_auth_user_row_before_counting(self) -> None:
        """The lock is the whole mechanism: it serializes two concurrent creates
        from one actor onto one row, so exactly one of them sees ``count == 0``."""
        session, count = await self._ensure(owned=0)

        self.assertEqual(1, len(session.statements))
        locked = session.sql()[0]
        self.assertIn("FOR UPDATE", locked)
        self.assertIn('auth."user"', locked)
        count.assert_awaited_once()

    async def test_superuser_is_exempt_and_never_issues_a_query(self) -> None:
        session = _Session()
        count = AsyncMock()
        with (
            patch.object(workspace_service.settings_provider, "get_workspace_creation_config", AsyncMock()) as config,
            patch.object(workspaces.workspace_repo, "count_by_owner", count),
        ):
            await workspaces.ensure_create_limit(session, _actor(is_superuser=True))

        self.assertEqual([], session.statements)
        count.assert_not_awaited()
        config.assert_not_awaited()


class CountByOwnerTests(IsolatedAsyncioTestCase):
    async def test_counts_the_owner_id_column_and_never_joins_the_rbac_role(self) -> None:
        """Regression guard for the design's central correction: RBAC ``owner``
        is a mutable permission grant (co-owners, reassignment, revocation), so
        counting through ``auth.user_roles`` both double-counts co-owned
        workspaces and is gameable by handing the role away."""
        session = _Session()

        self.assertEqual(0, await WorkspaceRepository().count_by_owner(session, owner_id=42))

        sql = session.sql()[0]
        self.assertIn("count(workspace.id)", sql)
        self.assertIn("workspace.owner_id", sql)
        self.assertNotIn("user_roles", sql)
        self.assertNotIn("JOIN", sql)
