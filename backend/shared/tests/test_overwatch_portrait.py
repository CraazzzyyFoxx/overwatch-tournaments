"""The career portrait and the admission signals: a real OverFast profile read back as the reads show it, and the
public read's privacy against a real database."""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.disciplines.overwatch.collector import career, portrait
from shared.disciplines.overwatch.collector.domain import parse_career, parse_profile
from shared.schemas import rank_collection as schemas
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres

#: A live profile trimmed to a few heroes, its identity replaced.
PROFILE = json.loads((Path(__file__).parent / "fixtures" / "overfast_profile.json").read_text())
CLASS_OF = {"ana": "support", "baptiste": "support", "jetpack-cat": "support", "wuyang": "support", "reinhardt": "tank"}
NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


def _rows(captured_at: datetime = NOW) -> list[portrait.SeriesRow]:
    return [
        portrait.SeriesRow(s.platform, s.queue, s.season, s.character, s.stats, captured_at)
        for s in parse_career(PROFILE["stats"], PROFILE["summary"]["competitive"])
    ]


def _queues(rows: list[portrait.SeriesRow]) -> dict[str | None, schemas.CareerQueue]:
    return {queue.queue: queue for queue in portrait.queue_portraits(rows, CLASS_OF)}


class PortraitTests(IsolatedAsyncioTestCase):
    def test_a_queue_reads_games_from_the_account_total_and_rates_per_hero_from_its_own_time(self) -> None:
        quickplay = _queues(_rows())["quickplay"]
        self.assertEqual((quickplay.games_played, quickplay.games_won, quickplay.games_lost), (3488, 1811, 1677))
        ana = next(c for c in quickplay.characters if c.character == "ana")
        # 42 of 78: the hero's first ``games_won``, not the hero wins Blizzard repeats under the same key.
        self.assertEqual((ana.games_played, ana.games_won, ana.winrate), (78, 42, round(42 / 78, 4)))
        self.assertAlmostEqual(ana.rates["healing_done"], 481127 * 600 / 38763, places=1)
        self.assertEqual(ana.role, "support")

    def test_roles_add_up_their_heroes_with_pool_size_and_mains(self) -> None:
        quickplay = _queues(_rows())["quickplay"]
        support = next(role for role in quickplay.roles if role.role == "support")
        heroes = [c for c in quickplay.characters if c.role == "support"]
        self.assertEqual(support.seconds, sum(c.seconds for c in heroes))
        self.assertEqual(support.mains[0], max(heroes, key=lambda c: c.seconds).character)
        self.assertGreater(support.pool_size, 1)

    def test_a_hero_not_played_this_competitive_season_is_left_out_of_it(self) -> None:
        stale = portrait.SeriesRow("pc", "competitive", 24, "reinhardt", {"game": {"time_played": 9000}}, NOW)
        competitive = _queues([*_rows(), stale])["competitive"]
        self.assertEqual(competitive.season, 25)
        self.assertNotIn("reinhardt", {c.character for c in competitive.characters})

    def test_pool_size_and_mains(self) -> None:
        self.assertEqual(portrait.pool_size([100]), 1)
        self.assertEqual(portrait.pool_size([50, 50]), 2)
        self.assertEqual(portrait.mains([("a", 70), ("b", 20), ("c", 10)]), ["a", "b"])


def _account(**overrides: object) -> schemas.CareerAccount:
    profile = parse_profile(PROFILE["summary"])
    base = {
        "social_account_id": 1,
        "handle": "Player#1234",
        "is_primary": True,
        "status": "ok",
        "last_success_at": NOW,
        "profile": schemas.CareerProfile(
            display_name=profile.display_name,
            avatar_url=profile.avatar_url,
            attrs=profile.attrs,
            is_public=True,
            upstream_updated_at=NOW - timedelta(days=2),
            fetched_at=NOW,
        ),
        "queues": portrait.queue_portraits(_rows(), CLASS_OF),
    }
    return schemas.CareerAccount.model_validate(base | overrides)


def _codes(account: schemas.CareerAccount, best_rank: int | None = None) -> list[str]:
    return [signal.code for signal in portrait.account_signals(account, best_rank)]


class SignalTests(IsolatedAsyncioTestCase):
    def test_a_found_public_account_signals_nothing(self) -> None:
        self.assertEqual(_codes(_account()), [])

    def test_a_tag_that_resolved_before_is_told_from_one_that_never_did(self) -> None:
        self.assertEqual(_codes(_account(status="not_found", queues=[])), ["previously_found"])
        self.assertEqual(_codes(_account(status="not_found", last_success_at=None, queues=[])), ["profile_not_found"])

    def test_an_unranked_open_profile_is_not_private_and_a_closed_one_is(self) -> None:
        self.assertEqual(_codes(_account(status="private")), [])
        closed = _account(status="private", queues=[])
        closed.profile.is_public = False
        self.assertEqual(_codes(closed), ["profile_private"])

    def test_an_account_read_under_another_name_is_renamed(self) -> None:
        self.assertEqual(_codes(_account(handle="OldName#1234")), ["renamed"])

    def test_few_hours_at_a_high_rank(self) -> None:
        tiny = _account(
            queues=[q.model_copy(update={"seconds": 3600}) for q in portrait.queue_portraits(_rows(), CLASS_OF)]
        )
        high = portrait.HIGH_RANK
        self.assertEqual(_codes(tiny, high), ["low_hours_high_rank"])
        self.assertEqual(_codes(tiny, high - 1), [])
        self.assertEqual(_codes(_account(), high), [])  # hundreds of hours

    def test_the_player_is_inactive_when_no_account_changed_for_a_month(self) -> None:
        active = portrait.user_signals(7, [_account()], {}, now=NOW)
        self.assertNotIn("inactive", [s.code for s in active.signals])
        gone = _account()
        gone.profile.upstream_updated_at = NOW - timedelta(days=31)
        idle = portrait.user_signals(7, [gone], {}, now=NOW)
        self.assertIn("inactive", [s.code for s in idle.signals])
        self.assertEqual(idle.competitive_role_shares, {"support": 1.0})


_TAG = itertools.count()


class CareerAccountsDbTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"owportrait-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            user = models.User(name=tag)
            s.add(user)
            await s.flush()
            shown, hidden = (
                models.SocialAccount(
                    user_id=user.id,
                    provider="battlenet",
                    username=f"{tag}{n}#1234",
                    username_normalized=f"{tag}{n}#1234",
                )
                for n in ("a", "b")
            )
            s.add_all([shown, hidden])
            await s.flush()
            s.add(models.SocialAccountVisibility(account_id=shown.id, workspace_id=None))
            await s.commit()
            self.user_id, self.shown, self.hidden = user.id, shown.id, hidden.id
        for account_id in (self.shown, self.hidden):
            await self._poll(account_id, PROFILE["stats"])

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.User).where(models.User.id == self.user_id))
            await s.commit()
        await self.engine.dispose()

    async def _poll(self, account_id: int, stats: dict | None, *, readable: bool = True) -> None:
        async with self.Session() as s:
            await career.record(
                s,
                social_account_id=account_id,
                profile=replace(parse_profile(PROFILE["summary"]), is_public=stats is not None),
                career=parse_career(stats, PROFILE["summary"]["competitive"]) if readable else None,
            )
            await s.commit()

    async def _read(self, **kwargs: object) -> list[schemas.CareerAccount]:
        async with self.Session() as s:
            return (await portrait.career_accounts(s, [self.user_id], **kwargs))[self.user_id]

    async def test_the_public_read_shows_only_accounts_on_the_public_profile(self) -> None:
        self.assertEqual([a.social_account_id for a in await self._read()], [self.shown, self.hidden])
        (shown,) = await self._read(visible_only=True)
        self.assertEqual(shown.social_account_id, self.shown)
        self.assertEqual({q.queue for q in shown.queues}, {"quickplay", "competitive"})

    async def test_a_profile_closed_since_shows_no_career(self) -> None:
        await self._poll(self.shown, None)  # the next poll finds it closed
        (shown,) = await self._read(visible_only=True)
        self.assertFalse(shown.profile.is_public)
        self.assertEqual(shown.queues, [])

    async def test_an_unreadable_career_neither_closes_the_profile_nor_touches_its_series(self) -> None:
        await self._poll(self.shown, PROFILE["stats"], readable=False)
        (shown,) = await self._read(visible_only=True)
        self.assertTrue(shown.profile.is_public)
        self.assertEqual({q.queue for q in shown.queues}, {"quickplay", "competitive"})
