from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import pagination
from shared.schemas.identity import PersonDisplayRead
from shared.services.person_display import load_person_displays
from src import schemas

from .queries import MAP_STAT_RECORDS, StatisticsQueries

__all__ = ("StatisticsService", "statistics")

# ``(player_row, value)`` pairs plus the unpaginated total — the shape every
# leaderboard query on ``StatisticsQueries`` returns.
_Leaderboard = tuple[Sequence[tuple[Any, float | int]], int]


async def _displays(
    session: AsyncSession, discipline: str | None, workspace_id: int | None, names: dict[int, str]
) -> dict[int, PersonDisplayRead]:
    """How the read's game names each player (``user id -> canonical name``); every game's read: the canonical name."""
    if discipline is None:
        return {user_id: PersonDisplayRead.build(canonical=name) for user_id, name in names.items()}
    return await load_person_displays(session, names, discipline=discipline, workspace_id=workspace_id)


def _record(code: str, row: sa.Row, displays: dict[int, PersonDisplayRead]) -> schemas.StatRecord:
    """A record from a ``StatisticsQueries`` record row (see the label convention there)."""
    m = row._mapping

    def ref(key: str) -> schemas.StatRef | None:
        ref_id = m.get(f"{key}_id")
        return None if ref_id is None else schemas.StatRef(id=ref_id, name=m[f"{key}_name"])

    player_id = m.get("player_id")
    return schemas.StatRecord(
        code=code,
        value=m["value"],
        player=None if player_id is None else schemas.StatPlayerRef(id=player_id, display=displays[player_id]),
        team=ref("team"),
        opponent=ref("opponent"),
        tournament=ref("tournament"),
        encounter_id=m.get("encounter_id"),
        match_id=m.get("match_id"),
        map=None
        if m.get("map_id") is None
        else schemas.StatMapRef(id=m["map_id"], name=m["map_name"], slug=m["map_slug"], image_path=m["map_image_path"]),
        score=None if m.get("score") is None else (m["score"], m["opponent_score"]),
        duration_s=m.get("duration_s"),
        started_at=m.get("started_at"),
        ended_at=m.get("ended_at"),
        relative=m.get("relative"),
        of_total=m.get("of_total"),
    )


class StatisticsService:
    """The public statistics reads: one game's, or every game's when ``discipline`` is ``None`` (spec §6.5).

    The champion and win-rate boards (``Paginated[PlayerStatistics]``) differ only in which query feeds them and
    how the value is rounded, so they share one assembler.
    """

    @staticmethod
    async def _paginate(
        query: Callable[[], Awaitable[_Leaderboard]],
        params: pagination.PaginationSortParams,
        *,
        round_to: int | None = None,
    ) -> pagination.Paginated[schemas.PlayerStatistics]:
        rows, total = await query()
        return pagination.Paginated(
            page=params.page,
            per_page=params.per_page,
            total=total,
            results=[
                schemas.PlayerStatistics(
                    id=player.id,
                    name=player.name,
                    value=round(value, round_to) if round_to is not None else value,
                )
                for player, value in rows
            ],
        )

    async def get_most_champions(
        self,
        session: AsyncSession,
        params: pagination.PaginationSortParams,
        *,
        discipline: str | None,
        workspace_id: int | None = None,
    ) -> pagination.Paginated[schemas.PlayerStatistics]:
        """Players ranked by championships won."""
        queries = StatisticsQueries.of(discipline)
        return await self._paginate(
            lambda: queries.get_top_champions(session, params, workspace_id=workspace_id),
            params,
        )

    async def get_to_winrate_players(
        self,
        session: AsyncSession,
        params: pagination.PaginationSortParams,
        *,
        discipline: str | None,
        workspace_id: int | None = None,
    ) -> pagination.Paginated[schemas.PlayerStatistics]:
        """Players ranked by map win rate. Rounded — the query returns a ratio."""
        queries = StatisticsQueries.of(discipline)
        return await self._paginate(
            lambda: queries.get_top_winrate_players(session, params, workspace_id=workspace_id),
            params,
            round_to=2,
        )

    async def get_players(
        self,
        session: AsyncSession,
        params: schemas.PlayerLeaderboardQueryParams,
        *,
        discipline: str | None,
        workspace_id: int | None = None,
    ) -> pagination.Paginated[schemas.PlayerLeaderboardRow]:
        """Every player's titles, tournaments, maps and win rate, competition-ranked by ``params.sort``."""
        rows, total = await StatisticsQueries.of(discipline).get_player_leaderboard(
            session,
            sort=params.sort,
            descending=params.order == pagination.SortOrder.DESC,
            search=params.query.strip(),
            page=params.page,
            per_page=params.per_page,
            workspace_id=workspace_id,
        )
        displays = await _displays(session, discipline, workspace_id, {row.id: row.name for row in rows})
        return pagination.Paginated(
            page=params.page,
            per_page=params.per_page,
            total=total,
            results=[
                schemas.PlayerLeaderboardRow(
                    **{key: value for key, value in row._mapping.items() if key != "name"},
                    display=displays[row.id],
                )
                for row in rows
            ],
        )

    async def get_records(
        self, session: AsyncSession, *, discipline: str | None, workspace_id: int | None = None
    ) -> schemas.StatRecords:
        """The almanac records in their fixed order; the parsed-log ones only for one game; no data, no record."""
        queries = StatisticsQueries.of(discipline)
        found: list[tuple[str, sa.Row | None]] = [
            ("win_streak", await queries.get_win_streak(session, workspace_id)),
            ("biggest_upset", await queries.get_biggest_upset(session, workspace_id)),
            ("underdog_champion", await queries.get_underdog_champion(session, workspace_id)),
            ("closest_final", await queries.get_closest_final(session, workspace_id)),
        ]
        if discipline is not None:
            by_stat: dict[str, sa.Row] = {}
            for row in await queries.get_map_stat_records(session, workspace_id):
                by_stat.setdefault(row.stat_code, row)
            found += [(code, by_stat.get(stat)) for code, stat in MAP_STAT_RECORDS.items()]
            found += [
                ("most_mvps", await queries.get_most_mvps(session, workspace_id)),
                ("longest_map", await queries.get_longest_map(session, workspace_id)),
            ]
        present = [(code, row) for code, row in found if row is not None]
        holders = {
            row._mapping["player_id"]: row._mapping["player_name"]
            for _, row in present
            if row._mapping.get("player_id") is not None
        }
        displays = await _displays(session, discipline, workspace_id, holders)
        return schemas.StatRecords(records=[_record(code, row, displays) for code, row in present])

    async def get_maps(
        self, session: AsyncSession, *, discipline: str, workspace_id: int | None = None
    ) -> schemas.MapStatsResponse:
        """One game's maps grouped by the mode played (the match's own; modeless last), most played first."""
        by_mode: dict[int | None, list[sa.Row]] = {}
        for row in await StatisticsQueries.of(discipline).get_map_stats(session, workspace_id):
            by_mode.setdefault(row.mode_id, []).append(row)
        modes = []
        for rows in by_mode.values():
            games = sum(row.games for row in rows)
            head = rows[0]
            modes.append(
                schemas.MapModeStats(
                    mode=None
                    if head.mode_id is None
                    else schemas.StatMapRef(
                        id=head.mode_id, name=head.mode_name, slug=head.mode_slug, image_path=head.mode_image_path
                    ),
                    games=games,
                    maps=[
                        schemas.MapStat(
                            map=schemas.StatMapRef(
                                id=row.map_id, name=row.map_name, slug=row.map_slug, image_path=row.map_image_path
                            ),
                            games=row.games,
                            share=row.games / games,
                            avg_duration_s=row.avg_duration_s,
                        )
                        for row in sorted(rows, key=lambda row: (-row.games, row.map_name))
                    ],
                )
            )
        modes.sort(key=lambda mode: (mode.mode is None, -mode.games))
        return schemas.MapStatsResponse(total_games=sum(mode.games for mode in modes), modes=modes)


statistics = StatisticsService()
