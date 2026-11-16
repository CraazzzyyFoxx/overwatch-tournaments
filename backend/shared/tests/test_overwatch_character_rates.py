"""The daily hero-rates tick against the test DB: one day per slice, written once, nothing while collection is off."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.disciplines.overwatch.collector import character_rates
from shared.schemas.settings import RankCollectionConfig
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres

RATES = [
    {"hero": "ana", "pickrate": 35.7, "winrate": 46.8, "banrate": 9.5},
    {"hero": "anran", "pickrate": 5.2, "winrate": 49.7, "banrate": None},
]


def _rates(params: dict[str, str]) -> list[dict] | None:
    # A quick-play-only map: OverFast answers 400 for it in competitive.
    return None if params.get("map") == "hanaoka" else RATES


class CharacterRatesTickDbTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.day = datetime.now(UTC).date()
        await self._clear()
        self.client = SimpleNamespace(
            fetch_map_keys=AsyncMock(return_value=["kings-row", "hanaoka"]),
            fetch_character_rates=AsyncMock(side_effect=_rates),
        )

    async def asyncTearDown(self) -> None:
        await self._clear()
        await self.engine.dispose()

    async def _clear(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.CharacterRate).where(models.CharacterRate.captured_on == self.day))
            await s.commit()

    async def _tick(self, *, enabled: bool = True) -> int:
        with patch.object(
            character_rates.settings_provider,
            "get_rank_collection_config",
            AsyncMock(return_value=RankCollectionConfig(enabled=enabled, rate_limit_per_minute=1000)),
        ):
            return await character_rates.run_tick(
                redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
                session_factory=self.Session,
                client=self.client,
            )

    async def test_a_day_is_every_offered_slice_once(self) -> None:
        # quick play + competitive overall + 8 divisions + kings-row; hanaoka is not offered in competitive.
        self.assertEqual(await self._tick(), 11 * len(RATES))
        self.assertEqual(await self._tick(), 0)
        self.assertEqual(self.client.fetch_map_keys.await_count, 1)

        async with self.Session() as s:
            rate = models.CharacterRate
            rows = (
                await s.execute(
                    sa.select(rate.queue, rate.division, rate.map, rate.banrate).where(
                        rate.captured_on == self.day, rate.character == "anran"
                    )
                )
            ).all()
        self.assertEqual(len(rows), 11)
        self.assertIn(("competitive", None, "kings-row", None), rows)
        self.assertIn(("competitive", "grandmaster", None, None), rows)

    async def test_nothing_is_asked_while_collection_is_off(self) -> None:
        self.assertEqual(await self._tick(enabled=False), 0)
        self.client.fetch_map_keys.assert_not_awaited()
