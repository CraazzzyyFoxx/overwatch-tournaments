"""Behavioural pins for the two notification settings surfaces.

Both are "who may change what": the personal DM switches are self-service and
may only ever edit the caller's own row, and the workspace delivery config
decides which Discord channel the bot is made to speak in -- which is why a
channel outside the workspace's own verified guild has to be refused rather
than stored.

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

from shared.models.identity.oauth import OAuthConnection  # noqa: E402
from shared.models.platform.notification import NotificationPreference, NotificationWorkspaceConfig  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.services.discord_client import DiscordClient  # noqa: E402
from shared.services.notifications import NOTIFICATION_GROUPS  # noqa: E402
from shared.services.subscriptions.providers.discord_role import DiscordUnavailable  # noqa: E402
from shared.testing import install_postgres_type_shims  # noqa: E402
from src import schemas  # noqa: E402
from src.rpc import notifications as notifications_rpc  # noqa: E402
from src.rpc import workspaces as workspaces_rpc  # noqa: E402

install_postgres_type_shims()

TABLES = (
    NotificationPreference.__table__,
    NotificationWorkspaceConfig.__table__,
    OAuthConnection.__table__,
    Workspace.__table__,
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
    """Engine + captured subscribers for both RPC modules."""

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
        workspaces_rpc.register(broker, MagicMock())
        for module in (notifications_rpc, workspaces_rpc):
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
        workspaces_rpc.register(broker, MagicMock())

        for subject in self._SUBJECTS:
            with self.subTest(subject=subject):
                self.assertIn(subject, registered)
                self.assertTrue(openapi_docs.DOCS[subject]["summary"])
                self.assertIn(subject, openapi_schemas.OPERATIONS)
