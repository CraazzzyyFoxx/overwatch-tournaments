"""Publish order for a mix's Discord commands: announce, refresh, delete.

A queued Discord command cannot be recalled: once it is on the broker the bot
runs it, whatever the database ends up saying. So the row it names has to be
durable BEFORE the command goes out -- otherwise a failed commit leaves a post
in the channel that nothing of ours knows about, and a signup card whose every
button answers ``signup_closed``. Same commit-then-publish order the achievement
runner uses (``parser-service/src/services/achievement/engine/runner.py``).

The same rule governs every later command about that message: the refresh of a
live card, the delete of one the host took down, and the deletes that follow a
mix being destroyed all publish after the transaction they describe.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.schemas.events import DiscordCard, DiscordCommandEvent  # noqa: E402
from src.rpc import custom  # noqa: E402

SUBJECT = "rpc.balancer.custom.post_signup"
WORKSPACE_ID = 9
GAME_ID = 11


class _CapturingBroker:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def subscriber(self, subject: str):
        def decorator(function):
            self.handlers[subject] = function
            return function

        return decorator


class _FakeLogger:
    def warning(self, *args, **kwargs) -> None:
        return None

    def exception(self, *args, **kwargs) -> None:
        return None


class _Session:
    """A session that records the order of everything the handler does to it."""

    def __init__(self, calls: list[str], *, commit_fails: bool = False) -> None:
        self.calls = calls
        self.commit_fails = commit_fails

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def commit(self) -> None:
        self.calls.append("commit")
        if self.commit_fails:
            raise RuntimeError("commit failed")


def _identity() -> dict:
    return {
        "user_id": 501,
        "is_superuser": False,
        "is_active": True,
        "roles": [],
        "permissions": [],
        "workspaces": [
            {
                "workspace_id": WORKSPACE_ID,
                "role": "organizer",
                "rbac_roles": ["organizer"],
                "rbac_permissions": [{"resource": "custom_game", "action": "update"}],
            }
        ],
    }


def _card() -> DiscordCard:
    return DiscordCard(text="**Запись на микс**")


def _post(message_ref: int = 31) -> DiscordCommandEvent:
    return DiscordCommandEvent(action="post_message", channel_id=555, message_ref=message_ref, card=_card())


def _delete(message_ref: int) -> DiscordCommandEvent:
    return DiscordCommandEvent(action="delete_message", message_ref=message_ref)


def _edit(message_ref: int = 31) -> DiscordCommandEvent:
    return DiscordCommandEvent(action="edit_message", message_ref=message_ref, card=_card())


class PostSignupPublishOrderTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def _call(
        self, *, commit_fails: bool, commands: list[DiscordCommandEvent] | None = None
    ) -> tuple[dict, list]:
        calls: list[str] = []
        session = _Session(calls, commit_fails=commit_fails)
        broker = _CapturingBroker()
        custom.register(broker, _FakeLogger())
        service = AsyncMock()
        service.signup_post = AsyncMock(return_value=(555, commands if commands is not None else [_post()]))
        self.publish = AsyncMock(side_effect=lambda *_a, **_kw: calls.append("publish"))
        with (
            patch.object(custom, "_SF", lambda: session),
            patch.object(custom, "custom_game_service", service),
            patch.object(custom, "publish_message", self.publish),
            patch.object(custom, "emit_pickup_mix_updated", AsyncMock()),
        ):
            data = {
                "identity": _identity(),
                "workspace_id": WORKSPACE_ID,
                "custom_game_id": GAME_ID,
                "payload": {"self_signup": "pool"},
            }
            return await broker.handlers[SUBJECT](data, None), calls

    async def test_the_card_is_queued_only_after_the_commit(self) -> None:
        result, calls = await self._call(commit_fails=False)

        self.assertTrue(result["ok"], result)
        self.assertEqual({"status": "queued", "channel_id": "555"}, result["data"])
        self.assertEqual(["commit", "publish"], calls)

    async def test_a_failed_commit_queues_no_card(self) -> None:
        result, calls = await self._call(commit_fails=True)

        self.assertFalse(result["ok"], result)
        self.assertEqual(["commit"], calls)
        self.publish.assert_not_awaited()

    async def test_the_old_card_is_deleted_before_the_new_one_is_posted(self) -> None:
        """The service hands the commands over in order and the handler keeps
        it: reversed, the channel would hold two signup cards at once."""
        await self._call(commit_fails=False, commands=[_delete(30), _post(31)])

        sent = [call.args[1] for call in self.publish.await_args_list]
        self.assertEqual(
            [("delete_message", 30), ("post_message", 31)], [(e["action"], e["message_ref"]) for e in sent]
        )

    async def test_the_card_names_the_row_it_was_claimed_as(self) -> None:
        """Without ``message_ref`` the post is a snapshot: nothing can edit or
        delete it later, because nothing knows which message it became."""
        await self._call(commit_fails=False)

        event = self.publish.await_args.args[1]
        self.assertEqual(31, event["message_ref"])
        self.assertEqual("post_message", event["action"])


class MixDiscordCommandTests(IsolatedAsyncioTestCase):
    """The other three publish points: the refresh, the host's delete, and the
    deletes a destroyed mix leaves behind. All after the commit."""

    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    def setUp(self) -> None:
        self.calls: list[str] = []
        self.session = _Session(self.calls)
        self.broker = _CapturingBroker()
        custom.register(self.broker, _FakeLogger())
        self.service = AsyncMock()
        self.publish = AsyncMock(side_effect=lambda *_a, **_kw: self.calls.append("publish"))
        patches = (
            patch.object(custom, "_SF", lambda: self.session),
            patch.object(custom, "custom_game_service", self.service),
            patch.object(custom, "publish_message", self.publish),
            patch.object(custom, "emit_pickup_mix_updated", AsyncMock()),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def _admin_identity(self) -> dict:
        identity = _identity()
        identity["workspaces"][0]["rbac_roles"] = ["organizer", "admin"]
        identity["workspaces"][0]["role"] = "admin"
        return identity

    async def test_leaving_a_mix_refreshes_its_live_card_after_the_commit(self) -> None:
        self.service.self_leave = AsyncMock(return_value={"seat": None})
        self.service.signup_refresh = AsyncMock(return_value=_edit())

        result = await self.broker.handlers["rpc.balancer.custom.self_leave"](
            {"identity": _identity(), "custom_game_id": GAME_ID}, None
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(["commit", "publish"], self.calls)

    async def test_a_mix_with_no_live_card_publishes_nothing(self) -> None:
        self.service.self_leave = AsyncMock(return_value={"seat": None})
        self.service.signup_refresh = AsyncMock(return_value=None)

        await self.broker.handlers["rpc.balancer.custom.self_leave"](
            {"identity": _identity(), "custom_game_id": GAME_ID}, None
        )

        self.assertEqual(["commit"], self.calls)
        self.publish.assert_not_awaited()

    async def test_deleting_a_post_publishes_after_the_commit_and_returns_the_mix(self) -> None:
        game = object()
        self.service.delete_discord_post = AsyncMock(return_value=(game, [_delete(30)]))
        with patch.object(custom, "_with_roster", AsyncMock(return_value={"id": GAME_ID})) as with_roster:
            result = await self.broker.handlers["rpc.balancer.custom.delete_discord_post"](
                {
                    "identity": _identity(),
                    "workspace_id": WORKSPACE_ID,
                    "custom_game_id": GAME_ID,
                    "post_id": 30,
                },
                None,
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual({"id": GAME_ID}, result["data"])
        self.assertEqual(["commit", "publish"], self.calls)
        self.assertEqual(30, self.service.delete_discord_post.await_args.kwargs["post_id"])
        self.assertIs(game, with_roster.await_args.args[1])

    async def test_hard_delete_takes_the_mixs_posts_down_after_the_commit(self) -> None:
        """The deletes describe a mix that is gone: published before the commit
        they could erase the channel for a deletion that then rolled back."""
        self.service.hard_delete = AsyncMock(return_value=[_delete(30), _delete(31)])

        result = await self.broker.handlers["rpc.balancer.custom.hard_delete"](
            {"identity": self._admin_identity(), "workspace_id": WORKSPACE_ID, "custom_game_id": GAME_ID}, None
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual({"id": GAME_ID}, result["data"])
        self.assertEqual(["commit", "publish", "publish"], self.calls)
        self.assertEqual([30, 31], [call.args[1]["message_ref"] for call in self.publish.await_args_list])
