"""The career portrait and the admission signals: a real OverFast profile read back as the reads show it, and the
public read's privacy against a real database."""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
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


DAY = NOW.date()
META = portrait.MetaSource(
    platform="pc",
    captured_on=DAY,
    rates={
        ("competitive", None): {
            "ana": (0.30, 0.47, 0.09),
            "jetpack-cat": (0.10, 0.50, 0.20),
            "wuyang": (0.05, 0.49, None),
        },
        ("competitive", "diamond"): {"ana": (0.36, 0.468, 0.095), "jetpack-cat": (0.12, 0.52, 0.30)},
        ("quickplay", None): {"ana": (0.24, 0.455, None)},
    },
    divisions={"support": "diamond"},
)


def _meta(queue: schemas.CareerQueue, character: str) -> schemas.CareerMeta:
    meta = next(c for c in queue.characters if c.character == character).meta
    assert meta is not None
    return meta


class MetaTests(IsolatedAsyncioTestCase):
    def _queue(self, meta: portrait.MetaSource, queue: str) -> schemas.CareerQueue:
        return {q.queue: q for q in portrait.queue_portraits(_rows(), CLASS_OF, meta)}[queue]

    def test_a_competitive_hero_is_compared_at_the_players_division_in_its_role(self) -> None:
        ana = _meta(self._queue(META, "competitive"), "ana")
        self.assertEqual((ana.division, ana.winrate, ana.banrate), ("diamond", 0.468, 0.095))

    def test_a_hero_missing_from_its_division_slice_gets_no_meta_and_the_fit_weighs_the_rest(self) -> None:
        competitive = self._queue(META, "competitive")
        by_name = {c.character: c for c in competitive.characters}
        # wuyang is a support too: the diamond slice has no row for it, so it gets none rather than another slice's.
        self.assertIsNone(by_name["wuyang"].meta)
        ana, cat = by_name["ana"], by_name["jetpack-cat"]
        expected = (ana.share * 0.36 + cat.share * 0.12) / (ana.share + cat.share)
        self.assertAlmostEqual(competitive.meta_fit or 0, expected, places=3)

    def test_without_a_rank_in_the_role_the_hero_is_compared_over_every_division(self) -> None:
        unranked = portrait.MetaSource("pc", DAY, META.rates, divisions={})
        ana = _meta(self._queue(unranked, "competitive"), "ana")
        self.assertEqual((ana.division, ana.pickrate), (None, 0.30))

    def test_quick_play_has_no_bans_and_another_platform_no_meta(self) -> None:
        quickplay = self._queue(META, "quickplay")
        ana = _meta(quickplay, "ana")
        self.assertEqual((ana.pickrate, ana.banrate), (0.24, None))
        self.assertIsNone(quickplay.ban_exposure)
        console = portrait.MetaSource("console", DAY, META.rates, META.divisions)
        self.assertTrue(all(c.meta is None for c in self._queue(console, "competitive").characters))

    def test_the_top_rank_reads_the_top_rates_slice(self) -> None:
        from shared.disciplines.overwatch.collector.domain import rate_division

        self.assertEqual(
            [rate_division(d) for d in ("Diamond", "ultimate", "champion", None, "bogus")],
            ["diamond", "grandmaster", "grandmaster", None, None],
        )


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
        # Ranked accounts show their ranks, which a closed profile hides: a stale openness flag is no signal.
        ranked = _account()
        ranked.profile.is_public = False
        self.assertEqual(_codes(ranked), [])

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


def _health_row(account_id: int, user_id: int, status: str | None, **overrides: object) -> portrait.HealthRow:
    hidden = status in (None, "pending", "not_found")
    row = portrait.HealthRow(
        account_id,
        user_id,
        f"user{user_id}",
        f"Tag{account_id}#1234",
        status,
        None,
        f"Tag{account_id}",
        None if hidden else True,
    )
    return replace(row, **overrides)


class HealthTests(IsolatedAsyncioTestCase):
    def test_coverage_counts_players_by_their_best_account_and_lists_tags_to_fix(self) -> None:
        rows = [
            _health_row(1, 1, "ok"),
            _health_row(2, 1, "not_found"),  # the same player's other tag: still covered
            _health_row(3, 2, "private", is_public=False),  # found, closed
            _health_row(4, 3, "not_found", last_success_at=NOW - timedelta(days=9)),
            _health_row(5, 3, "not_found", last_success_at=NOW - timedelta(days=1)),
            _health_row(6, 4, None),
            _health_row(7, 5, "ok", display_name="NewName"),
        ]
        report = portrait.health(rows, now=NOW)
        self.assertEqual((report.players, report.players_found, report.players_public), (5, 3, 2))
        self.assertEqual(
            (report.accounts, report.accounts_found, report.accounts_public, report.accounts_not_found),
            (7, 3, 2, 3),
        )
        self.assertEqual((report.accounts_pending, report.lost, report.renamed), (1, 2, 1))
        self.assertEqual(
            [(p.kind, p.social_account_id) for p in report.problems], [("lost", 5), ("lost", 4), ("renamed", 7)]
        )


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

    async def _read(self, *, visible_only: bool = False) -> list[schemas.CareerAccount]:
        async with self.Session() as s:
            return (await portrait.career_accounts(s, [self.user_id], visible_only=visible_only))[self.user_id]

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

    async def test_the_read_compares_heroes_with_the_newest_rates_at_the_accounts_current_division(self) -> None:
        day = date(2099, 1, 1)  # newer than any other test's rates, removed below
        rate, entity = models.CharacterRate, models.CatalogEntity
        async with self.Session() as s:
            seeded = None
            if not await s.scalar(sa.select(entity.id).where(entity.discipline == "overwatch", entity.slug == "ana")):
                seeded = models.CatalogEntity(
                    discipline="overwatch", kind="character", slug="ana", name="Ana", attrs={"class": "support"}
                )
                s.add(seeded)
            s.add_all(
                [
                    rate(
                        discipline="overwatch",
                        captured_on=day,
                        platform="pc",
                        queue="competitive",
                        region="europe",
                        division=division,
                        character="ana",
                        pickrate=pick,
                        winrate=50.0,
                        banrate=1.5,
                    )
                    for division, pick in ((None, 20.0), ("platinum", 30.0), ("diamond", 40.0))
                ]
            )
            for captured_at, division in ((NOW - timedelta(days=30), "platinum"), (NOW, "diamond")):
                s.add(
                    models.UserRankSnapshot(
                        discipline="overwatch",
                        user_id=self.user_id,
                        social_account_id=self.shown,
                        handle="h",
                        platform="pc",
                        role="support",
                        division=division,
                        tier=3,
                        is_ranked=True,
                        captured_at=captured_at,
                    )
                )
            await s.commit()
        try:
            (shown,) = await self._read(visible_only=True)
            competitive = next(q for q in shown.queues if q.queue == "competitive")
            ana = _meta(competitive, "ana")
            self.assertEqual((ana.division, ana.pickrate, ana.banrate, ana.captured_on), ("diamond", 0.4, 0.015, day))
        finally:
            async with self.Session() as s:
                await s.execute(sa.delete(rate).where(rate.captured_on == day))
                if seeded is not None:
                    await s.execute(sa.delete(entity).where(entity.id == seeded.id))
                await s.commit()

    async def test_health_reads_only_the_scoped_accounts(self) -> None:
        scope = sa.select(models.SocialAccount.id).where(models.SocialAccount.user_id == self.user_id)
        async with self.Session() as s:
            report = await portrait.career_health(s, now=NOW, account_scope=scope)
        self.assertEqual((report.players, report.accounts), (1, 2))

    async def test_signals_name_the_player_and_each_account(self) -> None:
        async with self.Session() as s:
            (signals,) = await portrait.career_signals(s, [self.user_id], now=NOW)
        tag = signals.user_name or ""
        self.assertTrue(tag.startswith("owportrait-"))
        never = {s.handle for s in signals.signals if s.code == "never_collected"}
        self.assertEqual(never, {f"{tag}a#1234", f"{tag}b#1234"})
