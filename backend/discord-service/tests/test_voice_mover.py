"""``VoiceMover``: who Discord will actually move, and what it answers for the rest.

Stdlib unittest with a faked gateway cache -- no network, no discord.py client.
"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

import discord

from src.services.voice import VoiceMover


def _voice(channel_id: int, category_id: int | None = 10) -> MagicMock:
    channel = MagicMock(spec=discord.VoiceChannel, id=channel_id, category_id=category_id)
    channel.members = []
    return channel


def _member(user_id: int, in_channel: MagicMock | None) -> MagicMock:
    member = MagicMock(id=user_id, display_name=f"u{user_id}")
    member.voice = MagicMock(channel=in_channel) if in_channel is not None else None
    member.move_to = AsyncMock()
    return member


def _guild(channels: list[MagicMock], members: list[MagicMock]) -> MagicMock:
    by_channel = {c.id: c for c in channels}
    by_member = {m.id: m for m in members}
    return MagicMock(get_channel=by_channel.get, get_member=by_member.get)


class VoiceMoverTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.general, self.team1 = _voice(1), _voice(2)
        self.elsewhere = _voice(3, category_id=99)

    def _mover(self, guild: MagicMock) -> VoiceMover:
        return VoiceMover(MagicMock(get_guild=MagicMock(return_value=guild)))

    async def test_moves_a_member_connected_inside_the_category(self) -> None:
        ana = _member(7, self.general)
        guild = _guild([self.general, self.team1], [ana])

        outcome = await self._mover(guild).move(
            "5", category_id="10", moves=[{"discord_user_id": "7", "channel_id": "2"}], drain=None
        )

        ana.move_to.assert_awaited_once_with(self.team1, reason="OWT mix")
        self.assertEqual(
            outcome.payload["results"],
            [{"discord_user_id": "7", "name": "u7", "channel_id": "2", "status": "moved"}],
        )

    async def test_leaves_people_outside_the_category_alone(self) -> None:
        busy, gone = _member(7, self.elsewhere), _member(8, None)
        guild = _guild([self.team1, self.elsewhere], [busy, gone])

        outcome = await self._mover(guild).move(
            "5",
            category_id="10",
            moves=[
                {"discord_user_id": "7", "channel_id": "2"},
                {"discord_user_id": "8", "channel_id": "2"},
                {"discord_user_id": "9", "channel_id": "2"},
            ],
            drain=None,
        )

        busy.move_to.assert_not_awaited()
        self.assertEqual([r["status"] for r in outcome.payload["results"]], ["not_in_voice"] * 3)

    async def test_a_target_outside_the_category_is_refused(self) -> None:
        ana = _member(7, self.general)
        guild = _guild([self.general, self.elsewhere], [ana])

        outcome = await self._mover(guild).move(
            "5", category_id="10", moves=[{"discord_user_id": "7", "channel_id": "3"}], drain=None
        )

        ana.move_to.assert_not_awaited()
        self.assertEqual(outcome.payload["results"][0]["status"], "channel_outside_category")

    async def test_forbidden_is_missing_permission(self) -> None:
        ana = _member(7, self.general)
        ana.move_to.side_effect = discord.Forbidden(MagicMock(status=403), "Missing Permissions")
        outcome = await self._mover(_guild([self.general, self.team1], [ana])).move(
            "5", category_id="10", moves=[{"discord_user_id": "7", "channel_id": "2"}], drain=None
        )
        self.assertEqual(outcome.payload["results"][0]["status"], "missing_permission")

    async def test_drain_moves_everyone_in_the_sources(self) -> None:
        a, b = _member(7, self.team1), _member(8, self.team1)
        self.team1.members = [a, b]
        guild = _guild([self.general, self.team1], [a, b])

        outcome = await self._mover(guild).move(
            "5", category_id="10", moves=[], drain={"channel_ids": ["2"], "to_channel_id": "1"}
        )

        a.move_to.assert_awaited_once_with(self.general, reason="OWT mix")
        b.move_to.assert_awaited_once_with(self.general, reason="OWT mix")
        self.assertEqual([r["status"] for r in outcome.payload["results"]], ["moved", "moved"])

    async def test_unknown_guild_is_not_found(self) -> None:
        outcome = await VoiceMover(MagicMock(get_guild=MagicMock(return_value=None))).move(
            "5", category_id="10", moves=[], drain=None
        )
        self.assertEqual(outcome.status, "guild_not_found")
