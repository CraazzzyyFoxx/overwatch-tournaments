"""Player-vs-population and hero-vs-hero comparison queries."""

import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.division_grid import DivisionGrid, division_filter_predicates
from shared.services.achievement_effective import build_effective_achievement_rows_subquery
from src import models
from src.core import enums

from ._scope import (
    _compare_user_scope_exists,
    _hero_compare_stat_visibility_condition,
)

DEFAULT_HERO_COMPARE_STATS: tuple[enums.LogStatsName, ...] = tuple(
    stat for stat in enums.LogStatsName if stat != enums.LogStatsName.HeroTimePlayed
)

COMPARE_METRIC_DEFINITIONS: tuple[tuple[str, str, bool], ...] = (
    ("tournaments_count", "Tournaments", True),
    ("achievements_count", "Achievements", True),
    ("maps_total", "Maps Played", True),
    ("maps_won", "Maps Won", True),
    ("maps_winrate", "Map Winrate", True),
    ("avg_placement", "Average Placement", False),
    ("avg_playoff_placement", "Average Playoff Placement", False),
    ("avg_group_placement", "Average Group Placement", False),
    ("avg_closeness", "Average Closeness", True),
    ("mvp_score_avg", "MVP Score", False),
    ("eliminations_avg_10", "Eliminations", True),
    ("final_blows_avg_10", "Final Blows", True),
    ("hero_damage_dealt_avg_10", "Hero Damage", True),
    ("healing_dealt_avg_10", "Healing Dealt", True),
)


class UserCompareQueries:
    """Compare-tab queries: cohort metrics, hero-vs-hero stats and their catalogs."""

    async def get_compare_catalog_entities(
        self,
        session: AsyncSession,
        *,
        left_hero_id: int | None,
        right_hero_id: int | None,
        map_id: int | None,
    ) -> tuple[models.Hero | None, models.Hero | None, models.Map | None]:
        """Load the optional left hero, right hero, and map in one round trip."""
        left_hero = aliased(models.Hero, name="compare_left_hero")
        right_hero = aliased(models.Hero, name="compare_right_hero")
        compare_map = aliased(models.Map, name="compare_map")
        anchor = sa.select(sa.literal(1).label("anchor")).subquery("compare_catalog_anchor")

        statement = (
            sa.select(left_hero, right_hero, compare_map)
            .select_from(anchor)
            .outerjoin(left_hero, left_hero.id == left_hero_id if left_hero_id is not None else sa.false())
            .outerjoin(right_hero, right_hero.id == right_hero_id if right_hero_id is not None else sa.false())
            .outerjoin(compare_map, compare_map.id == map_id if map_id is not None else sa.false())
        )
        row = (await session.execute(statement)).one()
        return row[0], row[1], row[2]

    def _compare_scoped_players_cte(
        self,
        *,
        role: enums.HeroClass | None,
        div_min: int | None,
        div_max: int | None,
        tournament_id: int | None,
        grid: DivisionGrid,
        name: str = "compare_scoped_players",
        require_finished_nonleague: bool = True,
    ) -> sa.CTE:
        """Resolve eligible roster rows once for all grouped compare metrics."""

        filters: list[typing.Any] = [
            models.Player.is_substitution.is_(False),
        ]
        if require_finished_nonleague:
            filters.extend(
                [
                    models.Tournament.is_finished.is_(True),
                    models.Tournament.is_league.is_(False),
                ]
            )
        if role is not None:
            filters.append(models.Player.role == role)
        filters.extend(division_filter_predicates(models.Player.rank, div_min, div_max, grid))
        if tournament_id is not None:
            filters.append(models.Player.tournament_id == tournament_id)

        return (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Player.team_id.label("team_id"),
                models.Player.tournament_id.label("tournament_id"),
            )
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(*filters)
            .cte(name)
        )

    def _compare_metrics_query_v2(
        self,
        *,
        user_ids: list[int] | None,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.Select:
        """Build one set-based query instead of correlated subqueries per user."""

        scoped_players = self._compare_scoped_players_cte(
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
        )
        stat_scoped_players = self._compare_scoped_players_cte(
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
            name="compare_stat_scoped_players",
            require_finished_nonleague=False,
        )
        has_scope_filter = role is not None or div_min is not None or div_max is not None or tournament_id is not None

        # The cohort, expressed once as something pushable into a subquery. Everything
        # downstream that would otherwise scan a whole table and only meet the cohort at
        # the final join takes this instead.
        cohort_scope: typing.Any | None = None
        if user_ids is not None:
            cohort_scope = user_ids
        elif has_scope_filter:
            cohort_scope = sa.select(scoped_players.c.user_id).distinct()

        candidates_query = sa.select(
            models.User.id.label("id"),
            models.User.name.label("name"),
        )
        if cohort_scope is not None:
            candidates_query = candidates_query.where(models.User.id.in_(cohort_scope))
        candidates = candidates_query.cte("compare_candidates")

        tournament_counts = (
            sa.select(
                scoped_players.c.user_id,
                sa.func.count(sa.distinct(scoped_players.c.tournament_id)).label("tournaments_count"),
            )
            .group_by(scoped_players.c.user_id)
            .cte("compare_tournament_counts")
        )

        encounter_tournament = aliased(models.Tournament)

        def _maps_for_side(team_fk: typing.Any, won: typing.Any, lost: typing.Any) -> sa.Select:
            # One equality join per side. `home_team_id = team.id OR away_team_id =
            # team.id` cannot use either FK index and is what timed the compare
            # page out (OWT-TOURNAMENTS-21T) even after the cohort pushdown.
            return (
                sa.select(
                    scoped_players.c.user_id,
                    won.label("maps_won"),
                    lost.label("maps_lost"),
                )
                .select_from(scoped_players)
                .join(models.Team, models.Team.id == scoped_players.c.team_id)
                .join(models.Encounter, team_fk == models.Team.id)
                .join(encounter_tournament, encounter_tournament.id == models.Encounter.tournament_id)
                .where(
                    encounter_tournament.is_finished.is_(True),
                    encounter_tournament.is_league.is_(False),
                    *([models.Encounter.tournament_id == tournament_id] if tournament_id is not None else []),
                )
            )

        map_sides = (
            _maps_for_side(models.Encounter.home_team_id, models.Encounter.home_score, models.Encounter.away_score)
            .union_all(
                _maps_for_side(models.Encounter.away_team_id, models.Encounter.away_score, models.Encounter.home_score)
            )
            .subquery("compare_map_sides")
        )
        map_totals = (
            sa.select(
                map_sides.c.user_id,
                sa.func.coalesce(sa.func.sum(map_sides.c.maps_won), 0).label("maps_won"),
                sa.func.coalesce(sa.func.sum(map_sides.c.maps_lost), 0).label("maps_lost"),
            )
            .group_by(map_sides.c.user_id)
            .cte("compare_map_totals")
        )

        team_positions = (
            sa.select(
                scoped_players.c.user_id,
                scoped_players.c.team_id,
                sa.func.min(models.Standing.overall_position).label("overall_position"),
            )
            .select_from(scoped_players)
            .join(
                models.Standing,
                sa.and_(
                    models.Standing.team_id == scoped_players.c.team_id,
                    models.Standing.tournament_id == scoped_players.c.tournament_id,
                ),
            )
            .group_by(scoped_players.c.user_id, scoped_players.c.team_id)
            .cte("compare_team_positions")
        )
        average_placements = (
            sa.select(
                team_positions.c.user_id,
                sa.func.avg(team_positions.c.overall_position).label("avg_placement"),
            )
            .group_by(team_positions.c.user_id)
            .cte("compare_average_placements")
        )
        phase_placements = (
            sa.select(
                scoped_players.c.user_id,
                sa.func.avg(models.Standing.position)
                .filter(models.Standing.buchholz.is_(None))
                .label("avg_playoff_placement"),
                sa.func.avg(models.Standing.position)
                .filter(models.Standing.buchholz.isnot(None))
                .label("avg_group_placement"),
            )
            .select_from(scoped_players)
            .join(
                models.Standing,
                sa.and_(
                    models.Standing.team_id == scoped_players.c.team_id,
                    models.Standing.tournament_id == scoped_players.c.tournament_id,
                ),
            )
            .group_by(scoped_players.c.user_id)
            .cte("compare_phase_placements")
        )

        def _closeness_for_side(team_fk: typing.Any) -> sa.Select:
            return (
                sa.select(
                    scoped_players.c.user_id,
                    models.Encounter.closeness.label("closeness"),
                )
                .select_from(scoped_players)
                .join(models.Team, models.Team.id == scoped_players.c.team_id)
                .join(models.Encounter, team_fk == models.Team.id)
                .where(
                    models.Encounter.closeness.isnot(None),
                    *([models.Encounter.tournament_id == tournament_id] if tournament_id is not None else []),
                )
            )

        closeness_sides = (
            _closeness_for_side(models.Encounter.home_team_id)
            .union_all(_closeness_for_side(models.Encounter.away_team_id))
            .subquery("compare_closeness_sides")
        )
        average_closeness = (
            sa.select(
                closeness_sides.c.user_id,
                sa.func.avg(closeness_sides.c.closeness).label("avg_closeness"),
            )
            .group_by(closeness_sides.c.user_id)
            .cte("compare_average_closeness")
        )

        # Unrestricted, this scans every evaluation result and grant in the database and
        # runs the correlated revoke NOT EXISTS over all of them before grouping -- and
        # the cohort was only met at the ``candidates`` join below, which cannot be
        # pushed through the subquery's GROUP BY. Same rows, whole-table cost, and it is
        # what timed the compare page out. ``candidates.id`` is a primary key, so
        # joining it and filtering by membership in it are the same thing.
        effective_achievements = build_effective_achievement_rows_subquery(
            user_ids=cohort_scope,
            name="compare_effective_achievement_rows_v2",
        )
        achievement_match = aliased(models.Match)
        achievement_encounter = aliased(models.Encounter)
        achievements_query = (
            sa.select(
                effective_achievements.c.user_id,
                sa.func.count(sa.distinct(effective_achievements.c.achievement_rule_id)).label("achievements_count"),
            )
            .select_from(effective_achievements)
            .join(candidates, candidates.c.id == effective_achievements.c.user_id)
        )
        if has_scope_filter:
            achievements_query = (
                achievements_query.outerjoin(
                    achievement_match,
                    achievement_match.id == effective_achievements.c.match_id,
                )
                .outerjoin(
                    achievement_encounter,
                    achievement_encounter.id == achievement_match.encounter_id,
                )
                .join(
                    scoped_players,
                    sa.and_(
                        scoped_players.c.user_id == effective_achievements.c.user_id,
                        sa.or_(
                            scoped_players.c.tournament_id == effective_achievements.c.tournament_id,
                            scoped_players.c.tournament_id == achievement_encounter.tournament_id,
                        ),
                    ),
                )
            )
        achievements = achievements_query.group_by(effective_achievements.c.user_id).cte("compare_achievement_counts")

        # One pass over the per-hero stat rows: each (match, user, hero) is grouped
        # once and kept only if that hero was played for more than a minute, then
        # `match` is joined per group for its duration. Joining a separate
        # "eligible hero time" set back into `statistics` row by row is what timed
        # the global compare out (OWT-TOURNAMENTS-21T): the planner expects ~10 rows
        # from that join, gets ~500k, and nested-loops ~115k index probes.
        per_10_metrics = (
            (enums.LogStatsName.Eliminations, "eliminations_avg_10"),
            (enums.LogStatsName.FinalBlows, "final_blows_avg_10"),
            (enums.LogStatsName.HeroDamageDealt, "hero_damage_dealt_avg_10"),
            (enums.LogStatsName.HealingDealt, "healing_dealt_avg_10"),
        )
        stat = models.MatchStatistics
        hero_match_stats = (
            sa.select(
                stat.user_id,
                stat.match_id,
                *[
                    column
                    for name, label in per_10_metrics
                    for column in (
                        sa.func.sum(stat.value).filter(stat.name == name).label(f"{label}_value"),
                        # Rows, not seconds: `match.time` is applied once per stat row
                        # below, exactly as summing it over the joined rows did.
                        sa.func.count().filter(stat.name == name).label(f"{label}_rows"),
                    )
                ],
            )
            .select_from(stat)
            .where(
                stat.round == 0,
                stat.hero_id.isnot(None),
                stat.name.in_([*(name for name, _label in per_10_metrics), enums.LogStatsName.HeroTimePlayed]),
                stat.user_id.in_(sa.select(candidates.c.id)),
            )
        )
        if role is not None or div_min is not None or div_max is not None:
            hero_match_stats = hero_match_stats.join(
                stat_scoped_players,
                sa.and_(
                    stat_scoped_players.c.user_id == stat.user_id,
                    stat_scoped_players.c.team_id == stat.team_id,
                ),
            )
        hero_match_stats = (
            hero_match_stats.group_by(stat.match_id, stat.user_id, stat.hero_id)
            .having(sa.func.bool_or(sa.and_(stat.name == enums.LogStatsName.HeroTimePlayed, stat.value > 60)))
            .cte("compare_hero_match_stats")
        )
        per_10_stats = (
            sa.select(
                hero_match_stats.c.user_id,
                *[
                    (
                        sa.func.sum(hero_match_stats.c[f"{label}_value"])
                        / sa.func.nullif(sa.func.sum(models.Match.time * hero_match_stats.c[f"{label}_rows"]), 0)
                        * 600
                    ).label(label)
                    for _name, label in per_10_metrics
                ],
            )
            .select_from(hero_match_stats)
            .join(models.Match, models.Match.id == hero_match_stats.c.match_id)
        )
        if tournament_id is not None:
            per_10_stats = per_10_stats.join(
                models.Encounter,
                models.Encounter.id == models.Match.encounter_id,
            ).where(models.Encounter.tournament_id == tournament_id)
        per_10_stats = per_10_stats.group_by(hero_match_stats.c.user_id).cte("compare_match_stats")

        # MVP placement spans two LogStatsName columns: ImpactRank when the
        # impact-scoring pipeline computed it for a match, legacy Performance
        # otherwise — same COALESCE(ImpactRank, Performance) per-match average as
        # services.user.queries.encounters.get_roster_avg_mvp_bulk. First collapse each
        # match's two candidate rows into one (impact_rank, performance) pair, THEN
        # average the coalesced placement per user.
        mvp_per_match = (
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
            .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
            .join(candidates, candidates.c.id == models.MatchStatistics.user_id)
            .where(
                models.MatchStatistics.round == 0,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.name.in_([enums.LogStatsName.ImpactRank, enums.LogStatsName.Performance]),
            )
        )
        if role is not None or div_min is not None or div_max is not None:
            mvp_per_match = mvp_per_match.join(
                stat_scoped_players,
                sa.and_(
                    stat_scoped_players.c.user_id == models.MatchStatistics.user_id,
                    stat_scoped_players.c.team_id == models.MatchStatistics.team_id,
                ),
            )
        if tournament_id is not None:
            mvp_per_match = mvp_per_match.join(
                models.Encounter,
                models.Encounter.id == models.Match.encounter_id,
            ).where(models.Encounter.tournament_id == tournament_id)
        mvp_per_match = mvp_per_match.group_by(models.MatchStatistics.user_id, models.MatchStatistics.match_id).cte(
            "compare_mvp_per_match"
        )

        mvp_placement = sa.func.coalesce(mvp_per_match.c.impact_rank, mvp_per_match.c.performance)
        mvp_stats = (
            sa.select(
                mvp_per_match.c.user_id,
                sa.func.avg(mvp_placement).label("mvp_score_avg"),
            )
            .where(mvp_placement.isnot(None))
            .group_by(mvp_per_match.c.user_id)
        ).cte("compare_mvp_stats")

        maps_won = sa.func.coalesce(map_totals.c.maps_won, 0)
        maps_total = maps_won + sa.func.coalesce(map_totals.c.maps_lost, 0)
        return (
            sa.select(
                candidates.c.id,
                candidates.c.name,
                sa.func.coalesce(tournament_counts.c.tournaments_count, 0).label("tournaments_count"),
                sa.func.coalesce(achievements.c.achievements_count, 0).label("achievements_count"),
                maps_won.label("maps_won"),
                maps_total.label("maps_total"),
                sa.func.coalesce(maps_won / sa.func.nullif(maps_total, 0), 0).label("maps_winrate"),
                average_placements.c.avg_placement,
                phase_placements.c.avg_playoff_placement,
                phase_placements.c.avg_group_placement,
                average_closeness.c.avg_closeness,
                mvp_stats.c.mvp_score_avg,
                per_10_stats.c.eliminations_avg_10,
                per_10_stats.c.final_blows_avg_10,
                per_10_stats.c.hero_damage_dealt_avg_10,
                per_10_stats.c.healing_dealt_avg_10,
            )
            .select_from(candidates)
            .outerjoin(tournament_counts, tournament_counts.c.user_id == candidates.c.id)
            .outerjoin(achievements, achievements.c.user_id == candidates.c.id)
            .outerjoin(map_totals, map_totals.c.user_id == candidates.c.id)
            .outerjoin(average_placements, average_placements.c.user_id == candidates.c.id)
            .outerjoin(phase_placements, phase_placements.c.user_id == candidates.c.id)
            .outerjoin(average_closeness, average_closeness.c.user_id == candidates.c.id)
            .outerjoin(mvp_stats, mvp_stats.c.user_id == candidates.c.id)
            .outerjoin(per_10_stats, per_10_stats.c.user_id == candidates.c.id)
        )

    def _normalize_compare_value(self, value: typing.Any) -> float | int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def get_compare_population(
        self,
        session: AsyncSession,
        *,
        user_ids: list[int] | None = None,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> list[dict[str, typing.Any]]:
        if user_ids is not None and not user_ids:
            return []

        query = self._compare_metrics_query_v2(
            user_ids=user_ids,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
        )

        result = await session.execute(query)
        payload: list[dict[str, typing.Any]] = []

        for row in result.mappings().all():
            item: dict[str, typing.Any] = {
                "id": row["id"],
                "name": row["name"],
            }
            for key, _label, _higher_is_better in COMPARE_METRIC_DEFINITIONS:
                item[key] = self._normalize_compare_value(row.get(key))
            payload.append(item)

        return payload

    async def compare_population_exists(
        self,
        session: AsyncSession,
        *,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> bool:
        """Does the baseline cohort contain anybody?

        ``_compare_user_scope_exists`` without materializing the cohort. Its caller
        only needs this to tell "empty cohort" from "empty result" apart — the two are
        different 404s — and used to pull the whole population (~560 ``(id, name)``
        rows) to evaluate ``if not population_users``.
        """
        query = sa.select(sa.literal(1)).select_from(models.User)
        if role is not None or div_min is not None or div_max is not None or tournament_id is not None:
            query = query.where(
                _compare_user_scope_exists(
                    models.User.id,
                    role=role,
                    div_min=div_min,
                    div_max=div_max,
                    tournament_id=tournament_id,
                    grid=grid,
                )
            )
        return await session.scalar(query.limit(1)) is not None

    def compare_hero_candidates_select(
        self,
        *,
        user_ids: list[int] | None,
        role: enums.HeroClass | None,
        div_min: int | None,
        div_max: int | None,
        tournament_id: int | None,
        grid: DivisionGrid,
    ) -> sa.Select:
        """The users a hero-compare baseline covers, as a selectable.

        Public (not ``_``-prefixed) so a test can execute the real thing instead of a
        re-implementation of the predicate: the whole point of the change is that this
        set must stay identical while it stops travelling through Python.

        ``user_ids=None`` = the whole cohort, filtered exactly the way
        ``compare_population_exists`` tests it. An explicit list is passed through
        unchanged for callers that really do hold a few ids.
        """
        query = sa.select(models.User.id.label("user_id"))
        if user_ids is not None:
            return query.where(models.User.id.in_(user_ids))
        if role is None and div_min is None and div_max is None and tournament_id is None:
            return query
        return query.where(
            _compare_user_scope_exists(
                models.User.id,
                role=role,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                grid=grid,
            )
        )

    def _users_hero_compare_query_v2(
        self,
        *,
        user_ids: list[int] | None,
        hero_id: int | None,
        map_id: int | None,
        stats: list[enums.LogStatsName],
        role: enums.HeroClass | None,
        div_min: int | None,
        div_max: int | None,
        tournament_id: int | None,
        grid: DivisionGrid,
    ) -> sa.Select:
        """Return playtime and per-stat rows for all candidates in one statement.

        ``user_ids=None`` means "the whole baseline population", resolved HERE as a
        subquery rather than handed in as a list. The list form is still supported for
        callers that genuinely hold a few ids, but the population must not travel
        through Python: the caller used to resolve the cohort and hand ~560 ids straight
        back as an ``IN`` list, so this statement arrived with 584 bind
        parameters. That is slow twice over -- the planner cannot estimate selectivity
        through a list that long, and under pgBouncer (``prepared_statement_cache_size
        = 0``) the plan is rebuilt on every call, on a statement whose text changes
        whenever the population size does, so nothing is ever reused. It timed out.

        The predicate is ``_compare_user_scope_exists``, the same one the caller applied when it
        resolved the cohort itself, so the
        candidate set is unchanged. It is NOT the same as ``scoped_players`` below,
        which deliberately drops the finished/non-league restriction
        (``require_finished_nonleague=False``) -- reusing that CTE here would silently
        widen the baseline.
        """

        requested_stats = stats or list(DEFAULT_HERO_COMPARE_STATS)
        candidates = self.compare_hero_candidates_select(
            user_ids=user_ids,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
        ).cte("compare_hero_candidates")
        scoped_players = self._compare_scoped_players_cte(
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
            name="compare_hero_scoped_players",
            require_finished_nonleague=False,
        )

        playtime_query = (
            sa.select(
                models.MatchStatistics.user_id,
                sa.func.coalesce(sa.func.sum(models.MatchStatistics.value), 0.0).label("playtime_seconds"),
            )
            .select_from(models.MatchStatistics)
            .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
            .join(candidates, candidates.c.user_id == models.MatchStatistics.user_id)
            .where(
                models.MatchStatistics.round == 0,
                models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
                models.MatchStatistics.hero_id.isnot(None),
            )
        )
        if role is not None or div_min is not None or div_max is not None:
            playtime_query = playtime_query.join(
                scoped_players,
                sa.and_(
                    scoped_players.c.user_id == models.MatchStatistics.user_id,
                    scoped_players.c.team_id == models.MatchStatistics.team_id,
                ),
            )
        if tournament_id is not None:
            playtime_query = playtime_query.join(
                models.Encounter,
                models.Encounter.id == models.Match.encounter_id,
            ).where(models.Encounter.tournament_id == tournament_id)
        if hero_id is not None:
            playtime_query = playtime_query.where(models.MatchStatistics.hero_id == hero_id)
        if map_id is not None:
            playtime_query = playtime_query.where(models.Match.map_id == map_id)
        playtime = playtime_query.group_by(models.MatchStatistics.user_id).cte("compare_hero_playtime")

        eligible_hero_time = aliased(models.MatchStatistics)
        stats_query = (
            sa.select(
                models.MatchStatistics.user_id,
                models.MatchStatistics.name,
                (
                    sa.func.sum(models.MatchStatistics.value) / sa.func.nullif(sa.func.sum(models.Match.time), 0) * 600
                ).label("avg_10"),
            )
            .select_from(models.MatchStatistics)
            .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
            .join(candidates, candidates.c.user_id == models.MatchStatistics.user_id)
            .where(
                models.MatchStatistics.round == 0,
                _hero_compare_stat_visibility_condition(
                    models.MatchStatistics.name,
                    models.MatchStatistics.hero_id,
                    hero_id=hero_id,
                ),
                models.MatchStatistics.name.in_(requested_stats),
                sa.exists(
                    sa.select(1)
                    .select_from(eligible_hero_time)
                    .where(
                        eligible_hero_time.match_id == models.MatchStatistics.match_id,
                        eligible_hero_time.user_id == models.MatchStatistics.user_id,
                        eligible_hero_time.hero_id == models.MatchStatistics.hero_id,
                        eligible_hero_time.name == enums.LogStatsName.HeroTimePlayed,
                        eligible_hero_time.round == 0,
                        eligible_hero_time.value > 60,
                    )
                ),
            )
        )
        if role is not None or div_min is not None or div_max is not None:
            stats_query = stats_query.join(
                scoped_players,
                sa.and_(
                    scoped_players.c.user_id == models.MatchStatistics.user_id,
                    scoped_players.c.team_id == models.MatchStatistics.team_id,
                ),
            )
        if tournament_id is not None:
            stats_query = stats_query.join(
                models.Encounter,
                models.Encounter.id == models.Match.encounter_id,
            ).where(models.Encounter.tournament_id == tournament_id)
        if map_id is not None:
            stats_query = stats_query.where(models.Match.map_id == map_id)
        hero_stats = stats_query.group_by(
            models.MatchStatistics.user_id,
            models.MatchStatistics.name,
        ).cte("compare_hero_stats")

        return (
            sa.select(
                candidates.c.user_id,
                sa.func.coalesce(playtime.c.playtime_seconds, 0.0).label("playtime_seconds"),
                hero_stats.c.name,
                hero_stats.c.avg_10,
            )
            .select_from(candidates)
            .outerjoin(playtime, playtime.c.user_id == candidates.c.user_id)
            .outerjoin(hero_stats, hero_stats.c.user_id == candidates.c.user_id)
        )

    async def get_users_hero_compare_stats(
        self,
        session: AsyncSession,
        *,
        user_ids: list[int] | None,
        hero_id: int | None,
        map_id: int | None,
        stats: list[enums.LogStatsName],
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> tuple[dict[int, float], dict[tuple[int, enums.LogStatsName], float]]:
        """``user_ids=None`` resolves the baseline population in SQL — see
        ``_users_hero_compare_query_v2``. An empty LIST still means "nobody"."""
        if user_ids is not None and not user_ids:
            return {}, {}

        result = await session.execute(
            self._users_hero_compare_query_v2(
                user_ids=user_ids,
                hero_id=hero_id,
                map_id=map_id,
                stats=stats,
                role=role,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                grid=grid,
            )
        )

        playtime_payload: dict[int, float] = {}
        stats_payload: dict[tuple[int, enums.LogStatsName], float] = {}
        for user_id, playtime_seconds, stat_name, avg_10 in result.all():
            resolved_user_id = int(user_id)
            playtime_payload[resolved_user_id] = float(playtime_seconds or 0.0)
            if stat_name is not None and avg_10 is not None:
                stats_payload[(resolved_user_id, stat_name)] = float(avg_10)

        return playtime_payload, stats_payload

    async def get_user_hero_compare_stats(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        hero_id: int | None,
        map_id: int | None,
        stats: list[enums.LogStatsName],
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> tuple[float, dict[enums.LogStatsName, float]]:
        playtime_by_user, stats_by_user = await self.get_users_hero_compare_stats(
            session,
            user_ids=[user_id],
            hero_id=hero_id,
            map_id=map_id,
            stats=stats,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
        )
        return (
            playtime_by_user.get(user_id, 0.0),
            {
                stat_name: value
                for (resolved_user_id, stat_name), value in stats_by_user.items()
                if resolved_user_id == user_id
            },
        )


compare = UserCompareQueries()
