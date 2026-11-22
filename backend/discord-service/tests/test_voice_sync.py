"""``VoiceSync``: when a sync runs, and what applying a diff leaves in Discord calls and rows.

Fakes only: a guild double that records its calls, a session double that records its rows.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from src.services import voice_diff as vd
from src.services.guild_queue import GuildQueues
from src.services.voice_sync import VoiceSync, _Apply


def _sync() -> VoiceSync:
    return VoiceSync(bot=MagicMock(wait_until_ready=AsyncMock()), session_maker=MagicMock(), queues=GuildQueues())


async def _settle(sync: VoiceSync) -> None:
    while sync._runners:
        await asyncio.gather(*list(sync._runners.values()))


class TriggerTests(IsolatedAsyncioTestCase):
    async def test_a_burst_is_one_sync_and_a_request_mid_sync_is_one_follow_up(self) -> None:
        sync, runs = _sync(), []

        async def one_sync(tournament_id: int) -> None:
            runs.append(tournament_id)
            if len(runs) == 1:  # asked again, twice, while this one runs
                sync.request(tournament_id)
                sync.request(tournament_id)

        sync._sync = one_sync
        with patch("src.services.voice_sync.DEBOUNCE_SECONDS", 0):
            for _ in range(3):
                sync.request(5, explicit=True)
            await _settle(sync)

        self.assertEqual(runs, [5, 5])

    async def test_a_tournament_the_bot_never_heard_of_is_ignored_until_asked_explicitly(self) -> None:
        sync, runs = _sync(), []
        sync._sync = AsyncMock(side_effect=lambda tid: runs.append(tid))

        with patch("src.services.voice_sync.DEBOUNCE_SECONDS", 0):
            sync.request(7)  # a cache invalidation of a tournament with no voice
            await _settle(sync)
            self.assertEqual(runs, [])
            sync.request(7, explicit=True)
            await _settle(sync)
            sync.request(7)  # known now
            await _settle(sync)

        self.assertEqual(runs, [7, 7])


class _Guild:
    """Records what the bot asks of Discord; hands out ids from 500."""

    def __init__(self) -> None:
        self.id = 9
        self.me = MagicMock(id=1)
        self.next_id = 500
        self.calls: list[tuple] = []
        self.channels: dict[int, MagicMock] = {}

    def _made(self, kind: str, name: str, **fields) -> MagicMock:
        self.next_id += 1
        channel = MagicMock(id=self.next_id, edit=AsyncMock(), move=AsyncMock())
        self.channels[channel.id] = channel
        self.calls.append((kind, name, fields))
        return channel

    async def create_category(self, name: str, **fields) -> MagicMock:
        return self._made("category", name, **fields)

    async def create_voice_channel(self, name: str, **fields) -> MagicMock:
        return self._made("voice", name, **fields)

    def get_channel(self, channel_id: int):
        return self.channels.get(channel_id)

    def get_role(self, role_id: int):
        return MagicMock(id=role_id)

    def get_member(self, member_id: int):
        return None


def _apply(guild: _Guild, sync: VoiceSync | None = None) -> tuple[_Apply, MagicMock, dict]:
    session = MagicMock(add=MagicMock(), commit=AsyncMock(), delete=AsyncMock())
    rows: dict = {}
    return _Apply(sync or _sync(), guild, session, 5, rows, {}), session, rows


class ApplyTests(IsolatedAsyncioTestCase):
    async def test_creates_the_category_then_channels_inside_it_and_records_the_rows(self) -> None:
        guild = _Guild()
        applier, session, rows = _apply(guild)

        await applier.run(
            [
                vd.CreateCategory("category:1", "Cup"),
                vd.CreateChannel("hub", "hub", "Общий · Cup", "category:1"),
                vd.CreateChannel("team:1", "team", "Team 1", "category:1", team_id=1),
            ]
        )

        category_id = rows["category:1"].discord_channel_id
        self.assertEqual(
            [(kind, name) for kind, name, _ in guild.calls],
            [("category", "Cup"), ("voice", "Общий · Cup"), ("voice", "Team 1")],
        )
        self.assertTrue(all(fields["category"].id == category_id for _, _, fields in guild.calls[1:]))
        self.assertEqual(
            {key: (row.kind, row.status, row.owned) for key, row in rows.items()},
            {
                "category:1": ("category", "active", True),
                "hub": ("hub", "active", True),
                "team:1": ("team", "active", True),
            },
        )
        self.assertEqual(applier.issues, [])

    async def test_a_private_channel_is_created_with_its_overwrites(self) -> None:
        guild = _Guild()
        applier, _, _ = _apply(guild)
        overwrites = vd.private_overwrites({}, everyone_id=100, staff_role_ids=[77], member_ids=[42], bot_id=1)
        applier._categories["category:1"] = discord.Object(10)

        await applier.run([vd.CreateChannel("team:1", "team", "Team 1", "category:1", overwrites=overwrites)])

        (_, _, fields) = guild.calls[0]
        targets = {(type(t).__name__, t.id) for t in fields["overwrites"]}
        self.assertEqual(targets, {("MagicMock", 100), ("MagicMock", 77), ("Object", 42), ("Object", 1)})

    async def test_a_failed_category_skips_its_channels_and_the_rest_goes_on(self) -> None:
        guild = _Guild()
        guild.create_category = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "no"))
        applier, _, rows = _apply(guild)

        await applier.run(
            [vd.CreateCategory("category:1", "Cup"), vd.CreateChannel("hub", "hub", "Общий", "category:1")]
        )

        self.assertEqual(rows, {})
        self.assertEqual(applier.issues, [vd.Issue("missing_permission:manage_channels")])

    async def test_a_third_rename_inside_ten_minutes_waits(self) -> None:
        guild, sync = _Guild(), _sync()
        channel = MagicMock(id=600, edit=AsyncMock())
        guild.channels[600] = channel
        applier, _, rows = _apply(guild, sync)
        rows["team:1"] = MagicMock(discord_channel_id=600)

        await applier.run([vd.EditChannel("team:1", name="A"), vd.EditChannel("team:1", name="B")])
        self.assertEqual(channel.edit.await_count, 2)
        applier = _apply(guild, sync)[0]
        applier._rows["team:1"] = rows["team:1"]
        await applier.run([vd.EditChannel("team:1", name="C")])

        self.assertEqual(channel.edit.await_count, 2)  # the third waits
        self.assertGreater(applier.retry_in, 500)

    async def test_an_open_transaction_is_committed_before_discord_is_asked(self) -> None:
        """A rate-limited Discord wait outlives the database's idle-in-transaction timeout, so no transaction may be
        open across one."""
        guild = _Guild()
        applier, session, _ = _apply(guild)
        order: list[str] = []
        session.in_transaction = MagicMock(return_value=True)
        session.commit = AsyncMock(side_effect=lambda: order.append("commit"))
        made = guild.create_voice_channel

        async def create(name: str, **fields):
            order.append("discord")
            return await made(name, **fields)

        guild.create_voice_channel = create
        applier._categories["category:1"] = discord.Object(10)

        await applier.run([vd.CreateChannel("hub", "hub", "Общий", "category:1")])

        self.assertEqual(["commit", "discord"], order[:2])


async def _run_sync(
    guild: _Guild, rows: list[MagicMock], plan: MagicMock, ops: list[vd.Op], before: dict[str, str] | None = None
) -> VoiceSync:
    """One ``_sync`` of tournament 5 against ``guild``: the plan, rows and diff given, Postgres a no-op double.
    ``before`` are the routes a previous sync left, so this one is a round change."""
    session = MagicMock(commit=AsyncMock(), in_transaction=MagicMock(return_value=False))

    @asynccontextmanager
    async def session_maker():
        yield session

    sync = VoiceSync(
        bot=MagicMock(get_guild=MagicMock(return_value=guild)), session_maker=session_maker, queues=GuildQueues()
    )
    if before is not None:
        sync._remember(5, rows, before)
    with (
        patch.object(sync, "_plan", AsyncMock(return_value=plan)),
        patch.object(sync, "_models", AsyncMock(return_value=rows)),
        patch.object(sync, "_report", AsyncMock()),
        patch.object(VoiceSync, "_permission_issues", return_value=[]),
        patch("src.services.voice_sync.observe"),
        patch.object(vd, "diff", return_value=vd.Diff(ops=ops)),
    ):
        await sync._sync(5)
    return sync


def _slots(guild: _Guild, *channels: MagicMock) -> list[MagicMock]:
    guild.channels.update({channel.id: channel for channel in channels})
    return [
        MagicMock(slot_key=f"slot:1:{index}", kind="swiss_slot", discord_channel_id=channel.id)
        for index, channel in enumerate(channels)
    ]


class SyncRoutingTests(IsolatedAsyncioTestCase):
    async def test_a_rejected_overwrite_routes_nobody_to_that_slot(self) -> None:
        """A private lobby whose new overwrites Discord refused still admits the last round's roster: nobody is
        routed or moved into it until a later sync writes them."""
        guild = _Guild()
        refused = MagicMock(id=700, edit=AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "no")))
        granted = MagicMock(id=701, edit=AsyncMock())
        rows = _slots(guild, refused, granted)
        overwrites = {("member", 42): (1024, 0)}
        plan = MagicMock(guild_id="9", routes={"42": "slot:1:0", "43": "slot:1:1"}, channels=[])

        sync = await _run_sync(
            guild,
            rows,
            plan,
            [vd.EditChannel("slot:1:0", overwrites=overwrites), vd.EditChannel("slot:1:1", overwrites=overwrites)],
        )

        granted.edit.assert_awaited_once()
        self.assertEqual({"43": "slot:1:1"}, sync._routes[5])

    async def test_a_channel_is_renamed_before_the_round_moves_a_player_into_it(self) -> None:
        """A player arriving in their new lobby sees it already named after their match."""
        guild, order = _Guild(), []
        player = MagicMock(id=42, move_to=AsyncMock(side_effect=lambda *_, **__: order.append("move")))
        target = MagicMock(id=700, members=[], edit=AsyncMock(side_effect=lambda **_: order.append("rename")))
        sitting = MagicMock(id=701, members=[player], edit=AsyncMock())
        rows = _slots(guild, target, sitting)
        guild.get_member = lambda member_id: player if member_id == 42 else None
        plan = MagicMock(guild_id="9", routes={"42": "slot:1:0"}, channels=[])

        await _run_sync(guild, rows, plan, [vd.EditChannel("slot:1:0", name="Матч 1 · Команда A")], {"42": "slot:1:1"})

        self.assertEqual(["rename", "move"], order)


class HubTests(IsolatedAsyncioTestCase):
    def _hub(self, sync: VoiceSync, routes: dict[str, str]) -> tuple[MagicMock, MagicMock, MagicMock]:
        hub, lobby = MagicMock(id=100), MagicMock(id=200)
        guild = MagicMock(id=9, get_channel=lambda channel_id: {100: hub, 200: lobby}.get(channel_id))
        member = MagicMock(id=42, guild=guild, move_to=AsyncMock())
        member.voice.channel = hub
        sync._tracked = {100: 5, 200: 5}
        sync._channels = {5: {"hub": 100, "slot:1:0": 200}}
        sync._routes = {5: routes}
        return member, hub, lobby

    async def test_the_hub_sends_a_member_along_their_route(self) -> None:
        sync = _sync()
        member, hub, lobby = self._hub(sync, {"42": "slot:1:0"})

        await sync.hub_joined(member, hub)

        member.move_to.assert_awaited_once()
        self.assertIs(member.move_to.await_args.args[0], lobby)

    async def test_a_finished_match_does_not_send_its_player_back_from_the_hub_before_the_new_plan_lands(self) -> None:
        """The match ended (a sync is pending) and the player walks into the hub: the old route must not be used."""
        sync = _sync()
        member, hub, _lobby = self._hub(sync, {"42": "slot:1:0"})

        async def finished_plan(tournament_id: int) -> None:
            sync._routes[tournament_id] = {}  # the new plan gave the player no route

        sync._sync = finished_plan
        with patch("src.services.voice_sync.DEBOUNCE_SECONDS", 0.01):
            sync.request(5, explicit=True)
            await sync.hub_joined(member, hub)

        member.move_to.assert_not_awaited()
