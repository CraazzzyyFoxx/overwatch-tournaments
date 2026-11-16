"""The OverFast career: parsing the profile's stats block, the change-only series, the Blizzard-id match, and the
series a real database keeps across polls."""

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
from shared.disciplines.overwatch.collector import career
from shared.disciplines.overwatch.collector.domain import (
    ParsedProfile,
    changed_career,
    match_canonical_id,
    parse_career,
    parse_profile,
)
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres


def _category(name: str, **values: object) -> dict:
    return {
        "category": name,
        "label": name.title(),
        "stats": [{"key": k, "label": k, "value": v} for k, v in values.items()],
    }


def _stats(*, ana_time: int = 600, comp: bool = True) -> dict:
    return {
        "pc": {
            "quickplay": {
                "heroes_comparisons": {},
                "career_stats": {
                    "all-heroes": [_category("game", time_played=ana_time + 100)],
                    "ana": [
                        # The same key under two categories: both must survive.
                        _category("combat", eliminations=4, deaths=2),
                        _category("best", eliminations=4),
                        _category("hero_specific", enemies_slept=3, broken="n/a", flag=True),
                        _category("game", time_played=ana_time),
                    ],
                    "mercy": None,
                },
            },
            "competitive": {"career_stats": {"ana": [_category("game", time_played=60)]}} if comp else None,
        },
        "console": None,
    }


COMPETITIVE = {"pc": {"season": 25, "support": {"division": "diamond", "tier": 3}}, "console": None}


class ParseCareerTests(IsolatedAsyncioTestCase):
    def test_every_hero_of_every_platform_and_queue_is_a_series_grouped_by_category(self) -> None:
        series = {(s.platform, s.queue, s.character): s for s in parse_career(_stats(), COMPETITIVE)}
        self.assertEqual(
            set(series),
            {("pc", "quickplay", "all-heroes"), ("pc", "quickplay", "ana"), ("pc", "competitive", "ana")},
        )
        ana = series["pc", "quickplay", "ana"]
        self.assertEqual(ana.stats["combat"]["eliminations"], 4)
        self.assertEqual(ana.stats["best"]["eliminations"], 4)
        # Non-numbers (and booleans posing as numbers) are no statistic.
        self.assertEqual(ana.stats["hero_specific"], {"enemies_slept": 3})

    def test_only_competitive_figures_are_dated_by_the_season(self) -> None:
        series = {(s.queue, s.character): s.season for s in parse_career(_stats(), COMPETITIVE)}
        self.assertEqual(series["competitive", "ana"], 25)
        self.assertIsNone(series["quickplay", "ana"])

    def test_the_digest_follows_the_figures_not_their_order(self) -> None:
        first = parse_career(_stats(), COMPETITIVE)[1]
        reordered = _stats()
        reordered["pc"]["quickplay"]["career_stats"]["ana"].reverse()
        self.assertEqual(parse_career(reordered, COMPETITIVE)[1].digest, first.digest)
        self.assertNotEqual(parse_career(_stats(ana_time=601), COMPETITIVE)[1].digest, first.digest)

    def test_a_private_profile_has_no_career(self) -> None:
        self.assertEqual(parse_career(None, None), [])

    def test_a_key_blizzard_repeats_inside_a_category_keeps_its_first_figure(self) -> None:
        # Verbatim from a live profile (ana, quick play): 42 of 78 games won is the 53 % Blizzard shows; the two later
        # ``games_won`` rows carry the 17 hero wins.
        game = {
            "category": "game",
            "label": "Game",
            "stats": [
                {"key": "time_played", "label": "Time Played", "value": 38763},
                {"key": "games_played", "label": "Games Played", "value": 78},
                {"key": "games_won", "label": "Games Won", "value": 42},
                {"key": "games_won", "label": "Games Won", "value": 17},
                {"key": "games_won", "label": "Games Won", "value": 17},
                {"key": "hero_wins", "label": "Hero Wins", "value": 17},
                {"key": "win_percentage", "label": "Win Percentage", "value": 53},
                {"key": "games_lost", "label": "Games Lost", "value": 36},
            ],
        }
        (ana,) = parse_career({"pc": {"quickplay": {"career_stats": {"ana": [game]}}}}, None)
        self.assertEqual(ana.stats["game"]["games_won"], 42)
        self.assertEqual(ana.stats["game"]["hero_wins"], 17)


class ChangedCareerTests(IsolatedAsyncioTestCase):
    def test_only_new_or_moved_series_are_written(self) -> None:
        observed = parse_career(_stats(), COMPETITIVE)
        latest = {(s.platform, s.queue, s.character): (s.season, s.digest) for s in observed}
        self.assertEqual(changed_career(observed, latest), [])

        played = parse_career(_stats(ana_time=900), COMPETITIVE)
        self.assertEqual(
            {(s.queue, s.character) for s in changed_career(played, latest)},
            {("quickplay", "ana"), ("quickplay", "all-heroes")},
        )

    def test_a_new_season_with_the_same_figures_is_a_change(self) -> None:
        observed = parse_career(_stats(), COMPETITIVE)
        latest = {(s.platform, s.queue, s.character): (24, s.digest) for s in observed if s.queue == "competitive"}
        self.assertIn(("competitive", "ana"), {(s.queue, s.character) for s in changed_career(observed, latest)})


UPDATED = 1_794_419_881


def _entry(blizzard_id: str, **overrides: object) -> dict:
    return {
        "player_id": blizzard_id,
        "name": "Kito",
        "avatar": "a.png",
        "namecard": "n.png",
        "title": "War Machine",
        "career_url": "",
        "blizzard_id": blizzard_id,
        "last_updated_at": UPDATED,
        "is_public": True,
    } | overrides


PROFILE = parse_profile(
    {
        "username": "Kito",
        "avatar": "a.png",
        "namecard": "n.png",
        "title": "War Machine",
        "endorsement": {"level": 4, "frame": "f.svg"},
        "last_updated_at": UPDATED,
    }
)


class MatchCanonicalIdTests(IsolatedAsyncioTestCase):
    def test_the_one_result_the_summary_was_built_from_is_the_account(self) -> None:
        results = [
            _entry("d957b885fe23cafcbfa5%7C8a1896afd066f0e93cb4e907b5e15b38", last_updated_at=UPDATED - 50),
            _entry("d957b885fe22caffb8a6%7Ce780f97c2eec30abdf95084574139cd1"),
        ]
        self.assertEqual(match_canonical_id(PROFILE, results), "d957b885fe22caffb8a6|e780f97c2eec30abdf95084574139cd1")

    def test_two_identical_results_resolve_nothing(self) -> None:
        results = [_entry("aa%7Cbb"), _entry("cc%7Cdd")]
        self.assertIsNone(match_canonical_id(PROFILE, results))

    def test_without_a_timestamp_the_other_fields_are_not_an_identity(self) -> None:
        undated = ParsedProfile(display_name="Kito", avatar_url="a.png", attrs=PROFILE.attrs, upstream_updated_at=None)
        self.assertIsNone(match_canonical_id(undated, [_entry("aa%7Cbb", last_updated_at=None)]))

    def test_an_id_that_is_not_a_blizzard_id_is_never_stored(self) -> None:
        self.assertIsNone(match_canonical_id(PROFILE, [_entry("../../etc%7Cpasswd")]))


_TAG = itertools.count()


class CareerRecordDbTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"owcareer-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            user = models.User(name=tag)
            s.add(user)
            await s.flush()
            account = models.SocialAccount(
                user_id=user.id, provider="battlenet", username=f"{tag}#1234", username_normalized=f"{tag}#1234"
            )
            s.add(account)
            await s.commit()
            self.user_id, self.account_id = user.id, account.id

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.User).where(models.User.id == self.user_id))
            await s.commit()
        await self.engine.dispose()

    async def _poll(self, stats: dict, at: datetime) -> tuple[int, bool]:
        async with self.Session() as s:
            outcome = await career.record(
                s,
                social_account_id=self.account_id,
                profile=PROFILE,
                career=parse_career(stats, COMPETITIVE),
                now=at,
            )
            await s.commit()
            return outcome

    async def test_a_poll_writes_only_what_moved_and_the_series_reads_back_as_the_play_between_polls(self) -> None:
        start = datetime(2026, 11, 16, 12, tzinfo=UTC)
        self.assertEqual(await self._poll(_stats(), start), (3, True))
        # Nothing played: nothing written.
        self.assertEqual((await self._poll(_stats(), start + timedelta(hours=2)))[0], 0)
        # A session of Ana in quick play: her series and the account total move, competitive does not.
        self.assertEqual((await self._poll(_stats(ana_time=1500), start + timedelta(hours=4)))[0], 2)

        async with self.Session() as s:
            snap = models.CareerSnapshot
            times = (
                await s.scalars(
                    sa.select(snap.stats["game"]["time_played"].as_integer())
                    .where(
                        snap.social_account_id == self.account_id,
                        snap.queue == "quickplay",
                        snap.character == "ana",
                    )
                    .order_by(snap.captured_at)
                )
            ).all()
            profile = await s.scalar(
                sa.select(models.GameAccountProfile).where(
                    models.GameAccountProfile.social_account_id == self.account_id
                )
            )
        self.assertEqual(times, [600, 1500])
        self.assertEqual(profile.attrs, {"namecard": "n.png", "title": "War Machine", "endorsement_level": 4})
        self.assertEqual(profile.fetched_at, start + timedelta(hours=4))

    async def test_the_blizzard_id_is_resolved_again_only_after_a_week(self) -> None:
        start = datetime(2026, 11, 16, 12, tzinfo=UTC)
        await self._poll(_stats(), start)
        async with self.Session() as s:
            await career.set_canonical_id(s, social_account_id=self.account_id, canonical="aa|bb", now=start)
            await s.commit()
        self.assertFalse((await self._poll(_stats(), start + timedelta(days=6)))[1])
        self.assertTrue((await self._poll(_stats(), start + timedelta(days=7)))[1])
        # A miss keeps the id already known.
        async with self.Session() as s:
            await career.set_canonical_id(s, social_account_id=self.account_id, canonical=None)
            await s.commit()
            self.assertEqual(await career.canonical_id(s, self.account_id), "aa|bb")
