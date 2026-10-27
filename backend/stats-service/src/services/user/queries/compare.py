"""Player-vs-population and hero-vs-hero comparison queries."""

import typing

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.core import enums
from shared.disciplines import DISCIPLINES
from shared.division_grid import DivisionGrid, division_filter_predicates
from shared.schemas.role import RoleRef
from shared.services.achievement_effective import build_effective_achievement_rows_subquery
from src.services.discipline_queries import DisciplineQueries
from src.services.encounter_seats import Seat

from ._scope import (
    _compare_user_scope_exists,
    _hero_compare_stat_visibility_condition,
    canonical_division_predicates,
    player_role_filter,
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


class UserCompareQueries(DisciplineQueries):
    """Compare-tab queries: cohort metrics, hero-vs-hero stats and their catalogs."""

    @property
    def comparable_stats(self) -> tuple[enums.LogStatsName, ...]:
        """The game's declared non-team character stats, playtime aside: what a character comparison reports when the
        caller names none. ``()`` for a game that declares none (LoL) — never another game's vocabulary."""
        declared = {d.code for d in DISCIPLINES[self.discipline].stat_defs if d.group != "team"}
        return tuple(
            stat for stat in enums.LogStatsName if stat.value in declared and stat != enums.LogStatsName.HeroTimePlayed
        )

    async def get_compare_catalog_entities(
        self,
        session: AsyncSession,
        *,
        left_hero_id: int | None,
        right_hero_id: int | None,
        map_id: int | None,
    ) -> tuple[models.CatalogEntity | None, models.CatalogEntity | None, models.CatalogEntity | None]:
        """Load the optional left character, right character, and map of this game in one round trip."""
        if left_hero_id is None and right_hero_id is None and map_id is None:
            return None, None, None
        left_hero = aliased(models.CatalogEntity, name="compare_left_hero")
        right_hero = aliased(models.CatalogEntity, name="compare_right_hero")
        compare_map = aliased(models.CatalogEntity, name="compare_map")
        anchor = sa.select(sa.literal(1).label("anchor")).subquery("compare_catalog_anchor")

        statement = (
            sa.select(left_hero, right_hero, compare_map)
            .select_from(anchor)
            .outerjoin(
                left_hero,
                sa.and_(
                    left_hero.id == left_hero_id if left_hero_id is not None else sa.false(),
                    left_hero.kind == "character",
                    left_hero.discipline == self.discipline,
                ),
            )
            .outerjoin(
                right_hero,
                sa.and_(
                    right_hero.id == right_hero_id if right_hero_id is not None else sa.false(),
                    right_hero.kind == "character",
                    right_hero.discipline == self.discipline,
                ),
            )
            .outerjoin(
                compare_map,
                sa.and_(
                    compare_map.id == map_id if map_id is not None else sa.false(),
                    compare_map.kind == "map",
                    compare_map.discipline == self.discipline,
                ),
            )
        )
        row = (await session.execute(statement)).one()
        return row[0], row[1], row[2]

    def _compare_scoped_players_cte(
        self,
        *,
        role: RoleRef | None,
        div_min: int | None,
        div_max: int | None,
        tournament_id: int | None,
        workspace_id: int | None = None,
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
            filters.append(player_role_filter(models.Player, role))
        # All-workspaces bounds are canonical ladder numbers, the workspace grid's tier numbers otherwise.
        if workspace_id is None:
            filters.extend(
                canonical_division_predicates(
                    models.Player.rank, models.Player.tournament_id, self.discipline, div_min=div_min, div_max=div_max
                )
            )
        else:
            filters.extend(division_filter_predicates(models.Player.rank, div_min, div_max, grid))
        if tournament_id is not None:
            filters.append(models.Player.tournament_id == tournament_id)
        if workspace_id is not None:
            filters.append(models.Tournament.workspace_id == workspace_id)

        return (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Player.team_id.label("team_id"),
                models.Player.tournament_id.label("tournament_id"),
            )
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(models.Tournament.discipline == self.discipline)
            .where(*filters)
            .cte(name)
        )

    def _compare_metrics_query_v2(
        self,
        *,
        user_ids: list[int] | None,
        role: RoleRef | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.Select:
        """Build one set-based query instead of correlated subqueries per user."""

        scoped_players = self._compare_scoped_players_cte(
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            grid=grid,
        )
        stat_scoped_players = self._compare_scoped_players_cte(
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            grid=grid,
            name="compare_stat_scoped_players",
            require_finished_nonleague=False,
        )
        has_scope_filter = role is not None or div_min is not None or div_max is not None or tournament_id is not None
        # Which roster rows count: role/division narrow them, and so does the
        # workspace — a workspace's tournaments are a subset, and a candidate's
        # rows from someone else's workspace must not reach the metrics. The
        # per-stat joins below key on (user_id, team_id), which a tournament_id
        # filter handles via Encounter instead, hence the two separate flags.
        has_roster_filter = role is not None or div_min is not None or div_max is not None or workspace_id is not None

        # The cohort, expressed once as something pushable into a subquery. Everything
        # downstream that would otherwise scan a whole table and only meet the cohort at
        # the final join takes this instead.
        cohort_scope: typing.Any | None = None
        if user_ids is not None:
            cohort_scope = user_ids
        elif has_scope_filter or workspace_id is not None:
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

        map_seat = Seat(name="map_seat")
        map_sides = (
            map_seat.join(
                sa.select(
                    scoped_players.c.user_id,
                    map_seat.maps_won.label("maps_won"),
                    map_seat.maps_lost.label("maps_lost"),
                )
                .select_from(scoped_players)
                .join(models.Team, models.Team.id == scoped_players.c.team_id),
                models.Team.id,
            )
            .join(encounter_tournament, encounter_tournament.id == models.Encounter.tournament_id)
            .where(
                encounter_tournament.is_finished.is_(True),
                encounter_tournament.is_league.is_(False),
                *([models.Encounter.tournament_id == tournament_id] if tournament_id is not None else []),
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

        closeness_seat = Seat(name="closeness_seat")
        closeness_sides = (
            closeness_seat.join(
                sa.select(
                    scoped_players.c.user_id,
                    models.Encounter.closeness.label("closeness"),
                )
                .select_from(scoped_players)
                .join(models.Team, models.Team.id == scoped_players.c.team_id),
                models.Team.id,
                duel=False,
            )
            .where(
                models.Encounter.closeness.isnot(None),
                *([models.Encounter.tournament_id == tournament_id] if tournament_id is not None else []),
            )
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

        # Scoped to the cohort here because the ``candidates`` join below cannot be
        # pushed through the subquery's GROUP BY: unscoped, it scans every evaluation
        # result and grant and runs the correlated revoke NOT EXISTS over all of them.
        # ``candidates.id`` is a primary key, so joining it and filtering by
        # membership in it are the same thing.
        effective_achievements = build_effective_achievement_rows_subquery(
            workspace_id=workspace_id,
            discipline=self.discipline,
            user_ids=cohort_scope,
            name="compare_effective_achievement_rows_v2",
        )
        achievement_match = self._matches.alias()
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
                    achievement_match.c.id == effective_achievements.c.match_id,
                )
                .outerjoin(
                    achievement_encounter,
                    achievement_encounter.id == achievement_match.c.encounter_id,
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
        # `match` is joined per group for its duration. Never join a separate
        # "eligible hero time" set back into `statistics` row by row: the planner
        # expects ~10 rows from that join, gets ~500k, and nested-loops the probes.
        per_10_metrics = (
            (enums.LogStatsName.Eliminations, "eliminations_avg_10"),
            (enums.LogStatsName.FinalBlows, "final_blows_avg_10"),
            (enums.LogStatsName.HeroDamageDealt, "hero_damage_dealt_avg_10"),
            (enums.LogStatsName.HealingDealt, "healing_dealt_avg_10"),
        )
        hero_match_stats = (
            sa.select(
                self._facts.c.player_id.label("user_id"),
                self._facts.c.match_id,
                self._facts.c.workspace_member_id,
                self._facts.c.entity_id,
                *[
                    column
                    for name, label in per_10_metrics
                    for column in (
                        sa.func.sum(
                            aggregate_order_by(
                                self._facts.c.value,
                                self._facts.c.match_id,
                                self._facts.c.workspace_member_id,
                                self._facts.c.entity_id,
                            )
                        )
                        .filter(self._facts.c.stat_code == name.value)
                        .label(f"{label}_value"),
                        sa.func.count().filter(self._facts.c.stat_code == name.value).label(f"{label}_rows"),
                    )
                ],
            )
            .select_from(self._facts)
            .where(
                self._facts.c.segment == 0,
                self._facts.c.entity_id.isnot(None),
                self._facts.c.stat_code.in_(
                    [*(name.value for name, _label in per_10_metrics), enums.LogStatsName.HeroTimePlayed.value]
                ),
                self._facts.c.player_id.in_(sa.select(candidates.c.id)),
            )
        )
        if has_roster_filter:
            hero_match_stats = hero_match_stats.join(
                stat_scoped_players,
                sa.and_(
                    stat_scoped_players.c.user_id == self._facts.c.player_id,
                    stat_scoped_players.c.team_id == self._facts.c.tournament_team_id,
                ),
            )
        hero_match_stats = (
            hero_match_stats.group_by(
                self._facts.c.match_id,
                self._facts.c.workspace_member_id,
                self._facts.c.player_id,
                self._facts.c.entity_id,
            )
            .having(
                sa.func.bool_or(
                    sa.and_(
                        self._facts.c.stat_code == enums.LogStatsName.HeroTimePlayed.value, self._facts.c.value > 60
                    )
                )
            )
            .cte("compare_hero_match_stats")
        )
        reduction_order = (
            hero_match_stats.c.match_id,
            hero_match_stats.c.workspace_member_id,
            hero_match_stats.c.entity_id,
        )
        per_10_stats = (
            sa.select(
                hero_match_stats.c.user_id,
                *[
                    (
                        sa.func.sum(aggregate_order_by(hero_match_stats.c[f"{label}_value"], *reduction_order))
                        / sa.func.nullif(
                            sa.func.sum(
                                aggregate_order_by(
                                    self._matches.c.duration_s * hero_match_stats.c[f"{label}_rows"],
                                    *reduction_order,
                                )
                            ),
                            0,
                        )
                        * 600
                    ).label(label)
                    for _name, label in per_10_metrics
                ],
            )
            .select_from(hero_match_stats)
            .join(self._matches, self._matches.c.id == hero_match_stats.c.match_id)
        )
        if tournament_id is not None:
            per_10_stats = per_10_stats.join(
                models.Encounter,
                models.Encounter.id == self._matches.c.encounter_id,
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
            .join(self._matches, self._matches.c.id == self._facts.c.match_id)
            .join(candidates, candidates.c.id == self._facts.c.player_id)
            .where(
                self._facts.c.segment == 0,
                self._facts.c.entity_id.is_(None),
                self._facts.c.stat_code.in_([enums.LogStatsName.ImpactRank, enums.LogStatsName.Performance]),
            )
        )
        if has_roster_filter:
            mvp_per_match = mvp_per_match.join(
                stat_scoped_players,
                sa.and_(
                    stat_scoped_players.c.user_id == self._facts.c.player_id,
                    stat_scoped_players.c.team_id == self._facts.c.tournament_team_id,
                ),
            )
        if tournament_id is not None:
            mvp_per_match = mvp_per_match.join(
                models.Encounter,
                models.Encounter.id == self._matches.c.encounter_id,
            ).where(models.Encounter.tournament_id == tournament_id)
        mvp_per_match = mvp_per_match.group_by(self._facts.c.player_id, self._facts.c.match_id).cte(
            "compare_mvp_per_match"
        )

        mvp_placement = sa.func.coalesce(mvp_per_match.c.impact_rank, mvp_per_match.c.performance)
        mvp_stats = (
            sa.select(
                mvp_per_match.c.user_id,
                sa.func.avg(aggregate_order_by(mvp_placement, mvp_per_match.c.match_id)).label("mvp_score_avg"),
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
        role: RoleRef | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
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
            workspace_id=workspace_id,
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
        role: RoleRef | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
        grid: DivisionGrid,
    ) -> bool:
        """Does the baseline cohort contain anybody?

        ``_compare_user_scope_exists`` without materializing the cohort: its caller
        only needs this to tell "empty cohort" from "empty result" apart — the two are
        different 404s.
        """
        query = sa.select(sa.literal(1)).select_from(models.User)
        if (
            role is not None
            or div_min is not None
            or div_max is not None
            or tournament_id is not None
            or workspace_id is not None
        ):
            query = query.where(
                _compare_user_scope_exists(
                    models.User.id,
                    discipline=self.discipline,
                    role=role,
                    div_min=div_min,
                    div_max=div_max,
                    tournament_id=tournament_id,
                    workspace_id=workspace_id,
                    grid=grid,
                )
            )
        return await session.scalar(query.limit(1)) is not None

    def compare_hero_candidates_select(
        self,
        *,
        user_ids: list[int] | None,
        role: RoleRef | None,
        div_min: int | None,
        div_max: int | None,
        tournament_id: int | None,
        workspace_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.Select:
        """The users a hero-compare baseline covers, as a selectable.

        Public (not ``_``-prefixed) so a test can execute the real predicate instead
        of a re-implementation.

        ``user_ids=None`` = the whole cohort, filtered exactly the way
        ``compare_population_exists`` tests it. An explicit list is passed through
        unchanged for callers that really do hold a few ids.
        """
        query = sa.select(models.User.id.label("user_id"))
        if user_ids is not None:
            return query.where(models.User.id.in_(user_ids))
        if role is None and div_min is None and div_max is None and tournament_id is None and workspace_id is None:
            return query
        return query.where(
            _compare_user_scope_exists(
                models.User.id,
                discipline=self.discipline,
                role=role,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                workspace_id=workspace_id,
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
        role: RoleRef | None,
        div_min: int | None,
        div_max: int | None,
        tournament_id: int | None,
        workspace_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.Select:
        """Return playtime and per-stat rows for all candidates in one statement.

        ``user_ids=None`` means "the whole baseline population", resolved HERE as a
        subquery; the list form is for callers that genuinely hold a few ids. The
        population must not travel through Python as an ``IN`` list: the planner
        cannot estimate selectivity through a list that long, and a statement whose
        text changes whenever the population size does never reuses a prepared plan.

        The predicate is ``_compare_user_scope_exists``. It is NOT the same as
        ``scoped_players`` below, which deliberately drops the finished/non-league
        restriction (``require_finished_nonleague=False``) -- reusing that CTE here
        would silently widen the baseline.
        """

        candidates = self.compare_hero_candidates_select(
            user_ids=user_ids,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            grid=grid,
        ).cte("compare_hero_candidates")
        scoped_players = self._compare_scoped_players_cte(
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            grid=grid,
            name="compare_hero_scoped_players",
            require_finished_nonleague=False,
        )

        # Same reasoning as ``_compare_metrics_query_v2``: the workspace narrows which
        # roster rows — and therefore which stat rows — belong to the baseline.
        has_roster_filter = role is not None or div_min is not None or div_max is not None or workspace_id is not None
        reduction_order = (self._facts.c.match_id, self._facts.c.workspace_member_id, self._facts.c.entity_id)
        # Explicit ids also go straight onto the facts, not only through the ``candidates`` join: the constant reaches
        # the member scan inside ``player_facts``, so a one-player compare reads that player's facts instead of
        # joining every player's and only then meeting ``candidates``.
        player_scope = [self._facts.c.player_id.in_(user_ids)] if user_ids is not None else []

        playtime_query = (
            sa.select(
                self._facts.c.player_id.label("user_id"),
                sa.func.coalesce(
                    sa.func.sum(
                        aggregate_order_by(
                            self._facts.c.value,
                            *reduction_order,
                        )
                    ),
                    0.0,
                ).label("playtime_seconds"),
            )
            .select_from(self._facts)
            .join(self._matches, self._matches.c.id == self._facts.c.match_id)
            .join(candidates, candidates.c.user_id == self._facts.c.player_id)
            .where(
                self._facts.c.segment == 0,
                self._facts.c.stat_code == enums.LogStatsName.HeroTimePlayed,
                self._facts.c.entity_id.isnot(None),
                *player_scope,
            )
        )
        if has_roster_filter:
            playtime_query = playtime_query.join(
                scoped_players,
                sa.and_(
                    scoped_players.c.user_id == self._facts.c.player_id,
                    scoped_players.c.team_id == self._facts.c.tournament_team_id,
                ),
            )
        if tournament_id is not None:
            playtime_query = playtime_query.join(
                models.Encounter,
                models.Encounter.id == self._matches.c.encounter_id,
            ).where(models.Encounter.tournament_id == tournament_id)
        if hero_id is not None:
            playtime_query = playtime_query.where(self._facts.c.entity_id == hero_id)
        if map_id is not None:
            playtime_query = playtime_query.where(self._matches.c.map_entity_id == map_id)
        playtime = playtime_query.group_by(self._facts.c.player_id).cte("compare_hero_playtime")

        eligible_hero_time = self._facts.alias()
        stats_query = (
            sa.select(
                self._facts.c.player_id.label("user_id"),
                self._facts.c.stat_code.label("name"),
                (
                    sa.func.sum(aggregate_order_by(self._facts.c.value, *reduction_order))
                    / sa.func.nullif(sa.func.sum(aggregate_order_by(self._matches.c.duration_s, *reduction_order)), 0)
                    * 600
                ).label("avg_10"),
            )
            .select_from(self._facts)
            .join(self._matches, self._matches.c.id == self._facts.c.match_id)
            .join(candidates, candidates.c.user_id == self._facts.c.player_id)
            .where(
                self._facts.c.segment == 0,
                _hero_compare_stat_visibility_condition(
                    self._facts.c.stat_code,
                    self._facts.c.entity_id,
                    hero_id=hero_id,
                ),
                self._facts.c.stat_code.in_(stats),
                *player_scope,
                sa.exists(
                    sa.select(1)
                    .select_from(eligible_hero_time)
                    .where(
                        eligible_hero_time.c.match_id == self._facts.c.match_id,
                        eligible_hero_time.c.workspace_member_id == self._facts.c.workspace_member_id,
                        eligible_hero_time.c.entity_id == self._facts.c.entity_id,
                        eligible_hero_time.c.stat_code == enums.LogStatsName.HeroTimePlayed.value,
                        eligible_hero_time.c.segment == 0,
                        eligible_hero_time.c.value > 60,
                    )
                ),
            )
        )
        if has_roster_filter:
            stats_query = stats_query.join(
                scoped_players,
                sa.and_(
                    scoped_players.c.user_id == self._facts.c.player_id,
                    scoped_players.c.team_id == self._facts.c.tournament_team_id,
                ),
            )
        if tournament_id is not None:
            stats_query = stats_query.join(
                models.Encounter,
                models.Encounter.id == self._matches.c.encounter_id,
            ).where(models.Encounter.tournament_id == tournament_id)
        if map_id is not None:
            stats_query = stats_query.where(self._matches.c.map_entity_id == map_id)
        hero_stats = stats_query.group_by(
            self._facts.c.player_id,
            self._facts.c.stat_code,
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
        role: RoleRef | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
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
                workspace_id=workspace_id,
                grid=grid,
            )
        )

        playtime_payload: dict[int, float] = {}
        stats_payload: dict[tuple[int, enums.LogStatsName], float] = {}
        for user_id, playtime_seconds, stat_name, avg_10 in result.all():
            resolved_user_id = int(user_id)
            playtime_payload[resolved_user_id] = float(playtime_seconds or 0.0)
            if stat_name is not None and avg_10 is not None:
                stats_payload[(resolved_user_id, enums.LogStatsName(stat_name))] = float(avg_10)

        return playtime_payload, stats_payload

    async def get_user_hero_compare_stats(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        hero_id: int | None,
        map_id: int | None,
        stats: list[enums.LogStatsName],
        role: RoleRef | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
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
            workspace_id=workspace_id,
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
