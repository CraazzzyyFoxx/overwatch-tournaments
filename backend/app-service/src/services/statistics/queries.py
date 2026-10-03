import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import enums, pagination

__all__ = ("StatisticsQueries", "away_score_case", "encounter_query", "home_score_case", "queries")

home_score_case = sa.case(
    (models.Encounter.home_team_id == models.Team.id, models.Encounter.home_score),
    else_=models.Encounter.away_score,
).label("home_score_case")
away_score_case = sa.case(
    (models.Encounter.home_team_id == models.Team.id, models.Encounter.away_score),
    else_=models.Encounter.home_score,
).label("away_score_case")


# Equality-join sides. `home_team_id = team.id OR away_team_id = team.id` cannot
# use either FK index (OWT-TOURNAMENTS-21T). Kept local: statistics must not
# import the user-query `_scope` helpers.
_ENCOUNTER_TEAM_SIDES = (
    (models.Encounter.home_team_id, models.Encounter.home_score, models.Encounter.away_score),
    (models.Encounter.away_team_id, models.Encounter.away_score, models.Encounter.home_score),
)


def _union_encounter_team_sides(build_side):
    home, away = _ENCOUNTER_TEAM_SIDES
    return build_side(*home).union_all(build_side(*away))


def _encounter_side(team_fk, maps_won, maps_lost):
    return (
        sa.select(
            models.Player.id,
            maps_won.label("home_score"),
            maps_lost.label("away_score"),
        )
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(models.Encounter, team_fk == models.Team.id)
    )


encounter_query = _union_encounter_team_sides(_encounter_side).subquery("encounters")


class StatisticsQueries:
    """Analytical statistics reads (leaderboards, per-tournament ranks, top-N pages)."""

    # ---- shared query builders -------------------------------------------------

    def _encounter_scored_players_query(
        self,
        value: sa.ColumnElement[typing.Any],
        *,
        workspace_id: int | None,
        extra_filters: typing.Sequence[sa.ColumnElement[bool]] = (),
    ) -> sa.Select:
        """Per-user aggregate over the map-score subquery, for players with > 3 tournaments.

        The whole Player -> WorkspaceMember -> User -> ``encounter_query`` ->
        Tournament chain is identical for the winrate and won-maps leaderboards;
        only the aggregated ``value`` and the extra tournament filters differ.
        """
        return (
            sa.select(models.User, value.label("value"))
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .join(encounter_query, encounter_query.c.id == models.Player.id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(
                models.Player.is_substitution.is_(False),
                *extra_filters,
                models.Tournament.is_hidden.is_(False),
                *([models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []),
            )
            .group_by(models.User.id)
            .having(sa.func.count(models.Tournament.id.distinct()) > 3)
        )

    async def _page_with_window_total(
        self,
        session: AsyncSession,
        query: sa.Select,
        params: pagination.PaginationSortParams,
    ) -> tuple[typing.Sequence[tuple[typing.Any, typing.Any]], int]:
        """Fetch one page AND its grand total in a single round trip.

        ``count(*) OVER ()`` is evaluated after GROUP BY/HAVING but before
        LIMIT/OFFSET, so every returned row carries the full group count — the
        separate ``SELECT count(*) FROM (<page query>)`` round trip is gone.
        ``only_count`` requests are the one exception: they paginate to
        ``LIMIT 0``, which would starve the window of rows, so they ask for the
        count alone (still one round trip).
        """
        if params.only_count:
            total = await session.scalar(sa.select(sa.func.count()).select_from(query.order_by(None).subquery()))
            return [], total or 0
        paged = params.apply_pagination_sort(query.add_columns(sa.func.count().over().label("total")))
        rows = (await session.execute(paged)).all()
        return [(row[0], row[1]) for row in rows], (rows[0][2] if rows else 0)

    def _tournament_match_ids_cte(self, tournament_id: int, *, cte_name: str) -> sa.CTE:
        """The tournament's match ids, materialized so they DRIVE the stats scan.

        ``matches.statistics`` is ~27M rows and has no index on ``name``, so
        reaching the tournament the other way round (``statistics -> match ->
        encounter`` with the only selective predicate on ``encounter``) lets the
        planner make the stats table the outer relation: a full scan of the
        partial ``round = 0 AND hero_id IS NULL`` index, per request, which is
        what blew past ``statement_timeout`` (OWT-TOURNAMENTS-2AP). A tournament
        has a few hundred matches, so materializing them first — PostgreSQL
        inlines a single-reference CTE otherwise, reproducing the same plan —
        turns the stats read into an ``ix_match_statistics_match_name_round``
        probe per match. Same rows either way; only the shape differs.
        """
        return (
            sa.select(models.Match.id.label("match_id"))
            .select_from(models.Match)
            .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
            .where(models.Encounter.tournament_id == tournament_id)
            .cte(cte_name)
            .prefix_with("MATERIALIZED")
        )

    def _mvp_placement_stats_cte(self, tournament_id: int, *, cte_prefix: str) -> sa.CTE:
        """Per-user average MVP placement, dense-ranked ascending (1 = best).

        The MVP placement stat spans two ``LogStatsName`` columns instead of one:
        ``ImpactRank`` (the newer impact-scoring rank) when the impact pipeline
        computed it for a match, the legacy ``Performance`` rank otherwise — same
        ``COALESCE(ImpactRank, Performance)`` per-match average as
        ``services.user._repositories.get_roster_avg_mvp_bulk``.
        """
        tournament_matches = self._tournament_match_ids_cte(tournament_id, cte_name=f"{cte_prefix}matches")
        per_match = (
            sa.select(
                models.MatchStatistics.user_id.label("user_id"),
                models.MatchStatistics.match_id.label("match_id"),
                sa.func.max(
                    sa.case(
                        (models.MatchStatistics.name == enums.LogStatsName.ImpactRank, models.MatchStatistics.value)
                    )
                ).label("impact_rank"),
                sa.func.max(
                    sa.case(
                        (models.MatchStatistics.name == enums.LogStatsName.Performance, models.MatchStatistics.value)
                    )
                ).label("performance"),
            )
            .select_from(models.MatchStatistics)
            .join(tournament_matches, tournament_matches.c.match_id == models.MatchStatistics.match_id)
            .where(
                sa.and_(
                    models.MatchStatistics.name.in_([enums.LogStatsName.ImpactRank, enums.LogStatsName.Performance]),
                    models.MatchStatistics.hero_id.is_(None),
                    models.MatchStatistics.round == 0,
                )
            )
            .group_by(models.MatchStatistics.user_id, models.MatchStatistics.match_id)
            .cte(f"{cte_prefix}per_match")
        )
        placement = sa.func.coalesce(per_match.c.impact_rank, per_match.c.performance)

        return (
            sa.select(
                per_match.c.user_id.label("user_id"),
                sa.func.avg(placement).cast(sa.Numeric(10, 2)).label("value"),
                sa.func.dense_rank().over(order_by=sa.asc(sa.func.avg(placement))).label("rank"),
            )
            .where(placement.isnot(None))
            .group_by(per_match.c.user_id)
        ).cte(f"{cte_prefix}stats")

    def _ranked_leaderboard_query(self, stats_query: sa.CTE, limit: int) -> sa.Select:
        """``(user_id, name, value, rank)`` rows ordered by rank, for any ranked stats CTE."""
        return (
            sa.select(
                stats_query.c.user_id,
                models.User.name.label("name"),
                stats_query.c.value,
                stats_query.c.rank,
            )
            .join(models.User, models.User.id == stats_query.c.user_id)
            .order_by(stats_query.c.rank.asc(), models.User.name.asc())
            .limit(limit)
        )

    # ---- top-N leaderboards ---------------------------------------------------

    async def get_top_champions(
        self,
        session: AsyncSession,
        params: pagination.PaginationSortParams,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[tuple[models.Player, int]], int]:
        """Paginated players with their championship counts, plus the total player count."""
        query = (
            sa.select(models.User, sa.func.count("*").label("value"))
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Standing, models.Standing.team_id == models.Team.id)
            .outerjoin(
                models.StageItem,
                models.StageItem.id == models.Standing.stage_item_id,
            )
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(
                sa.and_(
                    models.Standing.overall_position == 1,
                    sa.or_(
                        models.Standing.stage_item_id.is_(None),
                        models.StageItem.type != enums.StageItemType.GROUP,
                    ),
                    models.Player.is_substitution.is_(False),
                    models.Tournament.is_league.is_(False),
                    models.Tournament.is_hidden.is_(False),
                    *([models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []),
                )
            )
            .group_by(models.User.id)
        )
        return await self._page_with_window_total(session, query, params)  # type: ignore[return-value]

    async def get_top_winrate_players(
        self,
        session: AsyncSession,
        params: pagination.PaginationSortParams,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[tuple[models.Player, float]], int]:
        """Paginated players with their win rates, plus the total player count."""
        query = self._encounter_scored_players_query(
            (
                sa.func.sum(encounter_query.c.home_score)
                / sa.func.nullif(
                    sa.func.sum(encounter_query.c.home_score) + sa.func.sum(encounter_query.c.away_score),
                    0,
                )
            ),
            workspace_id=workspace_id,
            extra_filters=(models.Tournament.is_league.is_(False),),
        )
        return await self._page_with_window_total(session, query, params)  # type: ignore[return-value]

    async def get_top_won_players(
        self,
        session: AsyncSession,
        params: pagination.PaginationSortParams,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[tuple[models.Player, int]], int]:
        """Paginated players with their win counts, plus the total player count."""
        query = self._encounter_scored_players_query(
            sa.func.sum(encounter_query.c.home_score),
            workspace_id=workspace_id,
        )
        return await self._page_with_window_total(session, query, params)  # type: ignore[return-value]

    # ---- per-tournament stats -------------------------------------------------

    async def get_tournament_avg_match_stat_for_user_bulk(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        user_id: int,
        stats_names: list[enums.LogStatsName],
    ) -> typing.Sequence[tuple[enums.LogStatsName, int, float, int, int, int]]:
        """Per-stat averages for a user in a tournament as ``(stat name, user id, average,
        descending rank, ascending rank, ranked user count)`` rows, one per requested stat.
        """
        tournament_matches = self._tournament_match_ids_cte(tournament.id, cte_name="tournament_stat_matches")
        stats_query = (
            sa.select(
                models.MatchStatistics.name,
                models.MatchStatistics.user_id,
                sa.func.avg(models.MatchStatistics.value).cast(sa.Numeric(10, 2)).label("value"),
                sa.func.dense_rank()
                .over(
                    order_by=sa.desc(sa.func.avg(models.MatchStatistics.value)),
                    partition_by=models.MatchStatistics.name,
                )
                .label("rank"),
                sa.func.dense_rank()
                .over(
                    order_by=sa.asc(sa.func.avg(models.MatchStatistics.value)),
                    partition_by=models.MatchStatistics.name,
                )
                .label("rank_asc"),
            )
            .select_from(models.MatchStatistics)
            .join(tournament_matches, tournament_matches.c.match_id == models.MatchStatistics.match_id)
            .where(
                sa.and_(
                    models.MatchStatistics.name.in_(stats_names),
                    models.MatchStatistics.round == 0,
                    models.MatchStatistics.hero_id.is_(None),
                )
            )
            .group_by(models.MatchStatistics.user_id, models.MatchStatistics.name)
        ).cte("stats_query")

        query = sa.select(
            stats_query,
            sa.select(sa.func.count(stats_query.c.user_id) / len(stats_names)).scalar_subquery(),
        ).where(stats_query.c.user_id == user_id)

        result = await session.execute(query)
        return result.all()  # type: ignore

    async def get_tournament_mvp_stat_for_user(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        user_id: int,
    ) -> sa.Row | None:
        """Average MVP placement + rank/total for ONE user in a tournament.

        Mirrors the ``(value, rank, total)`` shape
        ``get_tournament_avg_match_stat_for_user_bulk`` returns for the other
        ranked tournament stats, so ``get_tournament_with_stats`` can slot it
        into that same ``stats[LogStatsName.Performance]`` entry.

        Ranked ascending (1 = best, dense-ranked so ties share a rank) among every
        player with an MVP placement in this tournament. Returns ``None`` when the
        user has no such matches.
        """
        stats_query = self._mvp_placement_stats_cte(tournament.id, cte_prefix="tournament_mvp_")

        query = sa.select(
            stats_query,
            sa.select(sa.func.count(stats_query.c.user_id)).scalar_subquery().label("total"),
        ).where(stats_query.c.user_id == user_id)

        result = await session.execute(query)
        return result.first()

    async def get_tournament_mvp_stat_leaderboard(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        limit: int = 500,
    ) -> typing.Sequence[tuple[int, str, float, int]]:
        """Full ranked MVP-placement list of every player in a tournament.

        ``get_tournament_stat_leaderboard``'s counterpart for the MVP placement
        stat — see ``_mvp_placement_stats_cte`` for why it needs its own query
        instead of that function's single-``MatchStatistics.name`` shape.
        Returns rows shaped ``(user_id, name, value, rank)`` ordered by rank, same
        contract as ``get_tournament_stat_leaderboard``.
        """
        stats_query = self._mvp_placement_stats_cte(tournament_id, cte_prefix="tournament_mvp_leaderboard_")

        result = await session.execute(self._ranked_leaderboard_query(stats_query, limit))
        return result.all()  # type: ignore

    async def get_tournament_stat_leaderboard(
        self,
        session: AsyncSession,
        tournament_id: int,
        stat_name: enums.LogStatsName,
        *,
        limit: int = 500,
    ) -> typing.Sequence[tuple[int, str, float, int]]:
        """Full ranked list of every player in a tournament for a single stat.

        Generalizes ``get_tournament_avg_match_stat_for_user_bulk``: the same
        per-user ``AVG(value)`` cast to ``Numeric(10, 2)`` + ``dense_rank()`` window
        over ``MatchStatistics`` filtered to the tournament (``round == 0``,
        hero-agnostic totals via ``hero_id IS NULL``), but WITHOUT narrowing to a
        single ``user_id`` — so it returns EVERY player's row. Inverse
        "lower-is-better" stats (Deaths, etc. — see ``enums.is_ascending_stat``)
        rank ascending so the lowest average is rank 1; every other stat ranks
        descending. This mirrors the ``rank_asc``/``rank`` pick the tournament-stats
        flow makes, so a player's rank/value here matches their tournament-stats row.

        Returns rows shaped ``(user_id, name, value, rank)`` ordered by rank.
        ``limit`` is a defensive cap — lobbies are small (< ~200 players).
        """
        avg_value = sa.func.avg(models.MatchStatistics.value)
        order_by = sa.asc(avg_value) if enums.is_ascending_stat(stat_name) else sa.desc(avg_value)

        tournament_matches = self._tournament_match_ids_cte(tournament_id, cte_name="leaderboard_matches")
        stats_query = (
            sa.select(
                models.MatchStatistics.user_id.label("user_id"),
                avg_value.cast(sa.Numeric(10, 2)).label("value"),
                sa.func.dense_rank().over(order_by=order_by).label("rank"),
            )
            .select_from(models.MatchStatistics)
            .join(tournament_matches, tournament_matches.c.match_id == models.MatchStatistics.match_id)
            .where(
                sa.and_(
                    models.MatchStatistics.name == stat_name,
                    models.MatchStatistics.round == 0,
                    models.MatchStatistics.hero_id.is_(None),
                )
            )
            .group_by(models.MatchStatistics.user_id)
        ).cte("leaderboard_stats")

        result = await session.execute(self._ranked_leaderboard_query(stats_query, limit))
        return result.all()  # type: ignore

    async def get_tournament_winrate(
        self, session: AsyncSession, tournament: models.Tournament, user_id: int
    ) -> tuple[int, float, int, int] | None:
        """A user's tournament win rate as ``(user id, win rate, rank, ranked user count)``,
        or ``None`` when the user has no encounters in the tournament.
        """

        def _side(team_fk, won, lost):
            return (
                sa.select(
                    models.WorkspaceMember.player_id.label("user_id"),
                    won.label("maps_won"),
                    lost.label("maps_lost"),
                )
                .select_from(models.Encounter)
                .join(models.Team, team_fk == models.Team.id)
                .join(models.Player, models.Player.team_id == models.Team.id)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
                .where(models.Encounter.tournament_id == tournament.id)
            )

        sides = _union_encounter_team_sides(_side).subquery("tournament_winrate_sides")
        winrate = sa.func.coalesce(
            sa.func.sum(sides.c.maps_won)
            / sa.func.nullif(sa.func.sum(sides.c.maps_won) + sa.func.sum(sides.c.maps_lost), 0),
            0,
        ).label("winrate")

        stats_query = (
            sa.select(
                sides.c.user_id,
                winrate.cast(sa.Numeric(10, 2)).label("winrate"),
                sa.func.dense_rank().over(order_by=(sa.desc(winrate))).label("rank"),
            )
            .select_from(sides)
            .group_by(sides.c.user_id)
        ).subquery()

        query = sa.select(stats_query, sa.select(sa.func.max(stats_query.c.rank)).scalar_subquery()).where(
            stats_query.c.user_id == user_id
        )

        result = await session.execute(query)
        return result.first()


queries = StatisticsQueries()
