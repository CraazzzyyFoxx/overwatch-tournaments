"""Authorization + tenant scoping for the subscription-collection admin RPCs.

These handlers used to demand the *global* ``admin`` role, which refused a
workspace owner on their own workspace's collection health — a role check
standing in for RBAC. They now gate on ``subscription.read`` /
``subscription.update``, where ``workspace_id`` is simultaneously the
authorization scope and the row filter.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))


from shared.core.errors import BaseAPIException  # noqa: E402
from shared.rbac.catalog import PERMISSION_CATALOG, permission_names_for_workspace_role  # noqa: E402
from shared.services.settings_provider import settings_provider  # noqa: E402

WORKSPACE = 7
OTHER_WORKSPACE = 9


def _data(identity: dict, *, workspace_id: int | None = WORKSPACE) -> dict:
    """The gateway envelope: query params always arrive as lists of strings."""
    data: dict = {"identity": identity}
    if workspace_id is not None:
        data["query"] = {"workspace_id": [str(workspace_id)]}
    return data


def _workspace_member(*, roles: list[str], permissions: list[dict[str, str]] | None = None) -> dict:
    return {
        "user_id": 42,
        "roles": [],
        "permissions": [],
        "workspaces": [
            {
                "workspace_id": WORKSPACE,
                "rbac_roles": roles,
                "rbac_permissions": permissions or [],
            }
        ],
    }


#: What identity-service puts in the token for a workspace owner: the `owner`
#: system role, whose only grant is the `admin.*` wildcard.
OWNER = _workspace_member(roles=["owner"], permissions=[{"resource": "*", "action": "*"}])


class CatalogTests(TestCase):
    def test_subscription_permissions_are_in_the_catalog(self) -> None:
        pairs = {(p.resource, p.action) for p in PERMISSION_CATALOG}
        self.assertIn(("subscription", "read"), pairs)
        self.assertIn(("subscription", "update"), pairs)

    def test_workspace_admin_role_grants_them(self) -> None:
        # `owner` is the `admin.*` wildcard; `admin` is an enumerated grant list
        # and must name the new permissions explicitly or the tab 403s for them.
        granted = permission_names_for_workspace_role("admin")
        self.assertIn("subscription.read", granted)
        self.assertIn("subscription.update", granted)

    def test_plain_member_does_not_get_collection_health(self) -> None:
        self.assertNotIn("subscription.read", permission_names_for_workspace_role("member"))


class AuthorizeTests(TestCase):
    def _authorize(self, data: dict, action: str = "read") -> int | None:
        from src.rpc import subscription

        return subscription._authorize(data, action)

    def test_workspace_owner_is_allowed_and_scoped(self) -> None:
        # The regression this whole change exists for: an owner holds no global
        # role, so the old `has_role("admin")` gate answered 403.
        self.assertEqual(self._authorize(_data(OWNER)), WORKSPACE)
        self.assertEqual(self._authorize(_data(OWNER), "update"), WORKSPACE)

    def test_explicit_permission_without_any_role_is_enough(self) -> None:
        reader = _workspace_member(roles=[], permissions=[{"resource": "subscription", "action": "read"}])
        self.assertEqual(self._authorize(_data(reader)), WORKSPACE)
        with self.assertRaises(BaseAPIException) as ctx:
            self._authorize(_data(reader), "update")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_other_workspace_is_refused(self) -> None:
        with self.assertRaises(BaseAPIException) as ctx:
            self._authorize(_data(OWNER, workspace_id=OTHER_WORKSPACE))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_workspace_scope_cannot_widen_itself_by_dropping_the_param(self) -> None:
        # No workspace_id means "every workspace", so it needs the GLOBAL grant —
        # otherwise an owner could read every tenant's history by omitting it.
        with self.assertRaises(BaseAPIException) as ctx:
            self._authorize(_data(OWNER, workspace_id=None))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_global_holder_gets_the_cross_workspace_scope(self) -> None:
        operator = {
            "user_id": 1,
            "roles": [],
            "permissions": [{"resource": "subscription", "action": "read"}],
            "workspaces": [],
        }
        self.assertIsNone(self._authorize(_data(operator, workspace_id=None)))

    def test_superuser_keeps_both(self) -> None:
        root = {"user_id": 1, "is_superuser": True, "roles": [], "permissions": [], "workspaces": []}
        self.assertIsNone(self._authorize(_data(root, workspace_id=None)))
        self.assertEqual(self._authorize(_data(root)), WORKSPACE)

    def test_inactive_user_is_refused_before_the_permission_check(self) -> None:
        inactive = dict(OWNER, is_active=False)
        with self.assertRaises(BaseAPIException) as ctx:
            self._authorize(_data(inactive))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_deny_overlay_beats_the_workspace_wildcard(self) -> None:
        denied = dict(OWNER, denies=[{"resource": "subscription", "action": "update"}])
        self.assertEqual(self._authorize(_data(denied)), WORKSPACE)
        with self.assertRaises(BaseAPIException):
            self._authorize(_data(denied), "update")


class ScopingTests(IsolatedAsyncioTestCase):
    """The scope reaches the SQL, not just the 403."""

    #: The column name alone appears in every SELECT list, so match the predicate.
    WORKSPACE_PREDICATE = "check_log.workspace_id = "

    @staticmethod
    def _captured_sql(session) -> str:
        return " ".join(str(call.args[0]) for call in session.execute.await_args_list)

    @staticmethod
    def _empty_session():
        from unittest.mock import AsyncMock, MagicMock

        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)
        return session

    async def test_check_log_filters_by_the_authorized_workspace(self) -> None:
        from src.services.subscription_collection import admin

        session = self._empty_session()
        await admin.list_check_log(session, workspace_id=WORKSPACE)
        self.assertIn(self.WORKSPACE_PREDICATE, self._captured_sql(session))

    async def test_check_log_unscoped_query_has_no_workspace_predicate(self) -> None:
        from src.services.subscription_collection import admin

        session = self._empty_session()
        await admin.list_check_log(session)
        self.assertNotIn(self.WORKSPACE_PREDICATE, self._captured_sql(session))

    async def test_user_collection_filters_by_the_authorized_workspace(self) -> None:
        from unittest.mock import AsyncMock, patch

        from src.services.subscription_collection import admin

        session = self._empty_session()
        with patch.object(admin, "_auth_user_id_for_player", AsyncMock(return_value=100)):
            await admin.get_user_collection_status(session, 5, workspace_id=WORKSPACE)
        self.assertIn("entitlement.workspace_id = ", self._captured_sql(session))

    async def test_single_player_recheck_skips_other_workspaces_rules(self) -> None:
        from unittest.mock import AsyncMock, patch

        from src.services.subscription_collection import admin

        resolver = AsyncMock()
        resolver.resolve = AsyncMock(return_value={100: {"boosty": object()}})
        session = AsyncMock()

        with (
            patch.object(admin, "_auth_user_id_for_player", AsyncMock(return_value=100)),
            patch.object(
                admin,
                "_requirements_for_user",
                AsyncMock(return_value=[(WORKSPACE, ("boosty",)), (OTHER_WORKSPACE, ("twitch",))]),
            ),
            patch.object(admin, "build_resolver", return_value=resolver),
        ):
            checked = await admin.trigger_collection(session, user_id=5, workspace_id=WORKSPACE)

        self.assertEqual(checked, 1)
        resolver.resolve.assert_awaited_once()
        self.assertEqual(resolver.resolve.await_args.kwargs["workspace_id"], WORKSPACE)

    async def test_sweep_passes_the_scope_down_to_the_tournament_lookup(self) -> None:
        from unittest.mock import AsyncMock, patch

        from shared.schemas.settings import SubscriptionCollectionConfig
        from src.services.subscription_collection import admin

        sweep = AsyncMock(return_value=3)
        with (
            patch.object(
                settings_provider,
                "get_subscription_collection_config",
                AsyncMock(return_value=SubscriptionCollectionConfig(enabled=True)),
            ),
            patch.object(admin.service, "collect_subscriptions_for_active_tournaments", sweep),
        ):
            checked = await admin.trigger_collection(AsyncMock(), workspace_id=WORKSPACE)

        self.assertEqual(checked, 3)
        self.assertEqual(sweep.await_args.kwargs["workspace_id"], WORKSPACE)

    async def test_tournament_lookup_filters_by_workspace(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from src.services.subscription_collection import service

        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        await service.find_tournaments_requiring_subscriptions(session, workspace_id=WORKSPACE)
        self.assertIn("tournament.workspace_id", str(session.execute.await_args.args[0]))
