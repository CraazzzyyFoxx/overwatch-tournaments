"""Cross-game reads (spec §8.1) over the real stats-parity database: no game means every game's rows.

The legacy population is Overwatch only. There the parity player (``player``) has five visible tournaments and
``player_away`` exactly three (one short of the > 3 threshold). ``seed_native_sentinel`` adds one League tournament,
encounter and match, and ``_seed_lol_roster`` puts ``player`` on its winning home roster and ``player_away`` on the away
roster.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from inspect import unwrap
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared.core import pagination
from shared.division_grid import DEFAULT_GRID
from shared.testing import configure_test_cache
from shared.testing.stats_parity import BASE, STAMP, seed_native_sentinel
from src.services.statistics.service import statistics
from src.services.user.service import UserService

OW = "overwatch"
LOL = "lol"
_DATES = {"created_at": STAMP, "updated_at": STAMP + timedelta(seconds=1)}


@asynccontextmanager
async def _session(url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


def _insert(conn: Connection, table: str, /, **values: object) -> None:
    schema, _, name = table.partition(".")
    conn.execute(sa.insert(sa.table(name, *(sa.column(key) for key in values), schema=schema)), values)


def _seed_lol_roster(conn: Connection, ids: dict[str, int]) -> None:
    """Both parity members on the League sentinel's rosters; the home roster is the tournament's champion."""
    for offset, member, team in ((95, "member", "team_lol_home"), (96, "member_away", "team_lol_away")):
        _insert(
            conn,
            "tournament.player",
            id=BASE + offset,
            name=f"P4 LoL roster {offset}",
            rank=2500,
            tournament_id=ids["tournament_lol"],
            team_id=ids[team],
            workspace_member_id=ids[member],
            is_substitution=False,
            **_DATES,
        )
    _insert(
        conn,
        "tournament.standing",
        id=BASE + 95,
        tournament_id=ids["tournament_lol"],
        team_id=ids["team_lol_home"],
        position=1,
        overall_position=1,
        matches=1,
        win=1,
        draw=0,
        lose=0,
        points=1.0,
        **_DATES,
    )


def test_leaderboards_without_a_game_rank_every_games_results(
    stats_parity_database: tuple[str, dict[str, int]],
) -> None:
    url, ids = stats_parity_database

    async def run() -> None:
        async with _session(url) as session:
            params = pagination.PaginationSortParams(per_page=100, sort="value", order="desc")

            async def board(reader: Any, discipline: str | None) -> dict[int, float]:
                page = await reader(session, params, discipline=discipline)
                return {row.id: row.value for row in page.results}

            ow_champions = await board(statistics.get_most_champions, OW)
            await session.run_sync(lambda sync: seed_native_sentinel(sync.connection(), ids))
            await session.run_sync(lambda sync: _seed_lol_roster(sync.connection(), ids))

            # Champions: one game's board never counts another game's title; no game adds them up.
            assert await board(statistics.get_most_champions, OW) == ow_champions
            assert await board(statistics.get_most_champions, LOL) == {ids["player"]: 1}
            every = await board(statistics.get_most_champions, None)
            assert every[ids["player"]] == ow_champions.get(ids["player"], 0) + 1
            others = {user: value for user, value in every.items() if user != ids["player"]}
            assert others == {user: value for user, value in ow_champions.items() if user != ids["player"]}

            # Winrate keeps the "> 3 tournaments" threshold, counted across games when no game is named: one League
            # tournament ranks nobody on the League board, and lifts player_away (3 Overwatch tournaments) onto the
            # cross-game board only.
            ow, lol, every = [await board(statistics.get_to_winrate_players, game) for game in (OW, LOL, None)]
            assert lol == {}
            assert ids["player"] in ow and ids["player"] in every
            assert ids["player_away"] not in ow
            assert ids["player_away"] in every
            await session.rollback()

    asyncio.run(run())


async def _uncached(method: Any, *args: Any, **kwargs: Any) -> Any:
    """Invoke the real decorated service body, never a cached value."""
    return await unwrap(method.__func__)(method.__self__, *args, **kwargs)


def test_profile_tournaments_without_a_game_list_every_games_rows(
    stats_parity_database: tuple[str, dict[str, int]],
) -> None:
    url, ids = stats_parity_database

    async def run() -> None:
        configure_test_cache()
        async with _session(url) as session:
            await session.run_sync(lambda sync: seed_native_sentinel(sync.connection(), ids))
            await session.run_sync(lambda sync: _seed_lol_roster(sync.connection(), ids))

            async def history(discipline: str | None) -> dict[int, str]:
                service = UserService.of(discipline)
                rows = await _uncached(service.get_tournaments, session, ids["player"], grid=DEFAULT_GRID)
                return {row.id: row.discipline for row in rows.results}

            only_ow = await history(OW)
            assert ids["tournament_lol"] not in only_ow
            assert set(only_ow.values()) == {OW}
            assert await history(None) == {**only_ow, ids["tournament_lol"]: LOL}
            await session.rollback()

    asyncio.run(run())


def test_profile_encounters_without_a_game_list_every_games_rows(
    stats_parity_database: tuple[str, dict[str, int]],
) -> None:
    url, ids = stats_parity_database

    async def run() -> None:
        configure_test_cache()
        async with _session(url) as session:
            await session.run_sync(lambda sync: seed_native_sentinel(sync.connection(), ids))
            params = pagination.PaginationSortParams(per_page=100, sort="played_at", entities=["matches"])

            async def page(discipline: str | None) -> Any:
                service = UserService.of(discipline)
                return await _uncached(service.get_encounters_by_user, session, ids["player"], params)

            only_ow, every = await page(OW), await page(None)
            assert ids["encounter_lol"] not in {row.id for row in only_ow.results}
            assert {row.discipline for row in only_ow.results} == {OW}
            assert every.total == only_ow.total + 1
            league = next(row for row in every.results if row.id == ids["encounter_lol"])
            assert league.discipline == LOL
            # The match reads its own game's facts: the viewer's League totals. No game ranks member totals.
            (match,) = league.matches
            assert match.viewer is not None
            assert match.viewer.facts["hero_damage_dealt"] == 1_000_000.0
            assert match.member_totals == []
            # Overwatch's badge is a stored fact on the viewer: it ranks no member totals either.
            ow_matches = [match for row in only_ow.results for match in row.matches]
            assert ow_matches and all(match.member_totals == [] for match in ow_matches)
            await session.rollback()

    asyncio.run(run())
