"""Authorization + tenant scoping for the rank-collection admin RPCs.

These handlers used to demand the *global* ``admin`` role, which refused a
workspace owner on their own roster's collection health. They now gate on
``rank.read`` / ``rank.update``, where ``workspace_id`` is simultaneously the
authorization scope and the row filter.

Rank rows carry no workspace column: a battle tag belongs to a player and a
player reaches a workspace through ``workspace_member``, so every scoped query
goes through that subquery (``service.workspace_account_ids``).
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


#: What identity-service puts in the token for a workspace owner: the `owner`
#: system role, whose only grant is the `admin.*` wildcard.
OWNER = {
    "user_id": 42,
    "roles": [],
    "permissions": [],
    "workspaces": [
        {
            "workspace_id": WORKSPACE,
            "rbac_roles": ["owner"],
            "rbac_permissions": [{"resource": "*", "action": "*"}],
        }
    ],
}


class CatalogTests(TestCase):
    def test_rank_permissions_are_in_the_catalog(self) -> None:
        pairs = {(p.resource, p.action) for p in PERMISSION_CATALOG}
        self.assertIn(("rank", "read"), pairs)
        self.assertIn(("rank", "update"), pairs)

    def test_workspace_admin_role_grants_them(self) -> None:
        granted = permission_names_for_workspace_role("admin")
        self.assertIn("rank.read", granted)
        self.assertIn("rank.update", granted)

    def test_plain_member_does_not_get_collection_health(self) -> None:
        self.assertNotIn("rank.read", permission_names_for_workspace_role("member"))


class AuthorizeTests(TestCase):
    def _authorize(self, data: dict, action: str = "read") -> int | None:
        from src.rpc import rank

        return rank._authorize(data, action)

    def test_workspace_owner_is_allowed_and_scoped(self) -> None:
        # The regression this change exists for: an owner holds no global role,
        # so the old `has_role("admin")` gate answered 403.
        self.assertEqual(self._authorize(_data(OWNER)), WORKSPACE)
        self.assertEqual(self._authorize(_data(OWNER), "update"), WORKSPACE)

    def test_explicit_permission_without_any_role_is_enough(self) -> None:
        reader = {
            "user_id": 43,
            "roles": [],
            "permissions": [],
            "workspaces": [
                {
                    "workspace_id": WORKSPACE,
                    "rbac_roles": [],
                    "rbac_permissions": [{"resource": "rank", "action": "read"}],
                }
            ],
        }
        self.assertEqual(self._authorize(_data(reader)), WORKSPACE)
        with self.assertRaises(BaseAPIException) as ctx:
            self._authorize(_data(reader), "update")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_other_workspace_is_refused(self) -> None:
        with self.assertRaises(BaseAPIException) as ctx:
            self._authorize(_data(OWNER, workspace_id=OTHER_WORKSPACE))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_workspace_scope_cannot_widen_itself_by_dropping_the_param(self) -> None:
        with self.assertRaises(BaseAPIException) as ctx:
            self._authorize(_data(OWNER, workspace_id=None))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_global_holder_gets_the_cross_workspace_scope(self) -> None:
        operator = {
            "user_id": 1,
            "roles": [],
            "permissions": [{"resource": "rank", "action": "read"}],
            "workspaces": [],
        }
        self.assertIsNone(self._authorize(_data(operator, workspace_id=None)))

    def test_superuser_keeps_both(self) -> None:
        root = {"user_id": 1, "is_superuser": True, "roles": [], "permissions": [], "workspaces": []}
        self.assertIsNone(self._authorize(_data(root, workspace_id=None)))
        self.assertEqual(self._authorize(_data(root)), WORKSPACE)

    def test_inactive_user_is_refused_before_the_permission_check(self) -> None:
        with self.assertRaises(BaseAPIException) as ctx:
            self._authorize(_data(dict(OWNER, is_active=False)))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_deny_overlay_beats_the_workspace_wildcard(self) -> None:
        denied = dict(OWNER, denies=[{"resource": "rank", "action": "update"}])
        self.assertEqual(self._authorize(_data(denied)), WORKSPACE)
        with self.assertRaises(BaseAPIException):
            self._authorize(_data(denied), "update")


class ScopingTests(IsolatedAsyncioTestCase):
    """The scope reaches the SQL, not just the 403."""

    #: The membership hop every scoped rank query must go through.
    MEMBER_JOIN = "workspace_member"

    @staticmethod
    def _captured_sql(session) -> str:
        calls = list(session.execute.await_args_list) + list(session.scalars.await_args_list)
        return " ".join(str(call.args[0]) for call in calls)

    @staticmethod
    def _empty_session():
        from unittest.mock import AsyncMock, MagicMock

        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)
        scalars = MagicMock()
        scalars.all.return_value = []
        session.scalars = AsyncMock(return_value=scalars)
        return session

    async def test_fetch_log_filters_through_workspace_membership(self) -> None:
        from src.services.overwatch_rank import admin

        session = self._empty_session()
        await admin.list_fetch_log(session, workspace_id=WORKSPACE)
        self.assertIn(self.MEMBER_JOIN, self._captured_sql(session))

    async def test_fetch_log_unscoped_query_has_no_membership_predicate(self) -> None:
        from src.services.overwatch_rank import admin

        session = self._empty_session()
        await admin.list_fetch_log(session)
        self.assertNotIn(self.MEMBER_JOIN, self._captured_sql(session))

    async def test_user_collection_filters_through_workspace_membership(self) -> None:
        from src.services.overwatch_rank import admin

        session = self._empty_session()
        await admin.get_user_collection_status(session, 5, workspace_id=WORKSPACE)
        self.assertIn(self.MEMBER_JOIN, self._captured_sql(session))

    async def test_trigger_cannot_reach_tags_outside_the_workspace(self) -> None:
        # An explicit social_account_ids list is caller-supplied, so the scope has
        # to constrain it too — otherwise a workspace admin force-fetches any tag.
        from src.services.overwatch_rank import admin

        session = self._empty_session()
        enqueued = await admin.trigger_collection(session, social_account_ids=[1, 2], workspace_id=WORKSPACE)

        self.assertEqual(enqueued, 0)
        self.assertIn(self.MEMBER_JOIN, self._captured_sql(session))

    async def test_reenable_scopes_the_update(self) -> None:
        from unittest.mock import AsyncMock, patch

        from shared.schemas.settings import RankCollectionConfig
        from src.services.overwatch_rank import service

        session = self._empty_session()
        with patch.object(
            settings_provider,
            "get_rank_collection_config",
            AsyncMock(return_value=RankCollectionConfig()),
        ):
            from src.services.overwatch_rank import admin

            await admin.reenable_disabled(session, workspace_id=WORKSPACE)

        sql = self._captured_sql(session)
        self.assertIn("UPDATE", sql)
        self.assertIn(self.MEMBER_JOIN, sql)
        # The helper is the single definition of the membership hop.
        self.assertIn(self.MEMBER_JOIN, str(service.workspace_account_ids(WORKSPACE)))

    async def test_collection_stats_scopes_every_aggregate(self) -> None:
        from src.services.overwatch_rank import service

        session = self._empty_session()
        session.scalar = self._scalar_zero()
        await service.collection_stats(session, workspace_id=WORKSPACE)

        calls = list(session.execute.await_args_list) + list(session.scalar.await_args_list)
        self.assertTrue(calls)
        for call in calls:
            self.assertIn(self.MEMBER_JOIN, str(call.args[0]))

    @staticmethod
    def _scalar_zero():
        from unittest.mock import AsyncMock

        return AsyncMock(return_value=0)
