"""Deadlock's rank on a match date against the test DB: per account the row held then, the best ranked account."""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.disciplines.deadlock.ranks import ranks_at
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres

_TAG = itertools.count()
NOW = datetime.now(UTC)


def _snap(user_id: int, account: int, value: int | None, days_ago: int) -> models.UserRankSnapshot:
    return models.UserRankSnapshot(
        discipline="deadlock",
        user_id=user_id,
        social_account_id=account,
        handle=str(account),
        division=None if value is None else "Oracle",
        tier=None if value is None else 3,
        rank_value=value,
        is_ranked=value is not None,
        captured_at=NOW - timedelta(days=days_ago),
        source="scheduled",
    )


class DeadlockRankAtDbTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"dlra-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            user = models.User(name=tag)
            s.add(user)
            await s.flush()
            main, alt = (
                models.SocialAccount(user_id=user.id, provider="steam", username=name, username_normalized=name)
                for name in (f"{tag}a", f"{tag}b")
            )
            s.add_all([main, alt])
            await s.flush()
            s.add_all(
                [
                    _snap(user.id, main.id, 1000, 10),
                    _snap(user.id, main.id, 2000, 5),
                    _snap(user.id, main.id, None, 1),
                    _snap(user.id, alt.id, 1500, 3),
                ]
            )
            await s.commit()
            self.user_id = user.id

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.User).where(models.User.id == self.user_id))
            await s.commit()
        await self.engine.dispose()

    async def _at(self, days_ago: int) -> dict[int, int]:
        async with self.Session() as s:
            return await ranks_at(s, [self.user_id], NOW - timedelta(days=days_ago))

    async def test_the_rank_is_the_row_each_account_held_then_and_the_best_account_wins(self) -> None:
        self.assertEqual(await self._at(20), {})  # before the first poll: unknown
        self.assertEqual(await self._at(7), {self.user_id: 1000})
        self.assertEqual(await self._at(2), {self.user_id: 2000})  # the alt's 1500 is lower
        # The main lost its rank by now: only the alt's still counts.
        self.assertEqual(await self._at(0), {self.user_id: 1500})
