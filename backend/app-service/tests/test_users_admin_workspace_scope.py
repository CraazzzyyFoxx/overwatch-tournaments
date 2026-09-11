"""Authorization + tenant scoping for the Player-identities admin surface.

The regression this file exists for: every ``rpc.app.users.*`` handler demanded
a **global** ``user.<action>`` grant, so a workspace owner -- whose ``admin.*``
is workspace-scoped -- was refused the page outright and the frontend hid the
"Player identities" entry from their navigation to avoid a guaranteed 403. But
``user.*`` is in the workspace permission catalog (a workspace ``member`` holds
``user.read``, ``admin``/``owner`` hold the full CRUD), so the read is meant to
be grantable per workspace.

The line drawn now, and pinned here:

* **read** (``admin_list``) is workspace-grantable. ``workspace_id`` is both the
  authorization scope and the row filter, the same shape as the rank/subscription
  collection admin (``parser-service/src/rpc/rank.py``) -- so a scoped holder
  sees their own roster and cannot widen the read to the platform-wide registry
  by dropping the param;
* **writes to the global identity** (create/update/delete, avatar) still demand
  the global grant: a player identity is platform-wide, so editing one from
  inside a workspace would reach into every other workspace's history;
* **display visibility** is authorized in the scope it changes -- the
  per-workspace switch against that workspace's ``user.read``, the global switch
  against the global one.

Unlike ``rank._authorize``, a global holder stays unscoped even when
``workspace_id`` rides along (the frontend's ``apiFetch`` injects it on every
``/api/v1`` call), because dedupe/merge across workspaces is the whole job of
this page.

No DB and no broker: the gates are pure functions of the injected identity, and
the list query is driven with a fake session that records the SQL it is handed.
"""

from __future__ import annotations

from typing import Any
from unittest import IsolatedAsyncioTestCase, TestCase

from shared.core.errors import BaseAPIException
from shared.rbac.catalog import PERMISSION_CATALOG, permission_names_for_workspace_role
from src import schemas
from src.rpc import users_admin
from src.services.admin.user import users as admin_users

WORKSPACE = 7
OTHER_WORKSPACE = 9

#: What identity-service puts in the token for a workspace owner: the `owner`
#: system role, whose only grant is the workspace-scoped `admin.*` wildcard.
OWNER: dict[str, Any] = {
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


def _data(identity: dict, *, workspace_id: int | None = WORKSPACE) -> dict:
    """The gateway envelope: query params always arrive as lists of strings."""
    data: dict = {"identity": identity}
    if workspace_id is not None:
        data["query"] = {"workspace_id": [str(workspace_id)]}
    return data


class CatalogTests(TestCase):
    def test_user_crud_is_workspace_grantable(self) -> None:
        pairs = {(p.resource, p.action) for p in PERMISSION_CATALOG}
        for action in ("read", "create", "update", "delete"):
            self.assertIn(("user", action), pairs)

    def test_a_plain_member_already_holds_the_read(self) -> None:
        self.assertIn("user.read", permission_names_for_workspace_role("member"))


class ScopeTests(TestCase):
    def _scope(self, data: dict, action: str = "read") -> int | None:
        return users_admin._scope(data, action)

    def test_workspace_owner_is_allowed_and_scoped(self) -> None:
        self.assertEqual(self._scope(_data(OWNER)), WORKSPACE)

    def test_workspace_scope_cannot_widen_itself_by_dropping_the_param(self) -> None:
        with self.assertRaises(BaseAPIException) as ctx:
            self._scope(_data(OWNER, workspace_id=None))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_other_workspace_is_refused(self) -> None:
        with self.assertRaises(BaseAPIException) as ctx:
            self._scope(_data(OWNER, workspace_id=OTHER_WORKSPACE))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_explicit_workspace_read_without_any_role_is_enough(self) -> None:
        reader = {
            "user_id": 43,
            "roles": [],
            "permissions": [],
            "workspaces": [
                {
                    "workspace_id": WORKSPACE,
                    "rbac_roles": ["member"],
                    "rbac_permissions": [{"resource": "user", "action": "read"}],
                }
            ],
        }
        self.assertEqual(self._scope(_data(reader)), WORKSPACE)

    def test_global_holder_keeps_the_platform_wide_registry(self) -> None:
        # Even with workspace_id on the wire: apiFetch injects it on every
        # /api/v1 call, and filtering the global operator's page to one workspace
        # would break the cross-workspace dedupe this surface exists for.
        operator = {
            "user_id": 1,
            "roles": [],
            "permissions": [{"resource": "user", "action": "read"}],
            "workspaces": [],
        }
        self.assertIsNone(self._scope(_data(operator)))
        self.assertIsNone(self._scope(_data(operator, workspace_id=None)))

    def test_superuser_stays_unscoped(self) -> None:
        root = {"user_id": 1, "is_superuser": True, "roles": [], "permissions": [], "workspaces": []}
        self.assertIsNone(self._scope(_data(root)))

    def test_inactive_user_is_refused_before_the_permission_check(self) -> None:
        with self.assertRaises(BaseAPIException) as ctx:
            self._scope(_data(dict(OWNER, is_active=False)))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_deny_overlay_beats_the_workspace_wildcard(self) -> None:
        denied = dict(OWNER, denies=[{"resource": "user", "action": "read"}])
        with self.assertRaises(BaseAPIException) as ctx:
            self._scope(_data(denied))
        self.assertEqual(ctx.exception.status_code, 403)


class GlobalWriteTests(TestCase):
    """The writes stayed global — a workspace grant must not reach them."""

    def test_workspace_owner_cannot_write_the_global_identity(self) -> None:
        for action in ("create", "update", "delete"):
            with self.subTest(action=action), self.assertRaises(BaseAPIException) as ctx:
                users_admin._gate(_data(OWNER), action)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_global_holder_still_writes(self) -> None:
        operator = {
            "user_id": 1,
            "roles": [],
            "permissions": [{"resource": "user", "action": "update"}],
            "workspaces": [],
        }
        self.assertIsNotNone(users_admin._gate(_data(operator), "update"))


class VisibilityScopeTests(TestCase):
    def test_workspace_toggle_is_answered_by_that_workspace(self) -> None:
        self.assertIsNone(users_admin._visibility_scope(_data(OWNER), WORKSPACE))

    def test_workspace_toggle_in_a_foreign_workspace_is_refused(self) -> None:
        with self.assertRaises(BaseAPIException) as ctx:
            users_admin._visibility_scope(_data(OWNER), OTHER_WORKSPACE)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_the_global_switch_keeps_the_global_grant(self) -> None:
        # Hiding a handle everywhere is not a workspace's call to make.
        with self.assertRaises(BaseAPIException) as ctx:
            users_admin._visibility_scope(_data(OWNER), None)
        self.assertEqual(ctx.exception.status_code, 403)


class _FakeResult:
    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list:
        return []

    def scalar_one(self) -> int:
        return 0


class _FakeSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult()


class ListScopingTests(IsolatedAsyncioTestCase):
    """The scope reaches the SQL, not just the 403."""

    #: The membership hop a scoped page must go through.
    MEMBER_HOP = "workspace_member"

    @staticmethod
    def _params() -> schemas.UserListParams:
        return schemas.UserListParams.from_query_params(schemas.UserListQueryParams())

    async def _sql(self, workspace_id: int | None) -> str:
        session = _FakeSession()
        await admin_users.get_users(session, self._params(), workspace_id=workspace_id)
        # Both the page and the count must be scoped, or the pagination footer
        # advertises other workspaces' identities.
        self.assertEqual(len(session.statements), 2)
        return " ".join(str(statement) for statement in session.statements)

    async def test_a_scoped_page_filters_on_workspace_membership(self) -> None:
        sql = await self._sql(WORKSPACE)
        self.assertIn(self.MEMBER_HOP, sql)
        self.assertIn("EXISTS", sql)

    async def test_an_unscoped_page_is_the_whole_registry(self) -> None:
        sql = await self._sql(None)
        self.assertNotIn(self.MEMBER_HOP, sql)


class ListFilterTests(IsolatedAsyncioTestCase):
    """Chip filters reach the SQL, not a client-side pass over `per_page=-1`."""

    async def _sql(self, **overrides: Any) -> str:
        session = _FakeSession()
        params = schemas.UserListParams.from_query_params(schemas.UserListQueryParams(**overrides))
        await admin_users.get_users(session, params, workspace_id=None)
        self.assertEqual(len(session.statements), 2)
        return " ".join(str(statement) for statement in session.statements)

    async def test_has_account_adds_an_auth_user_predicate(self) -> None:
        base = await self._sql()
        sql = await self._sql(has_account=True)
        self.assertNotEqual(sql, base)
        self.assertIn("IS NOT NULL", sql)

    async def test_unlinked_adds_a_social_account_anti_join(self) -> None:
        base = await self._sql()
        sql = await self._sql(unlinked=True)
        self.assertNotEqual(sql, base)
        self.assertIn("EXISTS", sql)

    async def test_tournament_adds_a_roster_exists_predicate(self) -> None:
        base = await self._sql()
        sql = await self._sql(tournament_id=7)
        self.assertNotEqual(sql, base)
        self.assertIn("EXISTS", sql)
        self.assertIn("tournament_id", sql)


class DashboardIssueScopingTests(IsolatedAsyncioTestCase):
    """The "Unlinked player identities" card links into the scoped list.

    Every other issue count hangs off ``Tournament`` and so inherits
    ``ws_filters``; this one counts platform-wide ``players.user`` rows and had no
    workspace dimension at all -- harmless while only global operators saw the
    card, a plain lie now that a workspace owner does (a platform-wide number
    linking to a page that lists their roster).
    """

    @staticmethod
    def _session() -> Any:
        class _Row:
            def one(self) -> tuple[int, ...]:
                return (0,) * 7

        class _Session:
            def __init__(self) -> None:
                self.statements: list[Any] = []

            async def execute(self, statement: Any) -> Any:
                self.statements.append(statement)
                return _Row()

        return _Session()

    async def _sql(self, workspace_id: int | None) -> str:
        from src.services.dashboard.service import dashboard

        session = self._session()
        await dashboard.get_issues(session, workspace_id)
        return str(session.statements[0])

    async def test_a_scoped_dashboard_counts_only_this_workspace_roster(self) -> None:
        # `workspace_member` reaches the statement from this subquery alone.
        self.assertIn("workspace_member", await self._sql(WORKSPACE))

    async def test_an_unscoped_dashboard_counts_the_whole_platform(self) -> None:
        self.assertNotIn("workspace_member", await self._sql(None))
