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

import logging
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "stats-service"))


from shared.core.errors import BaseAPIException  # noqa: E402
from shared.core.social import SocialProvider  # noqa: E402
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

    def test_plain_player_does_not_get_collection_health(self) -> None:
        self.assertNotIn("rank.read", permission_names_for_workspace_role("player"))


class AuthorizeTests(TestCase):
    def _authorize(self, data: dict, action: str = "read") -> int | None:
        from shared.disciplines.overwatch.collector import handlers
        from shared.rpc.common import actor

        return handlers.authorize(actor(data), data, action)

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
        from shared.disciplines.overwatch.collector import admin

        session = self._empty_session()
        await admin.list_fetch_log(session, workspace_id=WORKSPACE)
        self.assertIn(self.MEMBER_JOIN, self._captured_sql(session))

    async def test_fetch_log_unscoped_query_has_no_membership_predicate(self) -> None:
        from shared.disciplines.overwatch.collector import admin

        session = self._empty_session()
        await admin.list_fetch_log(session)
        self.assertNotIn(self.MEMBER_JOIN, self._captured_sql(session))

    async def test_user_collection_filters_through_workspace_membership(self) -> None:
        from shared.disciplines.overwatch.collector import admin

        session = self._empty_session()
        await admin.get_user_collection_status(session, 5, workspace_id=WORKSPACE)
        self.assertIn(self.MEMBER_JOIN, self._captured_sql(session))

    async def test_trigger_cannot_reach_tags_outside_the_workspace(self) -> None:
        # An explicit social_account_ids list is caller-supplied, so the scope has
        # to constrain it too — otherwise a workspace admin force-fetches any tag.
        from shared.disciplines.overwatch.collector import admin

        session = self._empty_session()
        enqueued = await admin.trigger_collection(session, social_account_ids=[1, 2], workspace_id=WORKSPACE)

        self.assertEqual(enqueued, 0)
        self.assertIn(self.MEMBER_JOIN, self._captured_sql(session))

    async def test_reenable_scopes_the_update(self) -> None:
        from unittest.mock import AsyncMock, patch

        from shared.disciplines.overwatch.collector import service
        from shared.schemas.settings import RankCollectionConfig

        session = self._empty_session()
        with patch.object(
            settings_provider,
            "get_rank_collection_config",
            AsyncMock(return_value=RankCollectionConfig()),
        ):
            from shared.disciplines.overwatch.collector import admin

            await admin.reenable_disabled(session, workspace_id=WORKSPACE)

        sql = self._captured_sql(session)
        self.assertIn("UPDATE", sql)
        self.assertIn(self.MEMBER_JOIN, sql)
        # The helper is the single definition of the membership hop.
        self.assertIn(
            self.MEMBER_JOIN, str(service.workspace_account_ids(WORKSPACE, provider=SocialProvider.BATTLENET))
        )

    async def test_collection_stats_scopes_every_aggregate(self) -> None:
        from shared.disciplines.overwatch.collector import service

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


class RpcDispatchTests(IsolatedAsyncioTestCase):
    """Every ``rpc.stats.rank.*`` subject reaches the module handler behind it, with its authorization intact."""

    SUBJECTS = {
        f"rpc.stats.rank.{name}"
        for name in (
            "user_history",
            "game_account_history",
            "user_current",
            "user_career",
            "fetch_log",
            "stats",
            "user_collection",
            "career_signals",
            "career_health",
            "collect",
            "reenable_disabled",
        )
    }

    def setUp(self) -> None:
        from unittest.mock import patch

        from src.rpc import rank
        from tests._fakes import FakeBroker, session_factory

        self.broker = FakeBroker()
        rank.register(self.broker, logging.getLogger("test"))
        patcher = patch.object(rank, "_SF", session_factory(object()))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_subject_is_served(self) -> None:
        self.assertEqual(set(self.broker.handlers), self.SUBJECTS)

    async def test_an_admin_subject_without_identity_is_unauthorized(self) -> None:
        envelope = await self.broker.handlers["rpc.stats.rank.stats"]({"query": {}}, msg=None)
        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual(envelope["error"]["code"], "unauthorized")

    async def test_an_admin_subject_enforces_the_permission_behind_it(self) -> None:
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
        envelope = await self.broker.handlers["rpc.stats.rank.collect"](_data(reader), msg=None)
        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual(envelope["error"]["code"], "forbidden")

    async def test_a_public_read_runs_without_identity(self) -> None:
        from unittest.mock import AsyncMock, patch

        from shared.disciplines.overwatch.collector import queries

        with patch.object(queries, "get_current_ranks", AsyncMock(return_value=[])):
            envelope = await self.broker.handlers["rpc.stats.rank.user_current"](
                {"id": 5, "query": {"platform": ["pc"]}}, msg=None
            )
        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(envelope["data"]["user_id"], 5)

    async def test_a_public_read_ignores_a_malformed_identity(self) -> None:
        from unittest.mock import AsyncMock, patch

        from shared.disciplines.overwatch.collector import queries

        with patch.object(queries, "get_current_ranks", AsyncMock(return_value=[])):
            envelope = await self.broker.handlers["rpc.stats.rank.user_current"](
                {"id": 5, "identity": {"roles": []}, "query": {"platform": ["pc"]}}, msg=None
            )
        self.assertTrue(envelope["ok"], envelope)

    async def test_an_admin_subject_rejects_a_malformed_identity(self) -> None:
        envelope = await self.broker.handlers["rpc.stats.rank.stats"]({"identity": {"roles": []}}, msg=None)
        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual(envelope["error"]["code"], "unauthorized")

    async def test_a_subject_routes_to_the_named_games_handler(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        from src.rpc import rank

        handler = AsyncMock(return_value={"user_id": 5, "ranks": [], "generated_at": "2026-10-21T00:00:00Z"})
        fake = SimpleNamespace(collection_handlers={"rank.user_current": handler})
        with patch.dict(rank.DISCIPLINES, {"lol": fake}):
            envelope = await self.broker.handlers["rpc.stats.rank.user_current"](
                {"id": 5, "query": {"discipline": ["lol"]}}, msg=None
            )
        self.assertTrue(envelope["ok"], envelope)
        handler.assert_awaited_once()

    async def test_a_game_without_rank_collection_is_not_found(self) -> None:
        envelope = await self.broker.handlers["rpc.stats.rank.user_current"](
            {"id": 5, "query": {"discipline": ["chess"]}}, msg=None
        )
        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual(envelope["error"]["code"], "not_found")
