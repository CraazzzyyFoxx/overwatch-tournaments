"""PlayerSubRoleService: catalog goes through the repo; empty role is rejected."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from shared.core.errors import BaseAPIException
from shared.domain.player_sub_roles import build_subrole_catalog
from shared.rpc.player_sub_role import player_sub_role_entity
from shared.services.player_sub_role import PlayerSubRoleService


class _Row(SimpleNamespace):
    pass


class CatalogForWorkspaceTests(IsolatedAsyncioTestCase):
    async def test_reads_active_rows_through_the_repository(self) -> None:
        rows = [_Row(role="tank", slug="main_tank", label="Main Tank")]
        repo = SimpleNamespace(list_for_workspace=AsyncMock(return_value=rows))
        service = PlayerSubRoleService(sub_role_repo=repo)
        session = object()

        catalog = await service.catalog_for_workspace(session, 7)

        repo.list_for_workspace.assert_awaited_once_with(session, 7, only_active=True)
        self.assertEqual(build_subrole_catalog(rows), catalog)


class CreateSubRoleTests(IsolatedAsyncioTestCase):
    async def test_missing_role_is_400_before_any_write(self) -> None:
        repo = SimpleNamespace(create=AsyncMock(), get_by_slug=AsyncMock())
        service = PlayerSubRoleService(sub_role_repo=repo)

        with self.assertRaises(BaseAPIException) as raised:
            await service.create_sub_role(
                object(),
                SimpleNamespace(
                    workspace_id=1,
                    role="",
                    label="Main Tank",
                    slug=None,
                    description=None,
                    sort_order=0,
                    is_active=True,
                ),
            )

        self.assertEqual(400, raised.exception.status_code)
        repo.create.assert_not_called()
        repo.get_by_slug.assert_not_called()


class EntityConfigTests(IsolatedAsyncioTestCase):
    async def test_list_fn_reads_query_and_serializes_rows(self) -> None:
        cfg = player_sub_role_entity()
        row = SimpleNamespace(
            id=1,
            workspace_id=7,
            role="tank",
            slug="main_tank",
            label="Main Tank",
            description=None,
            sort_order=0,
            is_active=True,
        )
        session = object()
        with patch(
            "shared.rpc.player_sub_role.player_sub_role_service.list_sub_roles",
            AsyncMock(return_value=[row]),
        ) as listed:
            result = await cfg.list_fn(
                session,
                {"query": {"workspace_id": ["7"], "include_inactive": ["true"]}},
            )

        listed.assert_awaited_once_with(session, workspace_id=7, role=None, include_inactive=True)
        self.assertEqual("player_sub_role", cfg.entity)
        self.assertEqual("Main Tank", result[0]["label"])
