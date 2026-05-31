from __future__ import annotations

import importlib
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

workspace_service = importlib.import_module("src.services.workspace.service")


class WorkspaceServiceTests(IsolatedAsyncioTestCase):
    async def test_create_uses_system_default_division_grid_version_when_none_is_provided(self) -> None:
        session = SimpleNamespace(add=Mock(), flush=AsyncMock())

        with patch.object(
            workspace_service,
            "get_default_division_grid_version_id",
            AsyncMock(return_value=77),
        ) as get_default_version_id:
            workspace = await workspace_service.create(
                session,
                slug="homies-family",
                name="Homies Family",
                description=None,
                icon_url=None,
                default_division_grid_version_id=None,
            )

        self.assertEqual(77, workspace.default_division_grid_version_id)
        get_default_version_id.assert_awaited_once_with(session)
        session.add.assert_called_once_with(workspace)
        session.flush.assert_awaited_once()

    async def test_update_uses_system_default_division_grid_version_when_none_is_provided(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = SimpleNamespace(
            id=4,
            default_division_grid_version_id=12,
            name="Homies Family",
            description=None,
            icon_url=None,
        )

        with (
            patch.object(
                workspace_service,
                "get_default_division_grid_version_id",
                AsyncMock(return_value=77),
            ) as get_default_version_id,
            patch.object(
                workspace_service.division_grid_cache,
                "invalidate_workspace",
                AsyncMock(),
            ) as invalidate_workspace,
        ):
            result = await workspace_service.update(
                session,
                workspace,
                {"default_division_grid_version_id": None},
            )

        self.assertIs(result, workspace)
        self.assertEqual(77, workspace.default_division_grid_version_id)
        get_default_version_id.assert_awaited_once_with(session)
        invalidate_workspace.assert_awaited_once_with(4)
        session.flush.assert_awaited_once()

    async def test_update_member_roles_refreshes_member_after_flush(self) -> None:
        # Regression: ``updated_at`` (onupdate=func.now()) is server-computed and
        # gets expired by the UPDATE flush. Without refreshing it inside the async
        # context, the later sync read of ``member.updated_at`` triggers a lazy
        # load outside the greenlet -> sqlalchemy.exc.MissingGreenlet (HTTP 500).
        session = SimpleNamespace(flush=AsyncMock(), refresh=AsyncMock())
        member = SimpleNamespace(id=14, auth_user_id=22, workspace_id=2, role="member")

        with (
            patch.object(
                workspace_service,
                "user_has_only_workspace_owner_role",
                AsyncMock(return_value=False),
            ),
            patch.object(
                workspace_service,
                "replace_user_workspace_roles",
                AsyncMock(),
            ) as replace_roles,
            patch.object(
                workspace_service,
                "legacy_workspace_role_name_for_user",
                AsyncMock(return_value="admin"),
            ),
        ):
            result = await workspace_service.update_member_roles(
                session, member, role_ids=[5]
            )

        self.assertIs(result, member)
        self.assertEqual("admin", member.role)
        replace_roles.assert_awaited_once()
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(member)

    async def test_add_member_with_roles_refreshes_member_after_flush(self) -> None:
        session = SimpleNamespace(flush=AsyncMock(), refresh=AsyncMock())
        member = SimpleNamespace(id=14, auth_user_id=22, workspace_id=2, role="member")

        with (
            patch.object(
                workspace_service,
                "add_member",
                AsyncMock(return_value=member),
            ),
            patch.object(
                workspace_service,
                "replace_user_workspace_roles",
                AsyncMock(),
            ),
            patch.object(
                workspace_service,
                "legacy_workspace_role_name_for_user",
                AsyncMock(return_value="admin"),
            ),
        ):
            result = await workspace_service.add_member_with_roles(
                session,
                2,
                22,
                role_ids=[5],
                legacy_role="member",
            )

        self.assertIs(result, member)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(member)
