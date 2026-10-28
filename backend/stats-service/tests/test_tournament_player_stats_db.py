"""``GET /tournaments/{id}/player-stats`` against the real Postgres: the per-stat tournament leaderboards, pivoted."""

from __future__ import annotations

import asyncio
from inspect import unwrap

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared.testing import configure_test_cache
from src.services.user.service import UserService, tournament_player_stats

users = UserService.of("overwatch")


def test_player_stats_are_every_players_leaderboard_rows(stats_parity_database) -> None:
    url, ids = stats_parity_database

    async def run():
        configure_test_cache()
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                read = await unwrap(UserService.get_tournament_player_stats)(users, session, ids["tournament"])
                boards = [
                    await users.get_tournament_leaderboard(session, ids["tournament"], stat)
                    for stat in tournament_player_stats
                ]
                return read, boards
        finally:
            await engine.dispose()

    read, boards = asyncio.run(run())
    expected: dict[int, dict[str, dict]] = {}
    for stat, board in zip(tournament_player_stats, boards, strict=True):
        for entry in board.entries:
            expected.setdefault(entry.player_id, {})[stat.value] = {"value": entry.value, "rank": entry.rank}
    assert expected, "the fixture tournament has no stats to rank"
    assert {row.player_id: {k: v.model_dump() for k, v in row.stats.items()} for row in read.players} == expected
    assert read.total_players == max(board.total_players for board in boards)

    # Deaths rank ascending: the fewest deaths is rank 1.
    deaths = sorted(
        (row.stats["deaths"].value, row.stats["deaths"].rank) for row in read.players if "deaths" in row.stats
    )
    assert len({value for value, _ in deaths}) >= 2, "the fixture needs two distinct death averages"
    assert [rank for _, rank in deaths] == sorted(rank for _, rank in deaths)
    assert deaths[0][1] == 1


def test_an_unknown_tournament_is_not_found(rpc) -> None:
    resp = rpc.call_sync("rpc.stats.statistics.tournament_player_stats", {"id": 2_000_000_000})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "not_found"
