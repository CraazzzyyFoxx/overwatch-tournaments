"""Hero stats queries of the public character reads.

Generic CRUD-style operations (`get`, `get_all`, `playtime`) live
on `shared.repository.CatalogEntityRepository`. Everything that remains here is
the analytics/leaderboard logic.
"""

import typing

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums, pagination
from shared.core.chrono import tournament_chrono_key
from shared.division_grid import DivisionGrid, division_case_expr, ladder_grid
from shared.repository.stats_reads import duel_matches
from shared.services.division_grid.access import canonical_division_expr, tournament_grid_versions
from shared.services.tournament.visibility import visible_tournament_ids_subquery
from src.services.discipline_queries import DisciplineQueries

__all__ = ("HeroQueries",)


_LEADERBOARD_STATS = [
    enums.LogStatsName.HeroTimePlayed,
    enums.LogStatsName.Eliminations,
    enums.LogStatsName.HealingDealt,
    enums.LogStatsName.Deaths,
    enums.LogStatsName.HeroDamageDealt,
    enums.LogStatsName.FinalBlows,
    enums.LogStatsName.DamageBlocked,
    enums.LogStatsName.SoloKills,
    enums.LogStatsName.ObjectiveKills,
    enums.LogStatsName.DefensiveAssists,
    enums.LogStatsName.OffensiveAssists,
    enums.LogStatsName.AllDamageDealt,
    enums.LogStatsName.DamageTaken,
    enums.LogStatsName.SelfHealing,
    enums.LogStatsName.UltimatesUsed,
    enums.LogStatsName.Multikills,
    enums.LogStatsName.EnvironmentalKills,
    enums.LogStatsName.CriticalHits,
    # percentage stats — use AVG not per-10
    enums.LogStatsName.WeaponAccuracy,
    enums.LogStatsName.CriticalHitAccuracy,
]

# Maps LogStatsName → column name in stats_agg CTE (used for backend sorting)
_STAT_COLUMN_MAP: dict[enums.LogStatsName, str] = {
    enums.LogStatsName.Eliminations: "per10_eliminations",
    enums.LogStatsName.HealingDealt: "per10_healing",
    enums.LogStatsName.Deaths: "per10_deaths",
    enums.LogStatsName.HeroDamageDealt: "per10_damage",
    enums.LogStatsName.FinalBlows: "per10_final_blows",
    enums.LogStatsName.DamageBlocked: "per10_damage_blocked",
    enums.LogStatsName.SoloKills: "per10_solo_kills",
    enums.LogStatsName.ObjectiveKills: "per10_obj_kills",
    enums.LogStatsName.DefensiveAssists: "per10_defensive_assists",
    enums.LogStatsName.OffensiveAssists: "per10_offensive_assists",
    enums.LogStatsName.AllDamageDealt: "per10_all_damage",
    enums.LogStatsName.DamageTaken: "per10_damage_taken",
    enums.LogStatsName.SelfHealing: "per10_self_healing",
    enums.LogStatsName.UltimatesUsed: "per10_ultimates_used",
    enums.LogStatsName.Multikills: "per10_multikills",
    enums.LogStatsName.EnvironmentalKills: "per10_env_kills",
    enums.LogStatsName.CriticalHits: "per10_crit_hits",
    enums.LogStatsName.WeaponAccuracy: "avg_weapon_accuracy",
    enums.LogStatsName.CriticalHitAccuracy: "avg_crit_accuracy",
    enums.LogStatsName.KD: "kd",
    enums.LogStatsName.KDA: "kda",
}


class HeroQueries(DisciplineQueries):
    """Analytical hero SQL (leaderboard, per-map playtime, stat aggregates)."""

    async def get_heroes_playtime_by_maps(
        self,
        session: AsyncSession,
        maps_ids: list[int],
        user_id: int,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
    ) -> typing.Sequence[tuple[models.CatalogEntity, int, float]]:
        overall_play_time_subquery = (
            sa.select(
                sa.func.sum(
                    aggregate_order_by(
                        self._facts.c.value,
                        self._facts.c.match_id,
                        self._facts.c.workspace_member_id,
                        self._facts.c.entity_id,
                    )
                )
            )
            .select_from(models.CatalogEntity)
            .join(self._facts, self._facts.c.entity_id == models.CatalogEntity.id)
            .join(self._matches, self._matches.c.id == self._facts.c.match_id)
            .join(models.Encounter, models.Encounter.id == self._matches.c.encounter_id)
            .where(
                sa.and_(
                    models.CatalogEntity.kind == "character",
                    models.CatalogEntity.discipline == self.discipline,
                    self._facts.c.stat_code == enums.LogStatsName.HeroTimePlayed,
                    self._facts.c.value > 60,
                    self._facts.c.segment == 0,
                    self._facts.c.player_id == user_id,
                    self._matches.c.map_entity_id.in_(maps_ids),
                    # Mix stats live only inside the mix (mix encounters have no tournament).
                    models.Encounter.tournament_id.is_not(None),
                )
            )
        )

        if tournament_id is not None:
            overall_play_time_subquery = overall_play_time_subquery.where(
                models.Encounter.tournament_id == tournament_id
            )

        if workspace_id is not None:
            overall_play_time_subquery = overall_play_time_subquery.join(
                models.Tournament, models.Tournament.id == models.Encounter.tournament_id
            ).where(models.Tournament.workspace_id == workspace_id)

        query = (
            sa.select(
                models.CatalogEntity,
                self._matches.c.map_entity_id,
                (
                    sa.func.sum(
                        aggregate_order_by(
                            self._facts.c.value,
                            self._facts.c.match_id,
                            self._facts.c.workspace_member_id,
                            self._facts.c.entity_id,
                        )
                    )
                    / overall_play_time_subquery.as_scalar()
                ).label("playtime"),
            )
            .select_from(models.CatalogEntity)
            .join(
                self._facts,
                sa.and_(
                    self._facts.c.entity_id == models.CatalogEntity.id,
                    self._facts.c.stat_code == enums.LogStatsName.HeroTimePlayed,
                    self._facts.c.value > 60,
                    self._facts.c.segment == 0,
                    self._facts.c.player_id == user_id,
                ),
            )
            .join(self._matches, self._matches.c.id == self._facts.c.match_id)
            .join(models.Encounter, models.Encounter.id == self._matches.c.encounter_id)
            .where(
                self._matches.c.map_entity_id.in_(maps_ids),
                models.CatalogEntity.kind == "character",
                models.CatalogEntity.discipline == self.discipline,
                # Mix stats live only inside the mix (mix encounters have no tournament).
                models.Encounter.tournament_id.is_not(None),
            )
        )

        if tournament_id is not None:
            query = query.where(models.Encounter.tournament_id == tournament_id)

        if workspace_id is not None:
            query = query.join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id).where(
                models.Tournament.workspace_id == workspace_id
            )

        query = query.group_by(models.CatalogEntity.id, self._matches.c.map_entity_id).order_by(
            sa.text("playtime DESC")
        )

        result = await session.execute(query)
        return result.all()  # type: ignore

    async def get_user_hero_stats_by_maps(
        self,
        session: AsyncSession,
        maps_ids: list[int],
        user_id: int,
        limit_per_map: int = 5,
        min_seconds: float = 60,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
    ) -> typing.Sequence[tuple[models.CatalogEntity, int, int, int, int, int, float, float, float]]:
        """Return top hero summaries per map for a given user.

        This is designed for UX popovers: one query returns top N heroes per map with
        per-map playtime share and a W/L/D record based on match score.

        Notes:
        - Counts games where the hero time-played stat exists for the match (round=0)
          and is above `min_seconds`.
        - Winrate is wins / games (draws count as games, but not wins).
        """

        if not maps_ids:
            return []

        hero_match_q = (
            sa.select(
                self._facts.c.entity_id.label("hero_id"),
                self._facts.c.encounter_team_id,
                self._matches.c.id.label("match_id"),
                self._matches.c.map_entity_id.label("map_id"),
                sa.func.sum(aggregate_order_by(self._facts.c.value, self._facts.c.workspace_member_id)).label(
                    "playtime_seconds"
                ),
            )
            .select_from(self._facts)
            .join(self._matches, self._matches.c.id == self._facts.c.match_id)
            .where(
                sa.and_(
                    self._facts.c.stat_code == enums.LogStatsName.HeroTimePlayed,
                    self._facts.c.value > min_seconds,
                    self._facts.c.segment == 0,
                    self._facts.c.player_id == user_id,
                    self._facts.c.entity_id.isnot(None),
                    self._matches.c.map_entity_id.in_(maps_ids),
                    # Mix stats live only inside the mix (mix encounters have no tournament).
                    self._matches.c.tournament_id.is_not(None),
                )
            )
        )

        if tournament_id is not None or workspace_id is not None:
            hero_match_q = hero_match_q.join(models.Encounter, models.Encounter.id == self._matches.c.encounter_id)

            if tournament_id is not None:
                hero_match_q = hero_match_q.where(models.Encounter.tournament_id == tournament_id)

            if workspace_id is not None:
                hero_match_q = hero_match_q.join(
                    models.Tournament, models.Tournament.id == models.Encounter.tournament_id
                ).where(models.Tournament.workspace_id == workspace_id)

        hero_match = hero_match_q.group_by(
            self._facts.c.entity_id,
            self._facts.c.encounter_team_id,
            self._matches.c.id,
            self._matches.c.map_entity_id,
        ).cte("hero_match")

        # The user's duels only, MATERIALIZED: the planner estimates both sides at one row, and an inlined whole-game
        # duel subquery lands on the inner side of a nested loop and re-runs its score lookups per hero row (past the
        # 30s statement timeout for a long career).
        duels = (
            sa.select(duel_matches(discipline=self.discipline, match_ids=sa.select(hero_match.c.match_id)))
            .cte("hero_match_duels")
            .prefix_with("MATERIALIZED")
        )
        team_score = sa.case(
            (duels.c.home_encounter_team_id == hero_match.c.encounter_team_id, duels.c.home_score),
            else_=duels.c.away_score,
        )
        opponent_score = sa.case(
            (duels.c.home_encounter_team_id == hero_match.c.encounter_team_id, duels.c.away_score),
            else_=duels.c.home_score,
        )

        win_case = sa.case((team_score > opponent_score, 1), else_=0)
        loss_case = sa.case((team_score < opponent_score, 1), else_=0)
        draw_case = sa.case((team_score == opponent_score, 1), else_=0)

        hero_map_agg = (
            sa.select(
                hero_match.c.map_id.label("map_id"),
                hero_match.c.hero_id.label("hero_id"),
                sa.func.count(hero_match.c.match_id).label("games"),
                sa.func.sum(win_case).label("win"),
                sa.func.sum(loss_case).label("loss"),
                sa.func.sum(draw_case).label("draw"),
                (sa.func.sum(win_case) / sa.func.count(hero_match.c.match_id))
                .cast(sa.Numeric(10, 2))
                .label("win_rate"),
                sa.func.sum(
                    aggregate_order_by(
                        hero_match.c.playtime_seconds,
                        hero_match.c.match_id,
                        hero_match.c.encounter_team_id,
                    )
                ).label("playtime_seconds"),
            )
            .select_from(hero_match)
            .join(duels, duels.c.id == hero_match.c.match_id)
            .group_by(hero_match.c.map_id, hero_match.c.hero_id)
            .cte("hero_map_agg")
        )

        total_playtime_per_map = sa.func.sum(hero_map_agg.c.playtime_seconds).over(
            partition_by=hero_map_agg.c.map_id,
            order_by=hero_map_agg.c.hero_id,
            rows=(None, None),
        )
        playtime_share_on_map = (hero_map_agg.c.playtime_seconds / sa.func.nullif(total_playtime_per_map, 0)).label(
            "playtime_share_on_map"
        )

        ranked = (
            sa.select(
                hero_map_agg.c.map_id,
                hero_map_agg.c.hero_id,
                hero_map_agg.c.games,
                hero_map_agg.c.win,
                hero_map_agg.c.loss,
                hero_map_agg.c.draw,
                hero_map_agg.c.win_rate,
                hero_map_agg.c.playtime_seconds,
                playtime_share_on_map,
                sa.func.row_number()
                .over(
                    partition_by=hero_map_agg.c.map_id,
                    order_by=hero_map_agg.c.playtime_seconds.desc(),
                )
                .label("rn"),
            )
            .select_from(hero_map_agg)
            .subquery("hero_map_ranked")
        )

        query = (
            sa.select(
                models.CatalogEntity,
                ranked.c.map_id,
                ranked.c.games,
                ranked.c.win,
                ranked.c.loss,
                ranked.c.draw,
                ranked.c.win_rate,
                ranked.c.playtime_seconds,
                ranked.c.playtime_share_on_map,
            )
            .select_from(ranked)
            .join(models.CatalogEntity, models.CatalogEntity.id == ranked.c.hero_id)
            .where(
                ranked.c.rn <= limit_per_map,
                models.CatalogEntity.kind == "character",
                models.CatalogEntity.discipline == self.discipline,
            )
            .order_by(ranked.c.map_id, ranked.c.rn)
        )

        result = await session.execute(query)
        return result.all()  # type: ignore

    async def get_hero_leaderboard(
        self,
        session: AsyncSession,
        hero_id: int,
        tournament_id: int | None,
        stat: enums.LogStatsName,
        params: pagination.PaginationParams,
        workspace_id: int | None = None,
        *,
        grid: DivisionGrid | None,
    ) -> tuple[typing.Sequence[typing.Any], int]:
        hero_pt_alias = sa.alias(self._facts)

        base_conditions: list[typing.Any] = [
            self._facts.c.segment == 0,
            self._facts.c.entity_id == hero_id,
            self._facts.c.stat_code.in_(_LEADERBOARD_STATS),
            sa.exists(
                sa.select(sa.literal(1))
                .select_from(hero_pt_alias)
                .where(
                    hero_pt_alias.c.match_id == self._facts.c.match_id,
                    hero_pt_alias.c.workspace_member_id == self._facts.c.workspace_member_id,
                    hero_pt_alias.c.entity_id == hero_id,
                    hero_pt_alias.c.stat_code == enums.LogStatsName.HeroTimePlayed.value,
                    hero_pt_alias.c.segment == 0,
                    hero_pt_alias.c.value > 60,
                )
            ),
        ]

        if tournament_id is None:
            # Cross-tournament leaderboard: exclude hidden tournaments' stats. A
            # specific tournament_id is authorized upstream by the handler gate.
            base_conditions.append(
                self._facts.c.match_id.in_(
                    sa.select(self._matches.c.id)
                    .join(models.Encounter, models.Encounter.id == self._matches.c.encounter_id)
                    .where(models.Encounter.tournament_id.in_(visible_tournament_ids_subquery(None)))
                )
            )

        base_select = sa.select(
            self._facts.c.match_id,
            self._facts.c.workspace_member_id,
            self._facts.c.stat_id,
            self._facts.c.player_id.label("user_id"),
            self._facts.c.stat_code.label("name"),
            self._facts.c.value,
        ).where(*base_conditions)

        if tournament_id is not None:
            base_select = (
                base_select.join(self._matches, self._matches.c.id == self._facts.c.match_id)
                .join(models.Encounter, models.Encounter.id == self._matches.c.encounter_id)
                .where(models.Encounter.tournament_id == tournament_id)
            )

        if workspace_id is not None:
            if tournament_id is None:
                base_select = base_select.join(self._matches, self._matches.c.id == self._facts.c.match_id).join(
                    models.Encounter, models.Encounter.id == self._matches.c.encounter_id
                )
            base_select = base_select.join(
                models.Tournament, models.Tournament.id == models.Encounter.tournament_id
            ).where(models.Tournament.workspace_id == workspace_id)

        eligible_cte = base_select.cte("eligible")

        def _sum_stat(stat_name: enums.LogStatsName, col_label: str) -> sa.Label:  # type: ignore[type-arg]
            return sa.func.coalesce(
                sa.func.sum(
                    aggregate_order_by(
                        sa.case((eligible_cte.c.name == stat_name, eligible_cte.c.value), else_=0),
                        eligible_cte.c.match_id,
                        eligible_cte.c.workspace_member_id,
                        eligible_cte.c.stat_id,
                    )
                ),
                0,
            ).label(col_label)

        def _avg_pct(sum_col: sa.Column, count_col: sa.Column) -> sa.ColumnElement:  # type: ignore[type-arg]
            """AVG for percentage stats (WeaponAccuracy, CriticalHitAccuracy, etc.)"""
            return sa.func.coalesce(sum_col / sa.func.nullif(count_col, 0), 0).cast(sa.Numeric(10, 2))

        def _pct_count(stat_name: enums.LogStatsName, col_label: str) -> sa.Label:  # type: ignore[type-arg]
            return sa.func.sum(sa.case((eligible_cte.c.name == stat_name, 1), else_=0)).label(col_label)

        # Step 1: sum raw values per user
        sums_cte = (
            sa.select(
                eligible_cte.c.user_id,
                sa.func.sum(sa.case((eligible_cte.c.name == enums.LogStatsName.HeroTimePlayed, 1), else_=0)).label(
                    "games_played"
                ),
                _sum_stat(enums.LogStatsName.HeroTimePlayed, "total_playtime"),
                _sum_stat(enums.LogStatsName.Eliminations, "sum_eliminations"),
                _sum_stat(enums.LogStatsName.HealingDealt, "sum_healing"),
                _sum_stat(enums.LogStatsName.Deaths, "sum_deaths"),
                _sum_stat(enums.LogStatsName.HeroDamageDealt, "sum_damage"),
                _sum_stat(enums.LogStatsName.FinalBlows, "sum_final_blows"),
                _sum_stat(enums.LogStatsName.DamageBlocked, "sum_damage_blocked"),
                _sum_stat(enums.LogStatsName.SoloKills, "sum_solo_kills"),
                _sum_stat(enums.LogStatsName.ObjectiveKills, "sum_obj_kills"),
                _sum_stat(enums.LogStatsName.DefensiveAssists, "sum_defensive_assists"),
                _sum_stat(enums.LogStatsName.OffensiveAssists, "sum_offensive_assists"),
                _sum_stat(enums.LogStatsName.AllDamageDealt, "sum_all_damage"),
                _sum_stat(enums.LogStatsName.DamageTaken, "sum_damage_taken"),
                _sum_stat(enums.LogStatsName.SelfHealing, "sum_self_healing"),
                _sum_stat(enums.LogStatsName.UltimatesUsed, "sum_ultimates_used"),
                _sum_stat(enums.LogStatsName.Multikills, "sum_multikills"),
                _sum_stat(enums.LogStatsName.EnvironmentalKills, "sum_env_kills"),
                _sum_stat(enums.LogStatsName.CriticalHits, "sum_crit_hits"),
                # Percentage stats — need sum + count for proper AVG
                _sum_stat(enums.LogStatsName.WeaponAccuracy, "sum_weapon_accuracy"),
                _pct_count(enums.LogStatsName.WeaponAccuracy, "count_weapon_accuracy"),
                _sum_stat(enums.LogStatsName.CriticalHitAccuracy, "sum_crit_accuracy"),
                _pct_count(enums.LogStatsName.CriticalHitAccuracy, "count_crit_accuracy"),
            )
            .select_from(eligible_cte)
            .group_by(eligible_cte.c.user_id)
        ).cte("sums")

        def _per10(sum_col: sa.Column) -> sa.ColumnElement:  # type: ignore[type-arg]
            return sa.func.coalesce(sum_col * sa.literal(600.0) / sa.func.nullif(sums_cte.c.total_playtime, 0), 0).cast(
                sa.Numeric(10, 2)
            )

        # Step 2: derive per-10-min values from sums
        stats_agg_cte = (
            sa.select(
                sums_cte.c.user_id,
                sums_cte.c.games_played,
                sums_cte.c.total_playtime.cast(sa.Numeric(10, 0)).label("playtime_seconds"),
                _per10(sums_cte.c.sum_eliminations).label("per10_eliminations"),
                _per10(sums_cte.c.sum_healing).label("per10_healing"),
                _per10(sums_cte.c.sum_deaths).label("per10_deaths"),
                _per10(sums_cte.c.sum_damage).label("per10_damage"),
                _per10(sums_cte.c.sum_final_blows).label("per10_final_blows"),
                _per10(sums_cte.c.sum_damage_blocked).label("per10_damage_blocked"),
                _per10(sums_cte.c.sum_solo_kills).label("per10_solo_kills"),
                _per10(sums_cte.c.sum_obj_kills).label("per10_obj_kills"),
                _per10(sums_cte.c.sum_defensive_assists).label("per10_defensive_assists"),
                _per10(sums_cte.c.sum_offensive_assists).label("per10_offensive_assists"),
                _per10(sums_cte.c.sum_all_damage).label("per10_all_damage"),
                _per10(sums_cte.c.sum_damage_taken).label("per10_damage_taken"),
                _per10(sums_cte.c.sum_self_healing).label("per10_self_healing"),
                _per10(sums_cte.c.sum_ultimates_used).label("per10_ultimates_used"),
                _per10(sums_cte.c.sum_multikills).label("per10_multikills"),
                _per10(sums_cte.c.sum_env_kills).label("per10_env_kills"),
                _per10(sums_cte.c.sum_crit_hits).label("per10_crit_hits"),
                _avg_pct(sums_cte.c.sum_weapon_accuracy, sums_cte.c.count_weapon_accuracy).label("avg_weapon_accuracy"),
                _avg_pct(sums_cte.c.sum_crit_accuracy, sums_cte.c.count_crit_accuracy).label("avg_crit_accuracy"),
                # Derived ratios (not per-10-min — deaths cancel out)
                sa.func.coalesce(sums_cte.c.sum_eliminations / sa.func.nullif(sums_cte.c.sum_deaths, 0), 0)
                .cast(sa.Numeric(10, 2))
                .label("kd"),
                sa.func.coalesce(
                    (sums_cte.c.sum_eliminations + sums_cte.c.sum_offensive_assists + sums_cte.c.sum_defensive_assists)
                    / sa.func.nullif(sums_cte.c.sum_deaths, 0),
                    0,
                )
                .cast(sa.Numeric(10, 2))
                .label("kda"),
            )
            .select_from(sums_cte)
            .where(sums_cte.c.total_playtime >= 600)
        ).cte("stats_agg")

        player_rn_subq = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Player.name,
                models.Player.role,
                models.Player.sub_role,
                models.Player.rank,
                models.Player.tournament_id,
                models.Tournament.discipline,
                models.Team.id.label("team_id"),
                models.Team.name.label("team"),
                sa.func.row_number()
                .over(
                    partition_by=models.WorkspaceMember.player_id,
                    # The newest ranked event first, by the tournament chronology, not id: ids follow creation, not
                    # play. A player never ranked keeps the newest row and no division.
                    order_by=[models.Player.rank.is_(None), *(c.desc() for c in tournament_chrono_key())],
                )
                .label("rn"),
            )
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(models.Player.is_substitution.is_(False), models.Tournament.discipline == self.discipline)
        ).subquery("player_rn")

        # The division and the grid it is a number on, for each player's latest row only. A scoped read puts every
        # rank on the one request grid; the all-workspaces read reports the canonical number on the game's native
        # ladder (none without one), which is no stored grid version.
        versions: sa.CTE | None = None
        if workspace_id is not None:
            div_expr: sa.ColumnElement[typing.Any] = division_case_expr(player_rn_subq.c.rank, grid)
            grid_version_expr: sa.ColumnElement[typing.Any] = sa.literal(grid.version_id, sa.Integer)
        elif (ladder := ladder_grid(self.discipline)) is not None:
            versions = tournament_grid_versions(self.discipline)
            div_expr = canonical_division_expr(player_rn_subq.c.rank, versions.c.version_id, ladder)
            grid_version_expr = sa.null()
        else:
            div_expr = grid_version_expr = sa.null()

        player_latest_select = sa.select(
            player_rn_subq.c.user_id,
            player_rn_subq.c.name,
            player_rn_subq.c.role,
            player_rn_subq.c.sub_role,
            player_rn_subq.c.discipline,
            div_expr.label("div"),
            grid_version_expr.label("division_grid_version_id"),
            player_rn_subq.c.team_id,
            player_rn_subq.c.team,
        ).where(player_rn_subq.c.rn == 1)
        if versions is not None:
            player_latest_select = player_latest_select.join(
                versions, versions.c.tournament_id == player_rn_subq.c.tournament_id
            )
        player_latest_subq = player_latest_select.subquery("player_latest")

        sort_col_name = _STAT_COLUMN_MAP.get(stat, "per10_eliminations")
        sort_col = stats_agg_cte.c[sort_col_name]

        if enums.is_ascending_stat(stat):
            rank_order = sa.asc(sort_col)
        else:
            rank_order = sa.desc(sort_col)

        rank_expr = sa.func.dense_rank().over(order_by=rank_order).label("rank")

        ranked_cte = (
            sa.select(
                stats_agg_cte.c.user_id,
                player_latest_subq.c.name.label("player_name"),
                player_latest_subq.c.role,
                player_latest_subq.c.sub_role,
                player_latest_subq.c.discipline,
                player_latest_subq.c.div,
                player_latest_subq.c.division_grid_version_id,
                player_latest_subq.c.team_id,
                player_latest_subq.c.team,
                stats_agg_cte.c.games_played,
                stats_agg_cte.c.playtime_seconds,
                stats_agg_cte.c.per10_eliminations,
                stats_agg_cte.c.per10_healing,
                stats_agg_cte.c.per10_deaths,
                stats_agg_cte.c.per10_damage,
                stats_agg_cte.c.per10_final_blows,
                stats_agg_cte.c.per10_damage_blocked,
                stats_agg_cte.c.per10_solo_kills,
                stats_agg_cte.c.per10_obj_kills,
                stats_agg_cte.c.per10_defensive_assists,
                stats_agg_cte.c.per10_offensive_assists,
                stats_agg_cte.c.per10_all_damage,
                stats_agg_cte.c.per10_damage_taken,
                stats_agg_cte.c.per10_self_healing,
                stats_agg_cte.c.per10_ultimates_used,
                stats_agg_cte.c.per10_multikills,
                stats_agg_cte.c.per10_env_kills,
                stats_agg_cte.c.per10_crit_hits,
                stats_agg_cte.c.avg_weapon_accuracy,
                stats_agg_cte.c.avg_crit_accuracy,
                stats_agg_cte.c.kd,
                stats_agg_cte.c.kda,
                rank_expr,
            )
            .select_from(stats_agg_cte)
            .join(player_latest_subq, player_latest_subq.c.user_id == stats_agg_cte.c.user_id)
        ).cte("ranked")

        total_query = sa.select(sa.func.count()).select_from(ranked_cte)
        query = params.apply_pagination(sa.select(ranked_cte).order_by(ranked_cte.c.rank))

        result = await session.execute(query)
        total = await session.execute(total_query)
        return result.all(), total.scalar_one()
