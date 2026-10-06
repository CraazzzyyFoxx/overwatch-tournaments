"""A mix's Discord commands go out through the outbox, inside the transaction.

Nothing is published from a handler any more: the commands are enqueued as
``discord_commands`` outbox rows in the same transaction that claimed or
released the ``discord_message`` rows they name, and the outbox drainer sends
them only once that transaction is on disk. So a failed commit queues nothing
at all -- no post in a channel that no row of ours knows about -- and the order
the service built the commands in is the order the bot receives them (the
delete of the previous signup card before the post of its replacement).

The live card's own refresh is not here: no handler edits it. Every mutation
emits ``pickup_mix_changed`` and the projector re-renders from the committed
state (``src/services/mix_signup_projector.py``).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
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


class PostSignupOutboxTests(IsolatedAsyncioTestCase):
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
        self.enqueued: list[DiscordCommandEvent] = []
        self.enqueue = AsyncMock(side_effect=self._record(calls))
        with (
            patch.object(custom, "_SF", lambda: session),
            patch.object(custom, "custom_game_service", service),
            patch.object(custom.discord_messages, "enqueue", self.enqueue),
            patch.object(custom, "emit_pickup_mix_changed", AsyncMock()),
        ):
            data = {
                "identity": _identity(),
                "workspace_id": WORKSPACE_ID,
                "custom_game_id": GAME_ID,
                "payload": {"self_signup": "pool"},
            }
            return await broker.handlers[SUBJECT](data, None), calls

    def _record(self, calls: list[str]):
        async def _enqueue(_session, commands) -> None:
            calls.append("enqueue")
            self.enqueued.extend(commands)

        return _enqueue

    async def test_the_card_is_queued_inside_the_transaction(self) -> None:
        result, calls = await self._call(commit_fails=False)

        self.assertTrue(result["ok"], result)
        self.assertEqual({"status": "queued", "channel_id": "555"}, result["data"])
        self.assertEqual(["enqueue", "commit"], calls)

    async def test_a_failed_commit_queues_no_card(self) -> None:
        """The outbox row dies with the transaction, so nothing reaches the bot."""
        result, calls = await self._call(commit_fails=True)

        self.assertFalse(result["ok"], result)
        self.assertEqual(["enqueue", "commit"], calls)

    async def test_the_old_card_is_deleted_before_the_new_one_is_posted(self) -> None:
        """The service hands the commands over in order and the handler keeps
        it: reversed, the channel would hold two signup cards at once."""
        await self._call(commit_fails=False, commands=[_delete(30), _post(31)])

        self.assertEqual(
            [("delete_message", 30), ("post_message", 31)],
            [(event.action, event.message_ref) for event in self.enqueued],
        )

    async def test_the_card_names_the_row_it_was_claimed_as(self) -> None:
        """Without ``message_ref`` the post is a snapshot: nothing can edit or
        delete it later, because nothing knows which message it became."""
        await self._call(commit_fails=False)

        self.assertEqual([31], [event.message_ref for event in self.enqueued])
        self.assertEqual(["post_message"], [event.action for event in self.enqueued])


class MixDiscordCommandTests(IsolatedAsyncioTestCase):
    """The other command points: the host's delete, the deletes a destroyed mix
    leaves behind, and the change event a lineup move announces."""

    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    def setUp(self) -> None:
        self.calls: list[str] = []
        self.session = _Session(self.calls)
        self.broker = _CapturingBroker()
        custom.register(self.broker, _FakeLogger())
        self.service = AsyncMock()
        self.enqueued: list[DiscordCommandEvent] = []
        self.enqueue = AsyncMock(side_effect=self._record())
        self.emit = AsyncMock()
        patches = (
            patch.object(custom, "_SF", lambda: self.session),
            patch.object(custom, "custom_game_service", self.service),
            patch.object(custom.discord_messages, "enqueue", self.enqueue),
            patch.object(custom, "emit_pickup_mix_changed", self.emit),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def _record(self):
        async def _enqueue(_session, commands) -> None:
            self.calls.append("enqueue")
            self.enqueued.extend(commands)

        return _enqueue

    def _admin_identity(self) -> dict:
        identity = _identity()
        identity["workspaces"][0]["rbac_roles"] = ["organizer", "admin"]
        identity["workspaces"][0]["role"] = "admin"
        return identity

    async def test_benching_a_player_announces_the_change_for_that_mix(self) -> None:
        """The card lists the bench, so a lineup move from the site has to reach
        the channel too -- as a fact the projector re-renders from, naming the
        mix whose card it is."""
        self.service.set_participation = AsyncMock(return_value=SimpleNamespace(id=GAME_ID))
        with patch.object(custom, "_with_roster", AsyncMock(return_value={"id": GAME_ID})):
            result = await self.broker.handlers["rpc.balancer.custom.set_participation"](
                {
                    "identity": self._admin_identity(),
                    "workspace_id": WORKSPACE_ID,
                    "custom_game_id": GAME_ID,
                    "payload": {"players": [{"workspace_member_id": 7, "participation": "benched"}]},
                },
                None,
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(["commit"], self.calls)
        self.assertEqual(GAME_ID, self.emit.await_args.kwargs["custom_game_id"])
        self.assertEqual(WORKSPACE_ID, self.emit.await_args.args[1])

    async def test_deleting_a_post_queues_before_the_commit_and_returns_the_mix(self) -> None:
        game = SimpleNamespace(id=GAME_ID)
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
        self.assertEqual(["enqueue", "commit"], self.calls)
        self.assertEqual(30, self.service.delete_discord_post.await_args.kwargs["post_id"])
        self.assertIs(game, with_roster.await_args.args[1])

    async def test_hard_delete_queues_the_mixs_deletes_in_its_own_transaction(self) -> None:
        """The deletes describe a mix that is gone: queued outside its
        transaction they could erase the channel for a deletion that then
        rolled back."""
        self.service.hard_delete = AsyncMock(return_value=[_delete(30), _delete(31)])

        result = await self.broker.handlers["rpc.balancer.custom.hard_delete"](
            {"identity": self._admin_identity(), "workspace_id": WORKSPACE_ID, "custom_game_id": GAME_ID}, None
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual({"id": GAME_ID}, result["data"])
        self.assertEqual(["enqueue", "commit"], self.calls)
        self.assertEqual([30, 31], [event.message_ref for event in self.enqueued])
