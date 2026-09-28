"""Behavioural pins for the three notification settings surfaces.

All three are "who may change what": the personal DM switches are self-service
and may only ever edit the caller's own row, the workspace delivery config
decides which Discord channel the bot is made to speak in -- which is why a
channel outside the workspace's own verified guild has to be refused rather
than stored -- and the admin account inspector is the one place where an
operator reads and edits *somebody else's* switches, on a global grant and a
path id.

SQLite with the Postgres type shims behind the sync-``Session`` facade, like the
sibling notification suites: the answers are rows and effective values, and a
mocked session would agree with a flow that stores the wrong one.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cashews import cache  # noqa: E402

from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.oauth import OAuthConnection  # noqa: E402
from shared.models.identity.rbac import Role, user_roles  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from shared.models.platform.notification import (  # noqa: E402
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationRead,
    NotificationWorkspaceConfig,
)
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.services.discord_client import DiscordClient  # noqa: E402
from shared.services.notifications import NOTIFICATION_GROUPS  # noqa: E402
from shared.services.subscriptions.providers.discord_role import DiscordUnavailable  # noqa: E402
from shared.testing import install_postgres_type_shims  # noqa: E402
from src import schemas  # noqa: E402
from src.rpc import notifications as notifications_rpc  # noqa: E402
from src.rpc import notifications_admin as notifications_admin_rpc  # noqa: E402
from src.rpc import workspaces as workspaces_rpc  # noqa: E402
from src.services import notifications as notification_service  # noqa: E402

install_postgres_type_shims()

TABLES = (
    NotificationPreference.__table__,
    NotificationWorkspaceConfig.__table__,
    OAuthConnection.__table__,
    Workspace.__table__,
    # The admin inspector's half: the account it names, the ledger of what was
    # actually DM'd, and the four tables the unread count's audience resolves
    # through.
    AuthUser.__table__,
    Notification.__table__,
    NotificationRead.__table__,
    NotificationDelivery.__table__,
    WorkspaceMember.__table__,
    User.__table__,
    Role.__table__,
    user_roles,
)

ALICE = 100
WORKSPACE = 7
GUILD = "111111111111111111"
CHANNEL = "222222222222222222"

PAST = datetime.now(UTC) - timedelta(hours=1)

_ALICE = {"user_id": ALICE, "username": "alice", "is_active": True, "is_superuser": False}
_OWNER = {
    **_ALICE,
    "workspaces": [{"workspace_id": WORKSPACE, "rbac_roles": ["owner"], "rbac_permissions": []}],
}
_OUTSIDER = {"user_id": 3, "username": "mallory", "is_active": True, "is_superuser": False, "workspaces": []}

# The admin inspector's cast: the account being looked at, an operator who may
# only read and one who may also write. Both grants are global — this surface
# has no workspace to scope them to.
TARGET = 200
READER = 201
EDITOR = 202
DISCORD_TARGET = "424242424242424242"
DISCORD_STRANGER = "999999999999999999"

_READER = {
    "user_id": READER,
    "username": "reader",
    "is_active": True,
    "is_superuser": False,
    "permissions": [{"resource": "auth_user", "action": "read"}],
    "workspaces": [],
}
_EDITOR = {
    **_READER,
    "user_id": EDITOR,
    "username": "editor",
    "permissions": [
        {"resource": "auth_user", "action": "read"},
        {"resource": "auth_user", "action": "update"},
    ],
}


class _AsyncSessionShim:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: Any) -> Any:
        return self._session.execute(statement)

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()


class _SessionMaker:
    def __init__(self, shim: _AsyncSessionShim) -> None:
        self._shim = shim

    def __call__(self) -> _SessionMaker:
        return self

    async def __aenter__(self) -> _AsyncSessionShim:
        return self._shim

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _SettingsCase(IsolatedAsyncioTestCase):
    """Engine + captured subscribers for all three RPC modules."""

    def setUp(self) -> None:
        self.engine = sa.create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in TABLES if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in TABLES:
                table.create(conn)
        self.session = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

        maker = _SessionMaker(_AsyncSessionShim(self.session))
        self.handlers: dict[str, Any] = {}
        broker = MagicMock()
        broker.subscriber = self._capture
        notifications_rpc.register(broker, MagicMock())
        notifications_admin_rpc.register(broker, MagicMock())
        workspaces_rpc.register(broker, MagicMock())
        for module in (notifications_rpc, notifications_admin_rpc, workspaces_rpc):
            original = module._SF
            module._SF = maker
            self.addCleanup(setattr, module, "_SF", original)

    def _capture(self, subject: str, *args: Any, **kwargs: Any):
        def decorator(fn):
            self.handlers[subject] = fn
            return fn

        return decorator

    async def call(self, subject: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self.handlers[subject](data, MagicMock())


class PreferencesRpcTests(_SettingsCase):
    def link_discord(self) -> None:
        self.session.add(
            OAuthConnection(
                auth_user_id=ALICE,
                provider="discord",
                provider_user_id="424242424242424242",
                username="alice",
            )
        )
        self.session.flush()

    def stored(self) -> dict[str, bool] | None:
        row = self.session.get(NotificationPreference, ALICE)
        return dict(row.discord_dm) if row is not None else None

    async def test_the_caller_must_be_authenticated(self) -> None:
        """Preferences are per person; without an identity there is no row."""
        for subject in ("rpc.app.notification_preferences_get", "rpc.app.notification_preferences_update"):
            answer = await self.call(subject, {"payload": {"discord_dm": {"team": False}}})

            self.assertFalse(answer["ok"], subject)
            self.assertEqual(answer["error"]["code"], "unauthorized", subject)

    async def test_an_untouched_account_reads_every_group_on(self) -> None:
        """Defaults are computed, not stored: a new group needs no backfill."""
        answer = await self.call("rpc.app.notification_preferences_get", {"identity": _ALICE})

        self.assertTrue(answer["ok"], answer)
        self.assertEqual(answer["data"]["discord_dm"], dict.fromkeys(NOTIFICATION_GROUPS, True))
        self.assertFalse(answer["data"]["discord_linked"])
        self.assertIsNone(self.stored())

    async def test_a_linked_account_is_reported_as_linked(self) -> None:
        """The switches deliver nothing without a Discord account to DM."""
        self.link_discord()

        answer = await self.call("rpc.app.notification_preferences_get", {"identity": _ALICE})

        self.assertTrue(answer["data"]["discord_linked"])

    async def test_an_edit_is_partial_and_answers_with_the_effect(self) -> None:
        """Two edits in a row must not let the second re-assert the first.

        The stored row holds only what was changed, so the response has to be
        the *effective* map -- what the user will actually receive.
        """
        first = await self.call(
            "rpc.app.notification_preferences_update",
            {"identity": _ALICE, "payload": {"discord_dm": {"matches": False}}},
        )
        second = await self.call(
            "rpc.app.notification_preferences_update",
            {"identity": _ALICE, "payload": {"discord_dm": {"team": False}}},
        )

        self.assertTrue(first["ok"], first)
        self.assertEqual(first["data"]["discord_dm"], {"tournament": True, "matches": False, "team": True})
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["data"]["discord_dm"], {"tournament": True, "matches": False, "team": False})
        self.assertEqual(self.stored(), {"matches": False, "team": False})

    async def test_an_unknown_group_is_rejected(self) -> None:
        """A typo'd group would otherwise be stored and silently do nothing."""
        answer = await self.call(
            "rpc.app.notification_preferences_update",
            {"identity": _ALICE, "payload": {"discord_dm": {"tournaments": False}}},
        )

        self.assertFalse(answer["ok"], answer)
        self.assertEqual(answer["error"]["code"], "unprocessable")

    def test_the_response_shape_names_every_group(self) -> None:
        """``NotificationDmGroups`` is hand-written for OpenAPI; keep it honest."""
        self.assertEqual(set(schemas.NotificationDmGroups.model_fields), set(NOTIFICATION_GROUPS))
        self.assertEqual(set(schemas.NotificationDmGroupsUpdate.model_fields), set(NOTIFICATION_GROUPS))


class AdminUserNotificationsRpcTests(_SettingsCase):
    """The one notification surface that acts on somebody else's account.

    Everything here is about the target rather than the caller: the switches
    read and written are the path id's, the badge count is the one that account
    sees, and the delivery ledger is filtered to *their* Discord ids -- a
    missing filter would show an operator strangers' messages.
    """

    async def asyncSetUp(self) -> None:
        # The workspace set is cached per auth_user_id in a process-global
        # cashews backend that outlives one test's database.
        for auth_user_id in (ALICE, TARGET):
            await cache.delete(notification_service.WORKSPACE_IDS_CACHE_KEY.format(auth_user_id=auth_user_id))

    # -- builders ---------------------------------------------------------

    def account(self, auth_user_id: int = TARGET, username: str = "target") -> int:
        self.session.add(AuthUser(id=auth_user_id, email=f"{username}@example.test", username=username))
        self.session.flush()
        return auth_user_id

    def link_discord(self, auth_user_id: int, provider_user_id: str) -> None:
        self.session.add(
            OAuthConnection(
                auth_user_id=auth_user_id,
                provider="discord",
                provider_user_id=provider_user_id,
                username="linked",
            )
        )
        self.session.flush()

    def notify(self, auth_user_id: int) -> int:
        row = Notification(
            kind="registration.approved",
            audience="user",
            recipient_auth_user_id=auth_user_id,
            published_at=PAST,
        )
        self.session.add(row)
        self.session.flush()
        return row.id

    def delivered(self, target: str, *, channel: str = "discord_dm", created_at: datetime = PAST) -> int:
        row = NotificationDelivery(
            channel=channel,
            target=target,
            dedupe_key=f"{channel}:{target}:{created_at.isoformat()}",
            kind="match.scheduled",
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row.id

    async def read(self, identity: dict, auth_user_id: int = TARGET) -> dict[str, Any]:
        return await self.call("rpc.app.admin_user_notifications_get", {"identity": identity, "id": auth_user_id})

    async def write(self, identity: dict, auth_user_id: int = TARGET, **groups: bool) -> dict[str, Any]:
        return await self.call(
            "rpc.app.admin_user_notification_preferences_update",
            {"identity": identity, "id": auth_user_id, "payload": {"discord_dm": groups}},
        )

    def stored(self, auth_user_id: int) -> dict[str, bool] | None:
        self.session.expire_all()
        row = self.session.get(NotificationPreference, auth_user_id)
        return dict(row.discord_dm) if row is not None else None

    # -- the gate ----------------------------------------------------------

    async def test_reading_another_account_needs_the_global_read_grant(self) -> None:
        """Without it this is an ordinary user reading a stranger's settings."""
        self.account()

        answer = await self.read(_ALICE)

        self.assertFalse(answer["ok"], answer)
        self.assertEqual(answer["error"]["code"], "forbidden")

    async def test_writing_another_account_needs_update_not_merely_read(self) -> None:
        """Read is a weaker grant; it must not carry the edit with it."""
        self.account()

        answer = await self.write(_READER, matches=False)

        self.assertFalse(answer["ok"], answer)
        self.assertEqual(answer["error"]["code"], "forbidden")
        self.assertIsNone(self.stored(TARGET))

    async def test_a_missing_account_is_a_404_on_both_subjects(self) -> None:
        """Nothing is stored for an id that never existed, and no 200 implies it was."""
        read = await self.read(_READER)
        write = await self.write(_EDITOR, team=False)

        self.assertEqual(read["error"]["code"], "not_found", read)
        self.assertEqual(write["error"]["code"], "not_found", write)
        self.assertIsNone(self.stored(TARGET))

    # -- the read ----------------------------------------------------------

    async def test_the_read_answers_the_targets_effective_switches_and_link(self) -> None:
        """The target's values, not the caller's, and defaults filled in."""
        self.account()
        self.link_discord(TARGET, DISCORD_TARGET)
        self.session.add(NotificationPreference(auth_user_id=TARGET, discord_dm={"matches": False}))
        # The operator's own row must not answer for the account they inspect.
        self.session.add(NotificationPreference(auth_user_id=READER, discord_dm={"team": False}))
        self.session.flush()

        answer = await self.read(_READER)

        self.assertTrue(answer["ok"], answer)
        self.assertEqual(answer["data"]["discord_dm"], {"tournament": True, "matches": False, "team": True})
        self.assertTrue(answer["data"]["discord_linked"])

    async def test_the_unread_count_is_the_one_that_accounts_bell_shows(self) -> None:
        """Their inbox's audience, not a platform-wide total."""
        self.account()
        self.notify(TARGET)
        self.notify(TARGET)
        self.notify(ALICE)

        answer = await self.read(_READER)

        self.assertEqual(answer["data"]["unread_count"], 2, answer)

    async def test_deliveries_are_this_accounts_discord_dms_newest_first_capped_at_ten(self) -> None:
        """Three different ways the ledger could leak or mislead, in one pin.

        The ledger is keyed by Discord snowflake, so a target filter that let a
        stranger's id through, a channel filter that let a workspace broadcast
        through, or an unordered read would each put the wrong rows in front of
        an operator.
        """
        self.account()
        self.link_discord(TARGET, DISCORD_TARGET)
        mine = [self.delivered(DISCORD_TARGET, created_at=PAST + timedelta(minutes=index)) for index in range(12)]
        self.delivered(DISCORD_STRANGER)
        self.delivered(DISCORD_TARGET, channel="discord_channel")

        answer = await self.read(_READER)

        rows = answer["data"]["recent_deliveries"]
        self.assertEqual([row["id"] for row in rows], list(reversed(mine[2:])))
        self.assertEqual({row["channel"] for row in rows}, {"discord_dm"})

    async def test_an_account_with_no_discord_has_an_empty_ledger(self) -> None:
        """An unfiltered IN () would hand over every delivery on the platform."""
        self.account()
        self.delivered(DISCORD_STRANGER)

        answer = await self.read(_READER)

        self.assertEqual(answer["data"]["recent_deliveries"], [])
        self.assertFalse(answer["data"]["discord_linked"])

    # -- the write ---------------------------------------------------------

    async def test_the_write_edits_the_target_row_and_answers_the_full_payload(self) -> None:
        """The caller's own preferences must be untouched by an admin edit."""
        self.account()
        self.session.add(NotificationPreference(auth_user_id=EDITOR, discord_dm={"tournament": False}))
        self.session.flush()

        answer = await self.write(_EDITOR, matches=False)

        self.assertTrue(answer["ok"], answer)
        self.assertEqual(answer["data"]["discord_dm"], {"tournament": True, "matches": False, "team": True})
        self.assertEqual(answer["data"]["unread_count"], 0)
        self.assertEqual(answer["data"]["recent_deliveries"], [])
        self.assertEqual(self.stored(TARGET), {"matches": False})
        self.assertEqual(self.stored(EDITOR), {"tournament": False})

    async def test_the_admin_edit_is_partial_like_the_self_service_one(self) -> None:
        """An operator fixing one group must not re-assert the other two."""
        self.account()

        await self.write(_EDITOR, matches=False)
        answer = await self.write(_EDITOR, team=False)

        self.assertEqual(answer["data"]["discord_dm"], {"tournament": True, "matches": False, "team": False})
        self.assertEqual(self.stored(TARGET), {"matches": False, "team": False})


class WorkspaceNotificationConfigRpcTests(_SettingsCase):
    def workspace(self, *, guild_id: str | None = GUILD) -> None:
        self.session.add(
            Workspace(
                id=WORKSPACE,
                slug="cup",
                name="Cup",
                created_at=PAST,
                is_active=True,
                is_hidden=False,
                timezone="UTC",
                branding_enabled=False,
                verification_status="verified",
                newcomer_scope="workspace",
                discord_guild_id=guild_id,
            )
        )
        self.session.flush()

    def stored(self) -> NotificationWorkspaceConfig | None:
        return self.session.get(NotificationWorkspaceConfig, WORKSPACE)

    async def update(self, body: dict[str, Any], *, channels: Any = None, identity: dict[str, Any] | None = None):
        """Call the update handler with ``DiscordClient.guild_channels`` stubbed.

        ``channels`` is the guild's text channels, or the ``DiscordError`` the
        lookup raises. Patching the real method keeps the wiring under test --
        the handler binds it off a freshly built client.
        """
        listing = list(channels or []) if not isinstance(channels, BaseException) else None

        async def stub(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            if listing is None:
                raise channels
            return listing

        with patch.object(DiscordClient, "guild_channels", stub):
            return await self.call(
                "rpc.app.workspaces.notification_config_update",
                {"workspace_id": str(WORKSPACE), "identity": identity or _OWNER, "payload": body},
            )

    async def test_an_unconfigured_workspace_reads_its_defaults(self) -> None:
        """The screen has to render before anybody saves anything."""
        self.workspace()

        answer = await self.call(
            "rpc.app.workspaces.notification_config_get",
            {"workspace_id": str(WORKSPACE), "identity": _OWNER},
        )

        self.assertTrue(answer["ok"], answer)
        self.assertEqual(
            answer["data"],
            {
                "workspace_id": WORKSPACE,
                "discord_guild_id": GUILD,
                "discord_channel_id": None,
                "locale": "ru",
                "broadcast_kinds": ["registration.opened", "check_in.opened"],
                "broadcastable_kinds": ["check_in.opened", "encounter.scheduled", "registration.opened"],
            },
        )

    async def test_outsiders_cannot_read_or_write_the_config(self) -> None:
        """It names a private channel and it makes the bot speak."""
        self.workspace()

        read = await self.call(
            "rpc.app.workspaces.notification_config_get",
            {"workspace_id": str(WORKSPACE), "identity": _OUTSIDER},
        )
        write = await self.update({"broadcast_kinds": []}, identity=_OUTSIDER)

        self.assertEqual(read["error"]["code"], "forbidden", read)
        self.assertEqual(write["error"]["code"], "forbidden", write)

    async def test_a_channel_of_this_guild_is_stored_as_an_integer(self) -> None:
        """Snowflakes cross the wire as strings and are stored as bigints."""
        self.workspace()

        answer = await self.update(
            {"discord_channel_id": CHANNEL, "locale": "en", "broadcast_kinds": ["check_in.opened"]},
            channels=[{"id": CHANNEL, "name": "general"}],
        )

        self.assertTrue(answer["ok"], answer)
        self.assertEqual(answer["data"]["discord_channel_id"], CHANNEL)
        self.assertEqual(answer["data"]["locale"], "en")
        self.assertEqual(answer["data"]["broadcast_kinds"], ["check_in.opened"])
        self.assertEqual(self.stored().discord_channel_id, int(CHANNEL))

    async def test_a_channel_outside_the_guild_is_refused(self) -> None:
        """Otherwise workspace A points the bot at workspace B's server."""
        self.workspace()

        answer = await self.update(
            {"discord_channel_id": CHANNEL, "broadcast_kinds": []},
            channels=[{"id": "333333333333333333", "name": "elsewhere"}],
        )

        self.assertFalse(answer["ok"], answer)
        self.assertEqual(answer["error"]["code"], "unprocessable")
        self.assertIsNone(self.stored())

    async def test_a_channel_without_a_linked_guild_is_refused(self) -> None:
        """Nothing to check the channel against means nothing may be stored."""
        self.workspace(guild_id=None)

        answer = await self.update({"discord_channel_id": CHANNEL, "broadcast_kinds": []})

        self.assertFalse(answer["ok"], answer)
        self.assertEqual(answer["error"]["code"], "conflict")
        self.assertIn("discord_guild_not_linked", str(answer["error"]))
        self.assertIsNone(self.stored())

    async def test_an_unreachable_discord_does_not_store_an_unchecked_channel(self) -> None:
        self.workspace()

        answer = await self.update(
            {"discord_channel_id": CHANNEL, "broadcast_kinds": []},
            channels=DiscordUnavailable("bot is down"),
        )

        self.assertEqual(answer["error"]["code"], "unavailable", answer)
        self.assertIsNone(self.stored())

    async def test_clearing_the_channel_needs_no_discord_round_trip(self) -> None:
        """Turning delivery off must work while the bot is offline."""
        self.workspace()

        answer = await self.update(
            {"discord_channel_id": None, "broadcast_kinds": ["registration.opened"]},
            channels=DiscordUnavailable("bot is down"),
        )

        self.assertTrue(answer["ok"], answer)
        self.assertIsNone(answer["data"]["discord_channel_id"])

    async def test_a_kind_that_cannot_be_broadcast_is_refused(self) -> None:
        """Personal kinds in a channel would publish one person's business."""
        self.workspace()

        answer = await self.update({"broadcast_kinds": ["team_invite.received"]})

        self.assertFalse(answer["ok"], answer)
        self.assertEqual(answer["error"]["code"], "unprocessable")

    async def test_an_unknown_locale_is_refused(self) -> None:
        self.workspace()

        answer = await self.update({"locale": "de", "broadcast_kinds": []})

        self.assertEqual(answer["error"]["code"], "unprocessable", answer)

    async def test_a_missing_workspace_is_a_404(self) -> None:
        answer = await self.call(
            "rpc.app.workspaces.notification_config_get",
            {"workspace_id": str(WORKSPACE), "identity": _OWNER},
        )

        self.assertEqual(answer["error"]["code"], "not_found", answer)


class ContractTests(IsolatedAsyncioTestCase):
    """Registered, documented and typed: an unregistered subject only shows up
    as a gateway timeout, and one missing from ``OPERATIONS`` degrades to a
    generic ``object`` in the published manifest."""

    _SUBJECTS = (
        "rpc.app.notification_preferences_get",
        "rpc.app.notification_preferences_update",
        "rpc.app.admin_user_notifications_get",
        "rpc.app.admin_user_notification_preferences_update",
        "rpc.app.workspaces.notification_config_get",
        "rpc.app.workspaces.notification_config_update",
    )

    def test_registered_documented_and_typed(self) -> None:
        from src import openapi_docs, openapi_schemas

        registered: dict[str, object] = {}
        broker = MagicMock()

        def capture(subject: str, *args: Any, **kwargs: Any):
            def decorator(fn):
                registered[subject] = fn
                return fn

            return decorator

        broker.subscriber = capture
        notifications_rpc.register(broker, MagicMock())
        notifications_admin_rpc.register(broker, MagicMock())
        workspaces_rpc.register(broker, MagicMock())

        for subject in self._SUBJECTS:
            with self.subTest(subject=subject):
                self.assertIn(subject, registered)
                self.assertTrue(openapi_docs.DOCS[subject]["summary"])
                self.assertIn(subject, openapi_schemas.OPERATIONS)
