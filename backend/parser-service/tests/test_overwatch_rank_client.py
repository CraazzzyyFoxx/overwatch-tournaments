from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

import httpx

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "x")
os.environ.setdefault("CHALLONGE_API_KEY", "x")

client_mod = importlib.import_module("src.services.overwatch_rank.client")
from shared.core import enums  # noqa: E402

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


class FetchSummaryStatusTests(IsolatedAsyncioTestCase):
    async def test_ok_with_ranks(self) -> None:
        payload = {"competitive": {"pc": {"season": 1, "tank": {"division": "gold", "tier": 2}}}}
        c = _make_client(httpx.Response(200, json=payload))
        result = await c.fetch_summary("Name#1234")
        self.assertEqual(result.status, enums.RankCollectionStatus.ok)
        self.assertEqual(len(result.ranks), 3)

    async def test_private_when_competitive_empty(self) -> None:
        c = _make_client(httpx.Response(200, json={"competitive": None}))
        result = await c.fetch_summary("Name#1234")
        self.assertEqual(result.status, enums.RankCollectionStatus.private)
        self.assertEqual(result.ranks, [])

    async def test_not_found(self) -> None:
        c = _make_client(httpx.Response(404))
        result = await c.fetch_summary("Name#1234")
        self.assertEqual(result.status, enums.RankCollectionStatus.not_found)

    async def test_rate_limited_raises_with_retry_after(self) -> None:
        c = _make_client(httpx.Response(429, headers={"Retry-After": "30"}))
        with self.assertRaises(OverFastRateLimited) as ctx:
            await c.fetch_summary("Name#1234")
        self.assertEqual(ctx.exception.retry_after, 30.0)

    async def test_server_error_raises(self) -> None:
        c = _make_client(httpx.Response(503))
        with self.assertRaises(OverFastError):
            await c.fetch_summary("Name#1234")

    async def test_transport_error_raises_overfast_error(self) -> None:
        c = _make_client(httpx.ConnectError("boom"))
        with self.assertRaises(OverFastError):
            await c.fetch_summary("Name#1234")
