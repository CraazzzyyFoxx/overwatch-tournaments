import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

# Importing `src.core.config` instantiates the service `Settings`, which requires
# the whole Postgres/Redis/Rabbit block on top of the Discord credentials. Without
# these the file only passed on a machine with a populated backend/.env — in CI it
# raised several missing-field ValidationErrors before a single test ran. Nothing
# here connects; the values only have to parse.
#
# The AMQP URL deliberately carries no embedded credentials (AmqpDsn accepts
# that): the `user:pass@host` form the older suites use is what GitGuardian
# reports as a leaked secret, and a placeholder is not worth a security finding
# on every PR.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from src.cogs.membership import MembershipEventsCog  # noqa: E402
from src.rabbit.gateway import DiscordRabbitGateway  # noqa: E402
from src.services.directory import DiscordDirectoryService  # noqa: E402


def _registered_handlers() -> dict[str, object]:
    """Run the real registration and index the handlers by queue name.

    ``*extra`` matters: the match-log result subscriber is bound to an exchange
    as a second positional argument, and a one-arg fake silently made it look
    like that subscriber did not exist.
    """
    gateway = DiscordRabbitGateway(
        settings=MagicMock(),
        processor=MagicMock(),
        registry=MagicMock(),
        directory=MagicMock(),
        result_waiter=MagicMock(),
        bot=MagicMock(wait_until_ready=AsyncMock()),
        session_maker=MagicMock(),
    )

    handlers: dict[str, object] = {}

    def fake_subscriber(queue, *extra):
        def decorator(fn):
            handlers[getattr(queue, "name", str(queue))] = fn
            return fn

        return decorator

    fake_broker = MagicMock()
    fake_broker.subscriber = fake_subscriber
    gateway._register(fake_broker)
    return handlers


def _role(
    role_id: int, *, default: bool = False, position: int = 1, managed: bool = False, name: str = "role", color: int = 0
):
    role = MagicMock(id=role_id, position=position, managed=managed)
    role.name = name
    role.color.value = color
    role.is_default.return_value = default
    return role


def _http_exception():
    return discord.HTTPException(MagicMock(status=404), "not found")


class HandlerRegistrationTests(IsolatedAsyncioTestCase):
    def test_match_log_result_subscriber_is_registered(self) -> None:
        """Regression: it was once nested in an unrelated module-level function.

        Nothing then consumed MATCH_LOG_RESULT_EXCHANGE, so every attachment
        upload waited out the full 120s result timeout instead of getting its
        parser verdict -- and the handler's own `broker` reference was undefined.
        """
        names = {getattr(h, "__name__", "") for h in _registered_handlers().values()}
        self.assertIn("handle_match_log_result", names)
        self.assertIn("handle_discord_command", names)


class DirectoryServiceTests(IsolatedAsyncioTestCase):
    async def test_get_member_roles_success(self) -> None:
        everyone = _role(999, default=True)
        role1 = _role(100)
        role2 = _role(200)
        fake_member = MagicMock(id=111, roles=[everyone, role1, role2])
        fake_guild = MagicMock(id=999, roles=[everyone, role1, role2])
        fake_guild.get_member.side_effect = lambda uid: fake_member if uid == 111 else None
        fake_guild.fetch_member = AsyncMock(side_effect=lambda uid: fake_member if uid == 111 else None)

        mock_client = MagicMock(get_guild=MagicMock(return_value=fake_guild))
        directory = DiscordDirectoryService(mock_client)

        outcome = await directory.get_member_roles("999", ["111", "222"])

        # The guild role list keeps @everyone (the drift check compares against
        # it), but the member's own roles drop it to match what Discord's REST
        # member object returns on the HTTP fallback path.
        self.assertEqual(outcome.status, "success")
        self.assertEqual(outcome.payload["guild_role_ids"], ["999", "100", "200"])
        self.assertTrue(outcome.payload["members"]["111"]["found"])
        self.assertEqual(outcome.payload["members"]["111"]["roles"], ["100", "200"])
        self.assertFalse(outcome.payload["members"]["222"]["found"])

    async def test_get_member_roles_reports_unknown_guild(self) -> None:
        mock_client = MagicMock()
        mock_client.get_guild.return_value = None
        mock_client.fetch_guild = AsyncMock(side_effect=_http_exception())
        directory = DiscordDirectoryService(mock_client)

        outcome = await directory.get_member_roles("999", ["111"])

        self.assertEqual(outcome.status, "guild_not_found")
        self.assertEqual(outcome.payload["error"], "guild_not_found")
        self.assertEqual(outcome.payload["members"], {})

    async def test_get_guild_roles_success(self) -> None:
        admin = _role(100, position=2, name="Admin", color=0xFF0000)
        member = _role(200, position=1, name="Member", color=0)
        fake_guild = MagicMock(id=999, roles=[member, admin])
        mock_client = MagicMock(get_guild=MagicMock(return_value=fake_guild))
        directory = DiscordDirectoryService(mock_client)

        outcome = await directory.get_guild_roles("999")

        self.assertEqual(outcome.payload["guild_id"], "999")
        self.assertEqual(outcome.payload["roles"][0]["name"], "Admin")
        self.assertEqual(outcome.payload["roles"][0]["color"], "#ff0000")
        self.assertIsNone(outcome.payload["roles"][1]["color"])

    async def test_get_guild_channels_lists_every_kind_with_missing_permissions(self) -> None:
        category = MagicMock(spec=discord.CategoryChannel, id=10, category_id=None, position=0)
        category.name = "MIX"
        text = MagicMock(spec=discord.TextChannel, id=11, category_id=10, position=1)
        text.name = "lineups"
        voice = MagicMock(spec=discord.VoiceChannel, id=12, category_id=10, position=2)
        voice.name = "Team 1"
        granted = MagicMock(view_channel=True, connect=True, move_members=False)
        voice.permissions_for = MagicMock(return_value=granted)
        category.permissions_for = MagicMock(return_value=MagicMock(view_channel=True, connect=True, move_members=True))
        guild = MagicMock(id=999, channels=[voice, text, category], me=MagicMock())
        directory = DiscordDirectoryService(MagicMock(get_guild=MagicMock(return_value=guild)))

        outcome = await directory.get_guild_channels("999")

        self.assertEqual(outcome.status, "success")
        self.assertEqual(
            outcome.payload["channels"],
            [
                {
                    "id": "10",
                    "name": "MIX",
                    "type": "category",
                    "category_id": None,
                    "category_name": None,
                    "position": 0,
                    "missing_permissions": [],
                },
                {
                    "id": "11",
                    "name": "lineups",
                    "type": "text",
                    "category_id": "10",
                    "category_name": "MIX",
                    "position": 1,
                    "missing_permissions": None,
                },
                {
                    "id": "12",
                    "name": "Team 1",
                    "type": "voice",
                    "category_id": "10",
                    "category_name": "MIX",
                    "position": 2,
                    "missing_permissions": ["move_members"],
                },
            ],
        )

    async def test_get_guild_channels_fetches_for_uncached_guild(self) -> None:
        """A fetched guild has no channel cache and no ``me``: channels come over
        REST, and the bot's permissions are unknown rather than "all granted"."""
        voice = MagicMock(spec=discord.VoiceChannel, id=12, category_id=None, position=0)
        voice.name = "General"
        stage = MagicMock(spec=discord.StageChannel, id=13, category_id=None, position=1)
        stage.name = "Stage"
        guild = MagicMock(id=999, channels=[])
        guild.fetch_channels = AsyncMock(return_value=[voice, stage])
        client = MagicMock(get_guild=MagicMock(return_value=None), fetch_guild=AsyncMock(return_value=guild))

        outcome = await DiscordDirectoryService(client).get_guild_channels("999")

        self.assertEqual(
            outcome.payload["channels"],
            [
                {
                    "id": "12",
                    "name": "General",
                    "type": "voice",
                    "category_id": None,
                    "category_name": None,
                    "position": 0,
                    "missing_permissions": None,
                }
            ],
        )

    async def test_get_guild_info_success(self) -> None:
        owner = MagicMock(display_name="Ada", display_avatar=MagicMock(url="http://owner.png"))
        fake_guild = MagicMock(
            id=999,
            member_count=42,
            icon=MagicMock(url="http://icon.png"),
            owner_id=42,
            owner=owner,
        )
        fake_guild.name = "Test Server"
        mock_client = MagicMock(get_guild=MagicMock(return_value=fake_guild))
        directory = DiscordDirectoryService(mock_client)

        outcome = await directory.get_guild_info("999")

        self.assertEqual(outcome.payload["guild_id"], "999")
        self.assertTrue(outcome.payload["connected"])
        self.assertEqual(outcome.payload["name"], "Test Server")
        self.assertEqual(outcome.payload["member_count"], 42)
        self.assertEqual(outcome.payload["owner_id"], "42")
        self.assertEqual(outcome.payload["owner_name"], "Ada")
        self.assertEqual(outcome.payload["owner_avatar_url"], "http://owner.png")

    async def test_get_guild_info_uses_approximate_count_when_uncached(self) -> None:
        """``member_count`` is gateway-only; a fetched guild would report 0."""
        fake_guild = MagicMock(id=999, member_count=None, approximate_member_count=7, icon=None)
        fake_guild.name = "Test Server"
        mock_client = MagicMock()
        mock_client.get_guild.return_value = None
        mock_client.fetch_guild = AsyncMock(return_value=fake_guild)
        directory = DiscordDirectoryService(mock_client)

        outcome = await directory.get_guild_info("999")

        self.assertTrue(outcome.payload["connected"])
        self.assertEqual(outcome.payload["member_count"], 7)
        self.assertIsNone(outcome.payload["icon_url"])


class MembershipEventsCogTests(IsolatedAsyncioTestCase):
    async def test_on_member_update_triggers_subscription_change(self) -> None:
        r1 = MagicMock(id=100)
        r2 = MagicMock(id=200)

        before = MagicMock(id=111, roles=[r1], guild=MagicMock(id=999))
        after = MagicMock(id=111, roles=[r1, r2], guild=MagicMock(id=999))

        bot = MagicMock()
        bot.subscription_sync.resync = AsyncMock()
        cog = MembershipEventsCog(bot)

        await cog.on_member_update(before, after)

        bot.subscription_sync.resync.assert_awaited_once_with("999", "111", "role_update")
