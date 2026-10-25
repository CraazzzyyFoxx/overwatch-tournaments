import typing

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.core import enums, pagination
from shared.services.tournament.visibility import visible_tournaments_predicate
from src.services.discipline_queries import DisciplineQueries
from src.services.encounter_seats import Seat

__all__ = ("LOW_SAMPLE_TOURNAMENTS", "MAP_STAT_RECORDS", "StatisticsQueries", "encounter_query")


_seat = Seat(name="statistics_seat")
# One row per player and two-seat encounter their team played; ``maps_won`` /
# ``maps_lost`` are the series score of the team's seat and of the others.
encounter_query = _seat.join(
    sa.select(
        models.Player.id,
        _seat.maps_won.label("maps_won"),
        _seat.maps_lost.label("maps_lost"),
    )
    .select_from(models.Player)
    .join(models.Team, models.Team.id == models.Player.team_id),
    models.Team.id,
).subquery("encounters")

#: A player with this many tournaments or fewer is below the win-rate board (a low sample).
LOW_SAMPLE_TOURNAMENTS = 3

#: The single-map player-total records, in response order: record code -> the game's stat.
MAP_STAT_RECORDS = {
    "hero_damage": enums.LogStatsName.HeroDamageDealt,
    "healing": enums.LogStatsName.HealingDealt,
    "eliminations": enums.LogStatsName.Eliminations,
    "damage_blocked": enums.LogStatsName.DamageBlocked,
    "solo_kills": enums.LogStatsName.SoloKills,
}

#: A title: first overall outside a group stage (``StageItem`` outer-joined onto the standing).
_TITLE = (
    models.Standing.overall_position == 1,
    sa.or_(models.Standing.stage_item_id.is_(None), models.StageItem.type != enums.StageItemType.GROUP),
)

# The seats of a completed two-seat series that one of them won outright (a shared first place has no loser).
_winner = aliased(models.EncounterTeam, name="series_winner")
_loser = aliased(models.EncounterTeam, name="series_loser")


class StatisticsQueries(DisciplineQueries):
    """Analytical statistics reads (leaderboards, per-tournament ranks, top-N pages)."""

    # ---- shared query builders -------------------------------------------------

    def _public_tournaments(
        self, workspace_id: int | None, *, almanac: bool = True
    ) -> tuple[sa.ColumnElement[bool], ...]:
        """What a public board counts: this game, this workspace (``None``: all), and the ``/statistics`` set -- every
        tournament an anonymous viewer may see, leagues included (the overall figures' and ``/encounters``' set).
        ``almanac=False`` keeps the champion/win-rate boards (home, hall of fame) on their own rule: no hidden or
        league tournament."""
        visible = (
            (visible_tournaments_predicate(None),)
            if almanac
            else (models.Tournament.is_hidden.is_(False), models.Tournament.is_league.is_(False))
        )
        return (
            *visible,
            *self.discipline_filter(models.Tournament.discipline),
            *([models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []),
        )

    def _scored_participations(self, *columns: typing.Any, workspace_id: int | None, almanac: bool = True) -> sa.Select:
        """``columns`` over one row per non-substitute roster entry and two-seat encounter its team played
        (``encounter_query``) in a public tournament: the win-rate board's participation rule."""
        return (
            sa.select(*columns)
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(encounter_query, encounter_query.c.id == models.Player.id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(models.Player.is_substitution.is_(False), *self._public_tournaments(workspace_id, almanac=almanac))
        )

    def _championships(self, *columns: typing.Any, workspace_id: int | None, almanac: bool = True) -> sa.Select:
        """``columns`` over one row per title (:data:`_TITLE`) of a non-substitute roster entry in a public tournament."""
        return (
            sa.select(*columns)
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.Standing, models.Standing.team_id == models.Player.team_id)
            .outerjoin(models.StageItem, models.StageItem.id == models.Standing.stage_item_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(
                *_TITLE,
                models.Player.is_substitution.is_(False),
                *self._public_tournaments(workspace_id, almanac=almanac),
            )
        )

    def _decided_series(self, *columns: typing.Any, workspace_id: int | None) -> sa.Select:
        """``columns`` over every completed two-seat series of a public tournament with an outright winner
        (``_winner``/``_loser``)."""
        return (
            sa.select(*columns)
            .select_from(models.Encounter)
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .join(_winner, sa.and_(_winner.encounter_id == models.Encounter.id, _winner.active, _winner.placement == 1))
            .join(_loser, sa.and_(_loser.encounter_id == models.Encounter.id, _loser.active, _loser.placement > 1))
            .where(
                models.Encounter.slot_count == 2,
                models.Encounter.status == enums.EncounterStatus.COMPLETED,
                *self._public_tournaments(workspace_id),
            )
        )

    def _rated_teams(self, workspace_id: int | None) -> sa.CTE:
        """Public tournaments' teams with a roster average SR (non-substitutes), ranked strongest first WITHIN their
        own tournament: communities rate on different scales, so SR never compares across tournaments. A roster
        with an unranked (``rank`` NULL) player has no meaningful average and is left out."""
        avg_sr = sa.func.avg(models.Player.rank)
        return (
            sa.select(
                models.Team.id.label("team_id"),
                models.Team.name,
                models.Team.tournament_id,
                avg_sr.label("avg_sr"),
                sa.func.rank().over(partition_by=models.Team.tournament_id, order_by=avg_sr.desc()).label("sr_rank"),
                sa.func.count().over(partition_by=models.Team.tournament_id).label("rated_teams"),
            )
            .select_from(models.Team)
            .join(
                models.Player,
                sa.and_(models.Player.team_id == models.Team.id, models.Player.is_substitution.is_(False)),
            )
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(*self._public_tournaments(workspace_id))
            .group_by(models.Team.id)
            # Every rank set and positive, as ONE boolean aggregate: the planner guesses 50% of groups pass it but
            # 0.2% pass ``count(rank) = count(*) AND min(rank) > 0``, and at ~20 estimated rows (thousands real) the
            # biggest-upset self-join of this CTE costed a quadratic nested loop as cheap as a hash join (timeout).
            .having(sa.func.bool_and(sa.func.coalesce(models.Player.rank, 0) > 0))
            .cte("rated_teams")
        )

    async def _page_with_window_total(
        self,
        session: AsyncSession,
        query: sa.Select,
        params: pagination.PaginationSortParams,
    ) -> tuple[typing.Sequence[tuple[typing.Any, typing.Any]], int]:
        """Fetch one page AND its grand total in a single round trip.

        ``count(*) OVER ()`` is evaluated after GROUP BY/HAVING but before
        LIMIT/OFFSET, so every returned row carries the full group count and no
        separate ``SELECT count(*) FROM (<page query>)`` round trip is needed.
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
        """Materialize the tournament's native match ids to drive bounded fact probes."""
        return (
            sa.select(self._matches.c.id.label("match_id"))
            .select_from(self._matches)
            .join(models.Encounter, models.Encounter.id == self._matches.c.encounter_id)
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
        ``services.user.queries.encounters.get_roster_avg_mvp_bulk``.
        """
        tournament_matches = self._tournament_match_ids_cte(tournament_id, cte_name=f"{cte_prefix}matches")
        per_match = (
            sa.select(
                self._facts.c.player_id.label("user_id"),
                self._facts.c.match_id.label("match_id"),
                sa.func.max(
                    sa.case((self._facts.c.stat_code == enums.LogStatsName.ImpactRank, self._facts.c.value))
                ).label("impact_rank"),
                sa.func.max(
                    sa.case((self._facts.c.stat_code == enums.LogStatsName.Performance, self._facts.c.value))
                ).label("performance"),
            )
            .select_from(self._facts)
            .join(tournament_matches, tournament_matches.c.match_id == self._facts.c.match_id)
            .where(
                sa.and_(
                    self._facts.c.stat_code.in_([enums.LogStatsName.ImpactRank, enums.LogStatsName.Performance]),
                    self._facts.c.entity_id.is_(None),
                    self._facts.c.segment == 0,
                )
            )
            .group_by(self._facts.c.player_id, self._facts.c.match_id)
            .cte(f"{cte_prefix}per_match")
        )
        placement = sa.func.coalesce(per_match.c.impact_rank, per_match.c.performance)
        average = sa.func.avg(aggregate_order_by(placement, per_match.c.match_id))

        return (
            sa.select(
                per_match.c.user_id.label("user_id"),
                average.cast(sa.Numeric(10, 2)).label("value"),
                sa.func.dense_rank().over(order_by=sa.asc(average)).label("rank"),
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
            self._championships(
                models.User, sa.func.count("*").label("value"), workspace_id=workspace_id, almanac=False
            )
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .group_by(models.User.id)
        )
        return await self._page_with_window_total(session, query, params)  # type: ignore[return-value]

    async def get_top_winrate_players(
        self,
        session: AsyncSession,
        params: pagination.PaginationSortParams,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[tuple[models.Player, float]], int]:
        """Paginated players with their win rates (more than ``LOW_SAMPLE_TOURNAMENTS``), plus the total count."""
        won, lost = sa.func.sum(encounter_query.c.maps_won), sa.func.sum(encounter_query.c.maps_lost)
        query = (
            self._scored_participations(
                models.User,
                (won / sa.func.nullif(won + lost, 0)).label("value"),
                workspace_id=workspace_id,
                almanac=False,
            )
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .group_by(models.User.id)
            .having(sa.func.count(models.Tournament.id.distinct()) > LOW_SAMPLE_TOURNAMENTS)
        )
        return await self._page_with_window_total(session, query, params)  # type: ignore[return-value]

    async def get_player_leaderboard(
        self,
        session: AsyncSession,
        *,
        sort: typing.Literal["titles", "tournaments", "maps_won", "winrate"],
        descending: bool,
        search: str,
        page: int,
        per_page: int,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[sa.Row], int]:
        """One page of every player with a tournament under the win-rate participation rule, plus the total.

        ``rank`` is the competition rank by ``sort`` over the whole population (only the
        above-``LOW_SAMPLE_TOURNAMENTS`` players when sorting by win rate), computed before ``search`` filters
        the page, so a search never renumbers it. Ties: win rate desc (none last), then name.
        """
        won, lost = sa.func.sum(encounter_query.c.maps_won), sa.func.sum(encounter_query.c.maps_lost)
        results = (
            self._scored_participations(
                models.WorkspaceMember.player_id.label("user_id"),
                sa.func.count(models.Tournament.id.distinct()).label("tournaments"),
                won.label("maps_won"),
                lost.label("maps_lost"),
                workspace_id=workspace_id,
            )
            .group_by(models.WorkspaceMember.player_id)
            .cte("player_results")
        )
        titles = (
            self._championships(
                models.WorkspaceMember.player_id.label("user_id"),
                sa.func.count().label("titles"),
                workspace_id=workspace_id,
            )
            .group_by(models.WorkspaceMember.player_id)
            .cte("player_titles")
        )
        title_count = sa.func.coalesce(titles.c.titles, 0)
        winrate = results.c.maps_won / sa.func.nullif(results.c.maps_won + results.c.maps_lost, 0)
        metric = {
            "titles": title_count,
            "tournaments": results.c.tournaments,
            "maps_won": results.c.maps_won,
            "winrate": winrate,
        }[sort]
        ranked = (
            sa.select(
                sa.func.rank()
                .over(order_by=sa.nulls_last(metric.desc() if descending else metric.asc()))
                .label("rank"),
                models.User.id,
                models.User.name,
                title_count.label("titles"),
                results.c.tournaments,
                results.c.maps_won,
                results.c.maps_lost,
                winrate.label("winrate"),
                (results.c.tournaments <= LOW_SAMPLE_TOURNAMENTS).label("low_sample"),
            )
            .select_from(results)
            .join(models.User, models.User.id == results.c.user_id)
            .outerjoin(titles, titles.c.user_id == results.c.user_id)
            .where(*([results.c.tournaments > LOW_SAMPLE_TOURNAMENTS] if sort == "winrate" else []))
            .subquery("ranked_players")
        )
        query = (
            sa.select(*ranked.c, sa.func.count().over().label("total"))
            .where(*([ranked.c.name.icontains(search, autoescape=True)] if search else []))
            .order_by(ranked.c.rank, sa.nulls_last(ranked.c.winrate.desc()), ranked.c.name, ranked.c.id)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await session.execute(query)).all()
        return rows, (rows[0].total if rows else 0)

    # ---- records --------------------------------------------------------------
    #
    # One row (or none) per record, every column under the label ``StatisticsService`` maps: ``value``,
    # ``{player,team,opponent,tournament}_{id,name}``, ``encounter_id``, ``match_id``, ``map_{id,name,slug,image_path}``,
    # ``score``/``opponent_score``, ``duration_s``, ``started_at``/``ended_at``, ``relative``, ``of_total``.

    async def get_win_streak(self, session: AsyncSession, workspace_id: int | None = None) -> sa.Row | None:
        """The longest run of consecutive series a player's team won, across tournaments.

        Series order: the tournament's start, then the series' own end (the ``played_at`` chain of the
        encounters tab); a draw or a loss ends the run. The span shows real series times, else the tournament's
        dates: imported history carries only its import time.
        """
        seat = Seat(name="streak_seat")
        e, t = models.Encounter, models.Tournament
        series = (
            seat.join(
                sa.select(
                    models.WorkspaceMember.player_id.label("user_id"),
                    seat.won.label("won"),
                    t.start_date,
                    t.id.label("tournament_id"),
                    sa.func.coalesce(e.ended_at, e.confirmed_at, e.started_at, e.created_at).label("played_at"),
                    e.id.label("encounter_id"),
                    sa.func.coalesce(e.ended_at, e.started_at, e.scheduled_at, t.start_date).label("started_at"),
                    sa.func.coalesce(e.ended_at, e.started_at, e.scheduled_at, t.end_date, t.start_date).label(
                        "ended_at"
                    ),
                )
                .select_from(models.Player)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
                .join(t, t.id == models.Player.tournament_id),
                models.Player.team_id,
            )
            .where(
                models.Player.is_substitution.is_(False),
                e.status == enums.EncounterStatus.COMPLETED,
                *self._public_tournaments(workspace_id),
            )
            .subquery("streak_series")
        )
        # Gaps and islands: every non-win opens a new island, so an island's wins are one unbroken run.
        islands = sa.select(
            series.c.user_id,
            series.c.won,
            series.c.started_at,
            series.c.ended_at,
            sa.func.sum(sa.case((series.c.won, 0), else_=1))
            .over(
                partition_by=series.c.user_id,
                order_by=(
                    sa.nulls_last(series.c.start_date.asc()),
                    series.c.tournament_id,
                    series.c.played_at,
                    series.c.encounter_id,
                ),
            )
            .label("island"),
        ).subquery("streak_islands")
        streaks = (
            sa.select(
                islands.c.user_id,
                sa.func.count().label("value"),
                sa.func.min(islands.c.started_at).label("started_at"),
                sa.func.max(islands.c.ended_at).label("ended_at"),
            )
            .where(islands.c.won)
            .group_by(islands.c.user_id, islands.c.island)
            .subquery("streaks")
        )
        query = (
            sa.select(
                streaks.c.value,
                streaks.c.user_id.label("player_id"),
                models.User.name.label("player_name"),
                streaks.c.started_at,
                streaks.c.ended_at,
            )
            .join(models.User, models.User.id == streaks.c.user_id)
            .order_by(streaks.c.value.desc(), streaks.c.ended_at.desc(), models.User.name)
            .limit(1)
        )
        return (await session.execute(query)).first()

    async def get_biggest_upset(self, session: AsyncSession, workspace_id: int | None = None) -> sa.Row | None:
        """The series won by the weaker roster (avg SR) with the largest gap relative to the loser's average."""
        rated = self._rated_teams(workspace_id)
        winner_sr, loser_sr = rated.alias("winner_sr"), rated.alias("loser_sr")
        gap = loser_sr.c.avg_sr - winner_sr.c.avg_sr
        relative = gap / loser_sr.c.avg_sr
        query = (
            self._decided_series(
                gap.label("value"),
                relative.label("relative"),
                _winner.team_id.label("team_id"),
                _winner.name.label("team_name"),
                _loser.team_id.label("opponent_id"),
                _loser.name.label("opponent_name"),
                _winner.score.label("score"),
                _loser.score.label("opponent_score"),
                models.Tournament.id.label("tournament_id"),
                models.Tournament.name.label("tournament_name"),
                models.Encounter.id.label("encounter_id"),
                workspace_id=workspace_id,
            )
            .join(winner_sr, winner_sr.c.team_id == _winner.team_id)
            .join(loser_sr, loser_sr.c.team_id == _loser.team_id)
            .where(gap > 0)
            .order_by(
                relative.desc(),
                gap.desc(),
                sa.nulls_last(models.Tournament.start_date.desc()),
                models.Encounter.id.desc(),
            )
            .limit(1)
        )
        return (await session.execute(query)).first()

    async def get_underdog_champion(self, session: AsyncSession, workspace_id: int | None = None) -> sa.Row | None:
        """The champion ranked lowest by roster avg SR among its own tournament's rated teams (``sr_rank`` over
        ``rated_teams``, at least two), most recent first on a tie."""
        rated = self._rated_teams(workspace_id)
        champions = (
            sa.select(models.Standing.team_id)
            .outerjoin(models.StageItem, models.StageItem.id == models.Standing.stage_item_id)
            .where(*_TITLE)
        )
        query = (
            sa.select(
                rated.c.sr_rank.label("value"),
                rated.c.rated_teams.label("of_total"),
                rated.c.team_id,
                rated.c.name.label("team_name"),
                models.Tournament.id.label("tournament_id"),
                models.Tournament.name.label("tournament_name"),
            )
            .join(models.Tournament, models.Tournament.id == rated.c.tournament_id)
            .where(rated.c.team_id.in_(champions), rated.c.rated_teams > 1)
            .order_by(
                (sa.cast(rated.c.sr_rank, sa.Float) / rated.c.rated_teams).desc(),
                sa.nulls_last(models.Tournament.start_date.desc()),
                models.Tournament.id.desc(),
            )
            .limit(1)
        )
        return (await session.execute(query)).first()

    async def get_closest_final(self, session: AsyncSession, workspace_id: int | None = None) -> sa.Row | None:
        """The finished tournament's final with the highest ``closeness``; a smaller margin, then recency, breaks ties.

        A final is a completed encounter in the highest round of a bracket stage of the tournament's last
        bracket stage order (parallel divisions each have one).
        """
        be, stage = models.BracketEncounter, models.Stage
        stage_order = sa.func.coalesce(stage.order, 0)
        bracket = (
            sa.select(
                be.encounter_id,
                sa.and_(
                    stage_order == sa.func.max(stage_order).over(partition_by=be.tournament_id),
                    be.round == sa.func.max(be.round).over(partition_by=be.stage_id),
                ).label("is_final"),
            )
            .join(stage, stage.id == be.stage_id)
            .join(models.Encounter, models.Encounter.id == be.encounter_id)
            .where(
                models.Encounter.status == enums.EncounterStatus.COMPLETED,
                stage.stage_type.in_((enums.StageType.SINGLE_ELIMINATION, enums.StageType.DOUBLE_ELIMINATION)),
            )
            .subquery("bracket_rounds")
        )
        closeness = models.Encounter.closeness
        query = (
            self._decided_series(
                closeness.label("value"),
                _winner.team_id.label("team_id"),
                _winner.name.label("team_name"),
                _loser.team_id.label("opponent_id"),
                _loser.name.label("opponent_name"),
                _winner.score.label("score"),
                _loser.score.label("opponent_score"),
                models.Tournament.id.label("tournament_id"),
                models.Tournament.name.label("tournament_name"),
                models.Encounter.id.label("encounter_id"),
                workspace_id=workspace_id,
            )
            .join(bracket, sa.and_(bracket.c.encounter_id == models.Encounter.id, bracket.c.is_final))
            .where(closeness.is_not(None), models.Tournament.is_finished.is_(True))
            .order_by(
                closeness.desc(),
                sa.func.abs(_winner.score - _loser.score),
                sa.nulls_last(models.Tournament.start_date.desc()),
                models.Encounter.id.desc(),
            )
            .limit(1)
        )
        return (await session.execute(query)).first()

    async def get_map_stat_records(self, session: AsyncSession, workspace_id: int | None = None) -> list[sa.Row]:
        """The highest single-map player total of each :data:`MAP_STAT_RECORDS` stat this game has, newest map on a
        tie. An opponent seat per row: a lobby's map repeats its row once per other team (callers keep the first).

        One ``ix_fact_stat_value_total`` backward probe per stat over ``stats.fact`` alone (the stat id a constant,
        the public-tournament check a per-row EXISTS), so a branch stops at the first visible total: ~5 ms on the
        dev dataset where sorting every total through ``player_facts`` took ~1 s."""
        f, m, e, t, wm = (
            models.StatsFact,
            models.StatsMatch,
            models.Encounter,
            models.Tournament,
            models.WorkspaceMember,
        )
        stat_ids = (
            await session.scalars(
                sa.select(models.StatDef.id).where(
                    models.StatDef.discipline == self.discipline,
                    models.StatDef.code.in_(list(MAP_STAT_RECORDS.values())),
                )
            )
        ).all()
        if not stat_ids:
            return []
        visible = (
            sa.select(1)
            .select_from(m)
            .join(e, e.id == m.encounter_id)
            .join(t, t.id == e.tournament_id)
            .where(m.id == f.match_id, m.discipline == self.discipline, *self._public_tournaments(workspace_id))
            .exists()
        )
        top = sa.union_all(
            *(
                sa.select(f.stat_id, f.value, f.match_id, f.workspace_member_id, f.encounter_team_id)
                .where(
                    f.stat_id == stat_id,
                    f.segment == 0,
                    f.entity_id.is_(None),
                    f.workspace_member_id.is_not(None),
                    visible,
                )
                .order_by(f.value.desc(), f.match_id.desc())
                .limit(1)
                for stat_id in stat_ids
            )
        ).subquery("map_stat_records")
        own_seat = aliased(models.EncounterTeam, name="own_seat")
        other_side = aliased(models.StatsMatchTeam, name="other_side")
        other_seat = aliased(models.EncounterTeam, name="other_seat")
        query = (
            sa.select(
                models.StatDef.code.label("stat_code"),
                top.c.value,
                wm.player_id.label("player_id"),
                models.User.name.label("player_name"),
                own_seat.team_id.label("team_id"),
                own_seat.name.label("team_name"),
                other_seat.team_id.label("opponent_id"),
                other_seat.name.label("opponent_name"),
                t.id.label("tournament_id"),
                t.name.label("tournament_name"),
                m.encounter_id,
                top.c.match_id,
                m.duration_s,
                *self._map_columns(),
            )
            .select_from(top)
            .join(models.StatDef, models.StatDef.id == top.c.stat_id)
            .join(wm, wm.id == top.c.workspace_member_id)
            .join(models.User, models.User.id == wm.player_id)
            .join(own_seat, own_seat.id == top.c.encounter_team_id)
            .join(m, m.id == top.c.match_id)
            .join(e, e.id == m.encounter_id)
            .join(t, t.id == e.tournament_id)
            .join(models.CatalogEntity, models.CatalogEntity.id == m.map_entity_id)
            .outerjoin(
                other_side,
                sa.and_(other_side.match_id == top.c.match_id, other_side.encounter_team_id != top.c.encounter_team_id),
            )
            .outerjoin(other_seat, other_seat.id == other_side.encounter_team_id)
            .order_by(models.StatDef.code, other_side.source_position)
        )
        return list((await session.execute(query)).all())

    async def get_most_mvps(self, session: AsyncSession, workspace_id: int | None = None) -> sa.Row | None:
        """The player with the most maps at ``impact_rank`` 1 (the map's MVP)."""
        facts = self._facts
        mvps = (
            sa.select(facts.c.player_id, sa.func.count().label("value"))
            .join(models.Tournament, models.Tournament.id == facts.c.tournament_id)
            .where(
                facts.c.stat_code == enums.LogStatsName.ImpactRank,
                facts.c.value == 1,
                facts.c.segment == 0,
                facts.c.entity_id.is_(None),
                *self._public_tournaments(workspace_id),
            )
            .group_by(facts.c.player_id)
            .subquery("mvps")
        )
        query = (
            sa.select(mvps.c.value, mvps.c.player_id, models.User.name.label("player_name"))
            .join(models.User, models.User.id == mvps.c.player_id)
            .order_by(mvps.c.value.desc(), models.User.name)
            .limit(1)
        )
        return (await session.execute(query)).first()

    async def get_longest_map(self, session: AsyncSession, workspace_id: int | None = None) -> sa.Row | None:
        """The longest parsed map; its teams in observed (source) order."""
        matches = self._matches
        top = (
            sa.select(
                matches.c.id,
                matches.c.duration_s,
                matches.c.encounter_id,
                matches.c.tournament_id,
                matches.c.map_entity_id,
            )
            .join(models.Tournament, models.Tournament.id == matches.c.tournament_id)
            .where(matches.c.duration_s.is_not(None), *self._public_tournaments(workspace_id))
            .order_by(matches.c.duration_s.desc(), matches.c.id.desc())
            .limit(1)
            .subquery("longest_map")
        )
        sides = [aliased(models.StatsMatchTeam, name=f"side_{n}") for n in (1, 2)]
        seats = [aliased(models.EncounterTeam, name=f"seat_{n}") for n in (1, 2)]
        query = sa.select(
            top.c.duration_s.label("value"),
            top.c.duration_s,
            top.c.id.label("match_id"),
            top.c.encounter_id,
            top.c.tournament_id,
            models.Tournament.name.label("tournament_name"),
            seats[0].team_id.label("team_id"),
            seats[0].name.label("team_name"),
            seats[1].team_id.label("opponent_id"),
            seats[1].name.label("opponent_name"),
            *self._map_columns(),
        ).select_from(top)
        for position, (side, seat) in enumerate(zip(sides, seats, strict=True), 1):
            query = query.outerjoin(
                side, sa.and_(side.match_id == top.c.id, side.source_position == position)
            ).outerjoin(seat, seat.id == side.encounter_team_id)
        query = query.join(models.Tournament, models.Tournament.id == top.c.tournament_id).join(
            models.CatalogEntity, models.CatalogEntity.id == top.c.map_entity_id
        )
        return (await session.execute(query)).first()

    @staticmethod
    def _map_columns() -> tuple[sa.ColumnElement[typing.Any], ...]:
        entity = models.CatalogEntity
        return (
            entity.id.label("map_id"),
            entity.name.label("map_name"),
            entity.slug.label("map_slug"),
            entity.image_path.label("map_image_path"),
        )

    # ---- maps -----------------------------------------------------------------

    async def get_map_stats(self, session: AsyncSession, workspace_id: int | None = None) -> typing.Sequence[sa.Row]:
        """Per (map, mode) of this game: the map's catalog entity, the mode played, games and average parsed length.

        Games are those of completed series in public tournaments: a series' confirmed games with a map when it
        has any, else its parsed maps (imported history has logs but no game rows), so nothing counts twice.
        ``avg_duration_s`` averages every parsed map of those series. The mode is the game's/match's own column,
        never the map's catalog parent: one map can be played in several modes.
        """
        game, match = models.EncounterGame, models.StatsMatch
        official = sa.and_(game.state == enums.EncounterGameState.CONFIRMED, game.map_id.is_not(None))
        has_games = sa.exists().where(game.encounter_id == match.encounter_id, official)
        played = sa.union_all(
            sa.select(game.encounter_id, game.map_id.label("map_id"), game.mode_id.label("mode_id")).where(official),
            sa.select(match.encounter_id, match.map_entity_id, match.mode_entity_id).where(~has_games),
        ).subquery("played_maps")
        scope = (models.Encounter.status == enums.EncounterStatus.COMPLETED, *self._public_tournaments(workspace_id))
        games = (
            sa.select(played.c.map_id, played.c.mode_id, sa.func.count().label("games"))
            .join(models.Encounter, models.Encounter.id == played.c.encounter_id)
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(*scope)
            .group_by(played.c.map_id, played.c.mode_id)
            .subquery("map_games")
        )
        durations = (
            sa.select(
                match.map_entity_id.label("map_id"),
                match.mode_entity_id.label("mode_id"),
                sa.func.avg(match.duration_s).label("avg_duration_s"),
            )
            .join(models.Encounter, models.Encounter.id == match.encounter_id)
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(*scope)
            .group_by(match.map_entity_id, match.mode_entity_id)
            .subquery("map_durations")
        )
        mode = aliased(models.CatalogEntity, name="mode")
        query = (
            sa.select(
                *self._map_columns(),
                mode.id.label("mode_id"),
                mode.name.label("mode_name"),
                mode.slug.label("mode_slug"),
                mode.image_path.label("mode_image_path"),
                games.c.games,
                durations.c.avg_duration_s,
            )
            .select_from(games)
            .join(models.CatalogEntity, models.CatalogEntity.id == games.c.map_id)
            .outerjoin(mode, mode.id == games.c.mode_id)
            .outerjoin(
                durations,
                sa.and_(
                    durations.c.map_id == games.c.map_id,
                    durations.c.mode_id.is_not_distinct_from(games.c.mode_id),
                ),
            )
        )
        return (await session.execute(query)).all()

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
        avg_value = sa.func.avg(
            aggregate_order_by(self._facts.c.value, self._facts.c.match_id, self._facts.c.workspace_member_id)
        )
        stats_query = (
            sa.select(
                self._facts.c.stat_code.label("name"),
                self._facts.c.player_id.label("user_id"),
                avg_value.cast(sa.Numeric(10, 2)).label("value"),
                sa.func.dense_rank()
                .over(
                    order_by=sa.desc(avg_value),
                    partition_by=self._facts.c.stat_code,
                )
                .label("rank"),
                sa.func.dense_rank()
                .over(
                    order_by=sa.asc(avg_value),
                    partition_by=self._facts.c.stat_code,
                )
                .label("rank_asc"),
            )
            .select_from(self._facts)
            .join(tournament_matches, tournament_matches.c.match_id == self._facts.c.match_id)
            .where(
                sa.and_(
                    self._facts.c.stat_code.in_(stats_names),
                    self._facts.c.segment == 0,
                    self._facts.c.entity_id.is_(None),
                )
            )
            .group_by(self._facts.c.player_id, self._facts.c.stat_code)
        ).cte("stats_query")

        query = sa.select(
            stats_query,
            sa.select(sa.func.count(stats_query.c.user_id) / len(stats_names)).scalar_subquery(),
        ).where(stats_query.c.user_id == user_id)

        result = await session.execute(query)
        return [(enums.LogStatsName(code), *values) for code, *values in result.all()]

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

    async def get_tournament_user_ranks(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        user_id: int,
        stats_names: list[enums.LogStatsName],
    ) -> tuple[list[tuple[enums.LogStatsName, int, typing.Any, int, int, int]], sa.Row | None]:
        """``get_tournament_avg_match_stat_for_user_bulk`` and ``get_tournament_mvp_stat_for_user`` in one statement.

        Each of those reads every fact of every tournament match through ``player_facts`` (90k index rows to keep 13k
        and 4k); here the tournament's totals are read once from the tables, MATERIALIZED, and both rankings
        aggregate that. Returns ``(stat rows, mvp row)`` in those two functions' shapes.
        """
        f, d, m, wm = models.StatsFact, models.StatDef, models.StatsMatch, models.WorkspaceMember
        mvp_codes = [enums.LogStatsName.ImpactRank, enums.LogStatsName.Performance]
        matches = self._tournament_match_ids_cte(tournament.id, cte_name="tournament_rank_matches")
        facts = (
            sa.select(
                wm.player_id.label("user_id"), f.match_id, f.workspace_member_id, d.code.label("stat_code"), f.value
            )
            .select_from(matches)
            .join(f, f.match_id == matches.c.match_id)
            .join(m, m.id == f.match_id)
            .join(d, sa.and_(d.id == f.stat_id, d.discipline == m.discipline))
            .join(wm, sa.and_(wm.id == f.workspace_member_id, wm.workspace_id == m.workspace_id))
            .where(d.code.in_([*stats_names, *mvp_codes]), f.segment == 0, f.entity_id.is_(None))
            .cte("tournament_rank_facts")
            .prefix_with("MATERIALIZED")
        )
        avg_value = sa.func.avg(aggregate_order_by(facts.c.value, facts.c.match_id, facts.c.workspace_member_id))
        stats = (
            sa.select(
                facts.c.stat_code.label("name"),
                facts.c.user_id,
                avg_value.cast(sa.Numeric(10, 2)).label("value"),
                sa.func.dense_rank().over(order_by=sa.desc(avg_value), partition_by=facts.c.stat_code).label("rank"),
                sa.func.dense_rank().over(order_by=sa.asc(avg_value), partition_by=facts.c.stat_code).label("rank_asc"),
            )
            .where(facts.c.stat_code.in_(stats_names))
            .group_by(facts.c.user_id, facts.c.stat_code)
        ).cte("tournament_rank_stats")
        per_match = (
            sa.select(
                facts.c.user_id,
                facts.c.match_id,
                sa.func.max(sa.case((facts.c.stat_code == enums.LogStatsName.ImpactRank, facts.c.value))).label(
                    "impact_rank"
                ),
                sa.func.max(sa.case((facts.c.stat_code == enums.LogStatsName.Performance, facts.c.value))).label(
                    "performance"
                ),
            )
            .where(facts.c.stat_code.in_(mvp_codes))
            .group_by(facts.c.user_id, facts.c.match_id)
        ).cte("tournament_rank_mvp_per_match")
        placement = sa.func.coalesce(per_match.c.impact_rank, per_match.c.performance)
        average = sa.func.avg(aggregate_order_by(placement, per_match.c.match_id))
        mvp = (
            sa.select(
                per_match.c.user_id,
                average.cast(sa.Numeric(10, 2)).label("value"),
                sa.func.dense_rank().over(order_by=sa.asc(average)).label("rank"),
            )
            .where(placement.isnot(None))
            .group_by(per_match.c.user_id)
        ).cte("tournament_rank_mvp")
        query = sa.union_all(
            sa.select(
                stats.c.name,
                stats.c.user_id,
                stats.c.value,
                stats.c.rank,
                stats.c.rank_asc,
                sa.select(sa.func.count(stats.c.user_id) / len(stats_names)).scalar_subquery().label("total"),
            ).where(stats.c.user_id == user_id),
            # The MVP row: no stat name, its ascending rank in both rank columns.
            sa.select(
                sa.literal(None, sa.String).label("name"),
                mvp.c.user_id,
                mvp.c.value,
                mvp.c.rank,
                mvp.c.rank,
                sa.select(sa.func.count(mvp.c.user_id)).scalar_subquery(),
            ).where(mvp.c.user_id == user_id),
        )
        rows = (await session.execute(query)).all()
        stat_rows = [(enums.LogStatsName(row.name), *row[1:]) for row in rows if row.name is not None]
        return stat_rows, next((row for row in rows if row.name is None), None)

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
        instead of that function's single-stat-code shape.
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
        over native player facts filtered to the tournament (``segment == 0``,
        character-agnostic totals via ``entity_id IS NULL``), but WITHOUT narrowing to a
        single ``user_id`` — so it returns EVERY player's row. Inverse
        "lower-is-better" stats (Deaths, etc. — see ``enums.is_ascending_stat``)
        rank ascending so the lowest average is rank 1; every other stat ranks
        descending. This mirrors the ``rank_asc``/``rank`` pick the tournament-stats
        flow makes, so a player's rank/value here matches their tournament-stats row.

        Returns rows shaped ``(user_id, name, value, rank)`` ordered by rank.
        ``limit`` is a defensive cap — lobbies are small (< ~200 players).
        """
        avg_value = sa.func.avg(
            aggregate_order_by(self._facts.c.value, self._facts.c.match_id, self._facts.c.workspace_member_id)
        )
        order_by = sa.asc(avg_value) if enums.is_ascending_stat(stat_name) else sa.desc(avg_value)

        tournament_matches = self._tournament_match_ids_cte(tournament_id, cte_name="leaderboard_matches")
        stats_query = (
            sa.select(
                self._facts.c.player_id.label("user_id"),
                avg_value.cast(sa.Numeric(10, 2)).label("value"),
                sa.func.dense_rank().over(order_by=order_by).label("rank"),
            )
            .select_from(self._facts)
            .join(tournament_matches, tournament_matches.c.match_id == self._facts.c.match_id)
            .where(
                sa.and_(
                    self._facts.c.stat_code == stat_name,
                    self._facts.c.segment == 0,
                    self._facts.c.entity_id.is_(None),
                )
            )
            .group_by(self._facts.c.player_id)
        ).cte("leaderboard_stats")

        result = await session.execute(self._ranked_leaderboard_query(stats_query, limit))
        return result.all()  # type: ignore

    async def get_tournament_winrate(
        self, session: AsyncSession, tournament: models.Tournament, user_id: int
    ) -> tuple[int, float, int, int] | None:
        """A user's tournament win rate as ``(user id, win rate, rank, ranked user count)``,
        or ``None`` when the user has no encounters in the tournament.
        """

        seat = Seat(name="winrate_seat")
        sides = (
            seat.join(
                sa.select(
                    models.WorkspaceMember.player_id.label("user_id"),
                    seat.maps_won.label("maps_won"),
                    seat.maps_lost.label("maps_lost"),
                )
                .select_from(models.Team)
                .join(models.Player, models.Player.team_id == models.Team.id)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id),
                models.Team.id,
            )
            .where(models.Encounter.tournament_id == tournament.id)
            .subquery("tournament_winrate_sides")
        )
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
