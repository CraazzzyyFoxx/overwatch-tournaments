from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

workspace_service = importlib.import_module("src.services.workspace.service")
workspaces = workspace_service.workspaces


class WorkspaceServiceTests(IsolatedAsyncioTestCase):
    async def test_create_uses_system_default_division_grid_version_when_none_is_provided(self) -> None:
        session = SimpleNamespace(add=Mock(), flush=AsyncMock())

        with patch.object(
            workspace_service,
            "get_default_division_grid_version_id",
            AsyncMock(return_value=77),
        ) as get_default_version_id:
            workspace = await workspaces.create(
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

    async def test_update_rejects_default_version_changes_outside_activation_flow(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = SimpleNamespace(id=4, default_division_grid_version_id=12)

        with self.assertRaises(Exception) as caught:
            await workspaces.update(
                session,
                workspace,
                {"default_division_grid_version_id": 77},
            )

        self.assertEqual(400, getattr(caught.exception, "status_code", None))
        session.flush.assert_not_awaited()

    async def test_update_rejects_default_version_owned_by_another_workspace(self) -> None:
        session = SimpleNamespace(scalar=AsyncMock(return_value=9))

        with self.assertRaises(Exception) as caught:
            await workspaces.validate_default_division_grid_version(
                session,
                workspace_id=4,
                version_id=55,
            )

        self.assertEqual(400, getattr(caught.exception, "status_code", None))

    async def test_update_member_roles_refreshes_member_after_flush(self) -> None:
        # Regression: ``updated_at`` (onupdate=func.now()) is server-computed and
        # gets expired by the UPDATE flush. Without refreshing it inside the async
        # context, the later sync read of ``member.updated_at`` triggers a lazy
        # load outside the greenlet -> sqlalchemy.exc.MissingGreenlet (HTTP 500).
        session = SimpleNamespace(flush=AsyncMock(), refresh=AsyncMock())
        member = SimpleNamespace(id=14, player_id=99, workspace_id=2)

        with (
            patch.object(
                workspaces,
                "get_member_auth_user_id",
                AsyncMock(return_value=22),
            ) as get_auth_user_id,
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
        ):
            result = await workspaces.update_member_roles(session, member, role_ids=[5])

        self.assertIs(result, member)
        get_auth_user_id.assert_awaited_once_with(session, member)
        replace_roles.assert_awaited_once_with(session, user_id=22, workspace_id=2, role_ids=[5])
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(member)

    async def test_add_member_with_roles_refreshes_member_after_flush(self) -> None:
        session = SimpleNamespace(flush=AsyncMock(), refresh=AsyncMock())
        member = SimpleNamespace(id=14, player_id=99, workspace_id=2)

        with (
            patch.object(
                workspaces,
                "add_member",
                AsyncMock(return_value=member),
            ) as add_member,
            patch.object(
                workspace_service,
                "replace_user_workspace_roles",
                AsyncMock(),
            ) as replace_roles,
        ):
            result = await workspaces.add_member_with_roles(
                session,
                2,
                22,
                role_ids=[5],
            )

        self.assertIs(result, member)
        add_member.assert_awaited_once_with(session, 2, 22)
        replace_roles.assert_awaited_once_with(session, user_id=22, workspace_id=2, role_ids=[5])
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(member)

    async def test_get_member_auth_user_id_resolves_via_player(self) -> None:
        member = SimpleNamespace(id=14, player_id=99, workspace_id=2)
        player = SimpleNamespace(id=99, auth_user_id=22)
        session = SimpleNamespace()

        with patch.object(
            workspaces.user_repo,
            "get",
            AsyncMock(return_value=player),
        ) as get_player:
            auth_user_id = await workspaces.get_member_auth_user_id(session, member)

        self.assertEqual(22, auth_user_id)
        get_player.assert_awaited_once_with(session, 99)

    async def test_get_member_auth_user_id_raises_when_unlinked(self) -> None:
        member = SimpleNamespace(id=14, player_id=99, workspace_id=2)
        session = SimpleNamespace()

        with patch.object(
            workspaces.user_repo,
            "get",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(workspace_service.HTTPException):
                await workspaces.get_member_auth_user_id(session, member)

    async def test_add_member_resolves_player_id_from_auth_user_id(self) -> None:
        auth_user = SimpleNamespace(id=22, username="staff", email="s@ex.com")
        session = SimpleNamespace()
        player = SimpleNamespace(id=99, auth_user_id=22)
        created_member = SimpleNamespace(id=14, player_id=99, workspace_id=2)

        with (
            patch.object(
                workspace_service,
                "ensure_workspace_system_roles",
                AsyncMock(),
            ),
            patch.object(
                workspaces.auth_user_repo,
                "get",
                AsyncMock(return_value=auth_user),
            ),
            patch.object(
                workspaces.user_repo,
                "ensure_for_auth_user",
                AsyncMock(return_value=player),
            ) as ensure_for_auth_user,
            patch.object(
                workspace_service,
                "get_or_create_workspace_member",
                AsyncMock(return_value=created_member),
            ) as get_or_create,
        ):
            result = await workspaces.add_member(session, 2, 22)

        self.assertIs(result, created_member)
        ensure_for_auth_user.assert_awaited_once_with(session, auth_user_id=22, name_hint="staff")
        get_or_create.assert_awaited_once_with(session, workspace_id=2, player_id=99)

    async def test_add_member_provisions_player_when_none_linked(self) -> None:
        # Legacy auth user with no players.user: add_member now provisions a bare
        # player on demand (via ensure_for_auth_user) instead of raising 500.
        auth_user = SimpleNamespace(id=22, username="staff", email="s@ex.com")
        session = SimpleNamespace()
        provisioned = SimpleNamespace(id=77, auth_user_id=22)
        created_member = SimpleNamespace(id=14, player_id=77, workspace_id=2)

        with (
            patch.object(
                workspace_service,
                "ensure_workspace_system_roles",
                AsyncMock(),
            ),
            patch.object(
                workspaces.auth_user_repo,
                "get",
                AsyncMock(return_value=auth_user),
            ),
            patch.object(
                workspaces.user_repo,
                "ensure_for_auth_user",
                AsyncMock(return_value=provisioned),
            ) as ensure_for_auth_user,
            patch.object(
                workspace_service,
                "get_or_create_workspace_member",
                AsyncMock(return_value=created_member),
            ) as get_or_create,
        ):
            result = await workspaces.add_member(session, 2, 22)

        self.assertIs(result, created_member)
        ensure_for_auth_user.assert_awaited_once_with(session, auth_user_id=22, name_hint="staff")
        get_or_create.assert_awaited_once_with(session, workspace_id=2, player_id=77)

    async def test_resolve_member_role_ids_prefers_explicit_ids(self) -> None:
        session = SimpleNamespace()
        with (
            patch.object(workspace_service, "ensure_workspace_system_roles", AsyncMock()) as ensure,
            patch.object(workspace_service, "get_workspace_system_role", AsyncMock()) as get_role,
        ):
            result = await workspaces.resolve_member_role_ids(session, 2, role_ids=[9, 8], role_name="admin")
        ensure.assert_awaited_once_with(session, 2)
        get_role.assert_not_awaited()
        self.assertEqual([9, 8], result)

    async def test_resolve_member_role_ids_looks_up_named_system_role(self) -> None:
        session = SimpleNamespace()
        role = SimpleNamespace(id=4)
        with (
            patch.object(workspace_service, "ensure_workspace_system_roles", AsyncMock()),
            patch.object(workspace_service, "get_workspace_system_role", AsyncMock(return_value=role)) as get_role,
        ):
            result = await workspaces.resolve_member_role_ids(session, 2, role_ids=None, role_name=None)
        get_role.assert_awaited_once_with(session, 2, "player")
        self.assertEqual([4], result)


class WorkspaceGetAllVisibilityTests(IsolatedAsyncioTestCase):
    """``get_all`` serves three scopes. ``public`` is the home-page directory:
    ``is_hidden`` and ``unverified`` are dropped for EVERY caller, membership
    and ``is_superuser`` included. ``admin`` is the management list (superuser:
    everything, else own memberships only) and ``all`` unions that with the
    directory for the workspace switcher."""

    def _workspaces(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(id=1, is_hidden=False, verification_status="trusted"),
            SimpleNamespace(id=2, is_hidden=True, verification_status="trusted"),
            SimpleNamespace(id=3, is_hidden=False, verification_status="verified"),
            SimpleNamespace(id=4, is_hidden=False, verification_status="unverified"),
        ]

    async def _get_all(self, user, scope: str = "public") -> list[int]:
        session = SimpleNamespace()
        with patch.object(workspaces.workspace_repo, "list_ordered", AsyncMock(return_value=self._workspaces())):
            result = await workspaces.get_all(session, user=user, scope=scope)
        return [w.id for w in result]

    async def test_anonymous_sees_non_hidden_verified_and_trusted_workspaces(self) -> None:
        self.assertEqual([1, 3], await self._get_all(None))

    async def test_non_member_is_filtered_exactly_like_an_anonymous_viewer(self) -> None:
        user = SimpleNamespace(is_superuser=False, get_workspace_ids=Mock(return_value=[99]))

        self.assertEqual([1, 3], await self._get_all(user))

    async def test_unverified_stays_out_of_the_public_directory(self) -> None:
        """``unverified`` is the only tier the directory refuses: it is the
        default a self-service workspace is born at, before any superuser has
        looked at it."""
        user = SimpleNamespace(is_superuser=False, get_workspace_ids=Mock(return_value=[]))

        self.assertNotIn(4, await self._get_all(user))

    async def test_member_does_not_see_their_own_unverified_workspace_in_the_directory(self) -> None:
        """The directory is one shared surface: a member's own hidden or
        ``unverified`` workspace is reachable by slug and through the switcher
        (``scope=all``), never on the home page."""
        user = SimpleNamespace(is_superuser=False, get_workspace_ids=Mock(return_value=[2, 4]))

        self.assertEqual([1, 3], await self._get_all(user))

    async def test_superuser_gets_the_same_directory_as_a_visitor(self) -> None:
        """The whole point of the 2026-09-07 revision: an operator browsing the
        home page must not be shown workspaces nobody else can see."""
        user = SimpleNamespace(is_superuser=True, get_workspace_ids=Mock(return_value=[]))

        self.assertEqual([1, 3], await self._get_all(user))

    async def test_all_scope_adds_the_members_own_hidden_and_unverified_workspaces(self) -> None:
        user = SimpleNamespace(is_superuser=False, get_workspace_ids=Mock(return_value=[2, 4]))

        self.assertEqual([1, 2, 3, 4], await self._get_all(user, "all"))

    async def test_all_scope_for_a_superuser_is_every_workspace(self) -> None:
        user = SimpleNamespace(is_superuser=True, get_workspace_ids=Mock(return_value=[]))

        self.assertEqual([1, 2, 3, 4], await self._get_all(user, "all"))

    async def test_admin_scope_is_memberships_only_not_the_directory(self) -> None:
        """The management table must not pad a workspace admin's rows with
        every public workspace they have no business editing."""
        user = SimpleNamespace(is_superuser=False, get_workspace_ids=Mock(return_value=[4]))

        self.assertEqual([4], await self._get_all(user, "admin"))

    async def test_admin_scope_for_a_superuser_is_every_workspace(self) -> None:
        """Including ``unverified`` ones -- this is the list a superuser
        verifies workspaces from, so the tier gate must not reach it."""
        user = SimpleNamespace(is_superuser=True, get_workspace_ids=Mock(return_value=[]))

        self.assertEqual([1, 2, 3, 4], await self._get_all(user, "admin"))

    async def test_admin_scope_is_empty_for_an_anonymous_caller(self) -> None:
        self.assertEqual([], await self._get_all(None, "admin"))
