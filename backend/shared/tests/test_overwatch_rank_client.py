from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

import httpx

from shared.core import enums
from shared.disciplines.overwatch.collector import client as client_mod

OverFastRankClient = client_mod.OverFastRankClient
OverFastError = client_mod.OverFastError
OverFastRateLimited = client_mod.OverFastRateLimited


def _make_client(response: httpx.Response | Exception) -> OverFastRankClient:
    c = OverFastRankClient("http://overfast.local")
    if isinstance(response, Exception):
        c._http.get = AsyncMock(side_effect=response)
    else:
        c._http.get = AsyncMock(return_value=response)
    return c


class ParseCompetitiveTests(IsolatedAsyncioTestCase):
    def test_to_player_id(self) -> None:
        self.assertEqual(client_mod.to_player_id("TeKrop#2217"), "TeKrop-2217")

    def test_parse_skips_absent_platform_and_flags_unranked_role(self) -> None:
        comp = {
            "pc": {
                "season": 13,
                "tank": {"division": "diamond", "tier": 3},
                "damage": None,
                "support": {"division": "master", "tier": 5},
            },
            "console": None,
        }
        ranks = client_mod.parse_competitive(comp)
        # PC only: 3 roles; console skipped entirely.
        self.assertEqual(len(ranks), 3)
        by_role = {r.role: r for r in ranks}
        self.assertTrue(by_role["tank"].is_ranked)
        self.assertEqual(by_role["tank"].division, "diamond")
        self.assertFalse(by_role["damage"].is_ranked)
        self.assertIsNone(by_role["damage"].division)
        self.assertEqual(by_role["support"].season, 13)

    def test_parse_empty(self) -> None:
        self.assertEqual(client_mod.parse_competitive(None), [])
        self.assertEqual(client_mod.parse_competitive({}), [])


class FetchProfileStatusTests(IsolatedAsyncioTestCase):
    async def test_ok_with_ranks(self) -> None:
        payload = {"summary": {"competitive": {"pc": {"season": 1, "tank": {"division": "gold", "tier": 2}}}}}
        c = _make_client(httpx.Response(200, json=payload))
        result = await c.fetch_profile("Name#1234")
        self.assertEqual(result.status, enums.RankCollectionStatus.ok)
        self.assertEqual(len(result.ranks), 3)
        self.assertEqual(c._http.get.await_args.args[0], "/players/Name-1234")

    async def test_unranked_public_profile_is_private_but_still_carries_its_career(self) -> None:
        payload = {
            "summary": {"username": "Name", "competitive": None, "last_updated_at": 1_700_000_000},
            "stats": {
                "pc": {
                    "quickplay": {
                        "career_stats": {
                            "ana": [{"category": "game", "stats": [{"key": "time_played", "value": 3600}]}]
                        }
                    },
                    "competitive": None,
                },
                "console": None,
            },
        }
        c = _make_client(httpx.Response(200, json=payload))
        result = await c.fetch_profile("Name#1234")
        self.assertEqual(result.status, enums.RankCollectionStatus.private)
        self.assertEqual(result.ranks, [])
        self.assertEqual(result.profile.display_name, "Name")
        self.assertEqual(
            [(s.platform, s.queue, s.character, s.stats) for s in result.career],
            [("pc", "quickplay", "ana", {"game": {"time_played": 3600}})],
        )

    async def test_a_blizzard_id_is_read_by_its_encoded_path(self) -> None:
        c = _make_client(httpx.Response(200, json={"summary": {"competitive": None}}))
        await c.fetch_profile("df51a381fe20caf8baa7|0bf3b4c47cbebe84b8db9c676a4e9c1f")
        self.assertEqual(
            c._http.get.await_args.args[0], "/players/df51a381fe20caf8baa7%7C0bf3b4c47cbebe84b8db9c676a4e9c1f"
        )

    async def test_a_payload_without_summary_is_a_transient_failure(self) -> None:
        """A changed upstream shape must back off, never count toward auto-disabling every account."""
        c = _make_client(httpx.Response(200, json={"competitive": None}))
        with self.assertRaises(OverFastError):
            await c.fetch_profile("Name#1234")

    async def test_not_found(self) -> None:
        c = _make_client(httpx.Response(404))
        result = await c.fetch_profile("Name#1234")
        self.assertEqual(result.status, enums.RankCollectionStatus.not_found)

    async def test_rate_limited_raises_with_retry_after(self) -> None:
        c = _make_client(httpx.Response(429, headers={"Retry-After": "30"}))
        with self.assertRaises(OverFastRateLimited) as ctx:
            await c.fetch_profile("Name#1234")
        self.assertEqual(ctx.exception.retry_after, 30.0)

    async def test_server_error_raises(self) -> None:
        c = _make_client(httpx.Response(503))
        with self.assertRaises(OverFastError):
            await c.fetch_profile("Name#1234")

    async def test_transport_error_raises_overfast_error(self) -> None:
        c = _make_client(httpx.ConnectError("boom"))
        with self.assertRaises(OverFastError):
            await c.fetch_profile("Name#1234")

    async def test_malformed_battle_tag_is_rejected_without_request(self) -> None:
        c = _make_client(httpx.Response(200, json={"summary": {"competitive": {}}}))
        for bad in ("../../etc/passwd", "Name#1234/../secret", "Na me#1234", "Name-1234", "DF51|0BF3/../x"):
            result = await c.fetch_profile(bad)
            self.assertEqual(result.status, enums.RankCollectionStatus.error)
        c._http.get.assert_not_called()


class HeroRatesTests(IsolatedAsyncioTestCase):
    async def test_a_slice_the_game_does_not_offer_is_none_not_an_error(self) -> None:
        c = _make_client(httpx.Response(400, json={"error": "map not in competitive"}))
        self.assertIsNone(await c.fetch_character_rates({"map": "hanaoka"}))
