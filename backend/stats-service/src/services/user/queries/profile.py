"""Profile / dossier read queries for one user."""

import typing

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums, pagination
from shared.core.chrono import tournament_chrono_key
from shared.disciplines import discipline
from shared.models.stats.match import mv_entity_global_stats
from shared.schemas.role import RoleRef
from shared.services.division_grid.access import tournament_effective_version_id_expr
from src.services.discipline_queries import DisciplineQueries
from src.services.encounter_seats import Seat

from ._scope import (
    _build_eligible_hero_stats_cte,
    _hero_direction_score,
    _team_load_options,
    team_has_played_encounter,
    user_entities,
)


class UserProfileQueries(DisciplineQueries):
    """Single-user reads: tournaments, roles and hero statistics."""

    async def get(self, session: AsyncSession, user_id: int, entities: list[str]) -> models.User | None:
        """A user by ID, with the related entities named in ``entities`` eager-loaded."""
        query = sa.select(models.User).options(*user_entities(entities)).where(sa.and_(models.User.id == user_id))
        result = await session.execute(query)
        return result.unique().scalar_one_or_none()

    async def get_overall_statistics(
        self, session: AsyncSession, user_id: int, workspace_id: int | None = None
    ) -> tuple[int, int, int]:
        """A user's ``(maps won, maps lost, average encounter closeness)`` across this game's (or, unbound, every game's)
        tournaments, or the workspace's tournaments of this game when ``workspace_id`` is given.
        """

        seat = Seat()

        q = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                seat.maps_won.label("maps_won"),
                seat.maps_lost.label("maps_lost"),
                models.Encounter.closeness.label("closeness"),
            )
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.Player.is_substitution.is_(False),
                models.WorkspaceMember.player_id == user_id,
            )
        )
        q = seat.join(q, models.Team.id)
        q = q.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id).where(
            *self.discipline_filter(models.Tournament.discipline)
        )
        if workspace_id is not None:
            q = q.where(models.Tournament.workspace_id == workspace_id)
        sides = q.subquery("profile_map_sides")
        query = (
            sa.select(
                sa.func.sum(sides.c.maps_won).label("won_maps"),
                sa.func.sum(sides.c.maps_lost).label("lost_maps"),
                sa.func.avg(sides.c.closeness).label("closeness"),
            )
            .select_from(sides)
            .group_by(sides.c.user_id)
        )
        matches = await session.execute(query)
        return matches.first()

    async def get_teams(
        self,
        session: AsyncSession,
        user_id: int,
        params: pagination.PaginationSortParams,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[models.Team], int]:
        """Paginated teams a user has played for, plus the total count.

        Scoped exactly like ``get_tournaments_with_stats`` (which powers the
        Tournaments tab): a tournament belongs to a user's history as soon as the
        user has played an encounter in it, not once ``is_finished`` flips, so a
        player whose only event is the live one agrees with every other read (maps,
        heroes, roles, encounters). Hidden tournaments never appear.
        """
        played_encounter = team_has_played_encounter()
        scope = (
            models.WorkspaceMember.player_id == user_id,
            models.Player.is_substitution.is_(False),
            models.Tournament.is_hidden.is_(False),
            played_encounter,
        )

        total_query = (
            sa.select(sa.func.count(sa.distinct(models.Team.id)))
            .join(models.Player, models.Player.team_id == models.Team.id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(sa.and_(*scope))
        )

        query = (
            sa.select(models.Team)
            .options(*_team_load_options(params.entities))
            .join(models.Player, models.Player.team_id == models.Team.id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(sa.and_(*scope))
        )
        if workspace_id is not None:
            total_query = total_query.where(models.Tournament.workspace_id == workspace_id)
            query = query.where(models.Tournament.workspace_id == workspace_id)

        query = params.apply_pagination_sort(query, models.Team)
        result = await session.scalars(query)
        teams = result.unique().all()
        if params.per_page == -1:
            return teams, len(teams)
        result_total = await session.execute(total_query)
        return teams, result_total.scalar_one()

    async def get_roles(
        self, session: AsyncSession, user_id: int, workspace_id: int | None = None
    ) -> typing.Sequence[tuple[RoleRef | None, int, int, list[dict]]]:
        """Per-role ``(role, maps won, maps lost, tournament entries)`` rows for a user.

        Each tournament entry is a dict of ``tournament``, ``rank``, ``recency`` and
        ``division_grid_version_id`` — the tournament's *effective* grid version
        (own pin, else its workspace default, else the system default). The rank
        is raw, so the caller resolves the division against the grid version that
        tournament was actually played on. Entries come newest event first by the tournament chronology (start, end,
        then id): ids follow creation, not play, across workspaces. ``recency`` is
        that order across ALL of the user's tournaments here (1 = newest), so entries of different roles compare.
        """

        seat = Seat()
        start, end, _ = tournament_chrono_key()

        q = (
            sa.select(
                models.Player.role,
                models.Tournament.discipline,
                models.Player.sub_role,
                seat.maps_won.label("maps_won"),
                seat.maps_lost.label("maps_lost"),
                models.Team.tournament_id.label("tournament_id"),
                models.Player.rank.label("rank"),
                start.label("chrono_start"),
                end.label("chrono_end"),
                sa.func.dense_rank().over(order_by=[*(c.desc() for c in tournament_chrono_key())]).label("recency"),
                tournament_effective_version_id_expr(models.Team.tournament_id).label("division_grid_version_id"),
            )
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(models.Tournament.discipline == self.discipline)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.Player.is_substitution.is_(False),
                models.WorkspaceMember.player_id == user_id,
            )
        )
        q = seat.join(q, models.Team.id)
        if workspace_id is not None:
            q = q.where(models.Tournament.workspace_id == workspace_id)
        sides = q.subquery("profile_role_sides")
        query = (
            sa.select(
                sides.c.role,
                sides.c.discipline,
                sides.c.sub_role,
                sa.func.sum(sides.c.maps_won).label("won_maps"),
                sa.func.sum(sides.c.maps_lost).label("lost_maps"),
                sa.func.jsonb_agg(
                    aggregate_order_by(
                        sa.func.jsonb_build_object(
                            "tournament",
                            sides.c.tournament_id,
                            "rank",
                            sides.c.rank,
                            "division_grid_version_id",
                            sides.c.division_grid_version_id,
                            "recency",
                            sides.c.recency,
                        ),
                        sides.c.chrono_start.desc(),
                        sides.c.chrono_end.desc(),
                        sides.c.tournament_id.desc(),
                    )
                ),
            )
            .select_from(sides)
            .group_by(sides.c.role, sides.c.discipline, sides.c.sub_role)
        )
        result = await session.execute(query)
        return [
            (RoleRef.of(discipline(code).rated_dimension.code, role, sub_role), won, lost, entries)
            for role, code, sub_role, won, lost, entries in result.all()
        ]

    async def get_tournaments_with_stats(
        self,
        session: AsyncSession,
        user_id: int,
        workspace_id: int | None = None,
    ) -> typing.Sequence[tuple[models.Team, int, int, int]]:
        """A user's tournament history as ``(team, maps won, maps lost, average encounter
        closeness)`` rows.
        """

        seat = Seat()

        q = (
            sa.select(
                models.Team.id.label("team_id"),
                seat.maps_won.label("maps_won"),
                seat.maps_lost.label("maps_lost"),
                models.Encounter.closeness.label("closeness"),
            )
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id == user_id,
                models.Player.is_substitution.is_(False),
                # Hidden tournaments never appear in a user's public
                # tournament list. This read is cashews-cached without the viewer,
                # so exclude unconditionally; admins/allowlisted view hidden
                # tournaments through the gated tournament pages instead.
                models.Tournament.is_hidden.is_(False),
            )
        )
        q = seat.join(q, models.Team.id)
        if workspace_id is not None:
            q = q.where(models.Tournament.workspace_id == workspace_id)
        sides = q.subquery("profile_tournament_sides")
        agg = (
            sa.select(
                sides.c.team_id,
                sa.func.sum(sides.c.maps_won).label("won_maps"),
                sa.func.sum(sides.c.maps_lost).label("lost_maps"),
                sa.func.avg(sides.c.closeness).label("closeness"),
            )
            .group_by(sides.c.team_id)
            .subquery("profile_tournament_stats")
        )
        query = (
            sa.select(
                models.Team,
                agg.c.won_maps,
                agg.c.lost_maps,
                agg.c.closeness,
            )
            # Only the columns of the tournament and the team's standings are read (``get_tournaments``).
            .options(
                selectinload(models.Team.players).selectinload(models.Player.workspace_member),
                selectinload(models.Team.tournament),
                selectinload(models.Team.standings),
            )
            .join(agg, agg.c.team_id == models.Team.id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
            # Newest event first by the tournament chronology (an undated tournament at its creation time).
            .order_by(*(c.desc() for c in tournament_chrono_key()))
        )

        result = await session.execute(query)
        return result.unique().all()

    async def get_tournament_stats_overall(
        self, session: AsyncSession, tournament: models.Tournament, user_id: int
    ) -> tuple[int, int, int, float]:
        """A user's totals for one tournament: ``(maps won, maps lost, average encounter
        closeness, total playtime in seconds)``.
        """

        seat = Seat(name="playtime_seat")
        playtime_query = (
            sa.select(self._facts.c.value, self._facts.c.match_id, self._facts.c.workspace_member_id)
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id == user_id,
                models.Player.is_substitution.is_(False),
                models.Team.tournament_id == tournament.id,
                self._facts.c.player_id == models.WorkspaceMember.player_id,
                self._facts.c.stat_code == enums.LogStatsName.HeroTimePlayed,
                self._facts.c.entity_id.is_(None),
                self._facts.c.segment == 0,
            )
        )
        playtime_query = (
            seat.join(playtime_query, models.Team.id, duel=False)
            .join(self._matches, self._matches.c.encounter_id == models.Encounter.id)
            .join(self._facts, self._facts.c.match_id == self._matches.c.id)
        )
        playtime_rows = playtime_query.subquery("profile_playtime_sides")
        playtime_subquery = sa.select(
            sa.func.sum(
                aggregate_order_by(
                    playtime_rows.c.value,
                    playtime_rows.c.match_id,
                    playtime_rows.c.workspace_member_id,
                )
            )
        ).scalar_subquery()

        maps_seat = Seat(name="maps_seat")
        maps_query = (
            sa.select(
                maps_seat.maps_won.label("maps_won"),
                maps_seat.maps_lost.label("maps_lost"),
                models.Encounter.closeness.label("closeness"),
            )
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id == user_id,
                models.Player.is_substitution.is_(False),
                models.Team.tournament_id == tournament.id,
            )
        )
        map_sides = maps_seat.join(maps_query, models.Team.id).subquery("profile_tournament_map_sides")
        query = sa.select(
            sa.func.coalesce(sa.func.sum(map_sides.c.maps_won), 0).label("won_maps"),
            sa.func.coalesce(sa.func.sum(map_sides.c.maps_lost), 0).label("lost_maps"),
            sa.func.coalesce(sa.func.avg(map_sides.c.closeness), 0).label("closeness"),
            sa.func.coalesce(playtime_subquery, 0).label("playtime"),
        ).select_from(map_sides)
        result = await session.execute(query)
        row = result.one_or_none()
        if not row:
            return 0, 0, 0, 0

        won_maps, lost_maps, closeness, playtime = row
        return won_maps, lost_maps, closeness, playtime

    def _statistics_by_heroes_query(
        self,
        *,
        user_id: int,
        stats: list[enums.LogStatsName] | None,
        tournament_id: int | None,
        workspace_id: int | None,
    ) -> sa.Select:
        """Build the per-(hero, stat) totals + best-performance query for one user.

        Rank the slim eligible native facts before hydrating the winning row's
        map and tournament metadata; match duration remains the per-10 denominator.
        """
        eligible_stats = _build_eligible_hero_stats_cte(
            discipline=self.discipline,
            user_id=user_id,
            stats=stats,
            cte_name="eligible_user_hero_stats",
            tournament_id=tournament_id,
            workspace_id=workspace_id,
        )
        direction_score = _hero_direction_score(eligible_stats.c.value, eligible_stats.c.stat_code)

        # One match duration per eligible stat row, not character playtime.
        # Match/member order is the native MV contract; never depend on heap/group-sort ties.
        reduction_order = (eligible_stats.c.match_id, eligible_stats.c.workspace_member_id)
        agg_cte = (
            sa.select(
                eligible_stats.c.entity_id,
                eligible_stats.c.stat_code,
                sa.func.sum(aggregate_order_by(eligible_stats.c.value, *reduction_order)).label("total_value"),
                sa.func.sum(aggregate_order_by(self._matches.c.duration_s, *reduction_order)).label("total_time"),
            )
            .select_from(eligible_stats)
            .join(self._matches, self._matches.c.id == eligible_stats.c.match_id)
            .group_by(eligible_stats.c.entity_id, eligible_stats.c.stat_code)
            .cte("hero_stats_agg")
        )

        # Best-value ties prefer the newer match id.
        ranked_cte = (
            sa.select(
                eligible_stats.c.entity_id,
                eligible_stats.c.stat_code,
                eligible_stats.c.match_id,
                eligible_stats.c.value,
                sa.func.row_number()
                .over(
                    partition_by=[
                        eligible_stats.c.entity_id,
                        eligible_stats.c.stat_code,
                    ],
                    order_by=[direction_score.desc(), eligible_stats.c.match_id.desc()],
                )
                .label("row_num"),
            )
            .select_from(eligible_stats)
            .cte("hero_stats_ranked")
        )

        # Hydrate map/tournament metadata only for the winning row per (hero, stat). MATERIALIZED: the planner
        # estimates the eligible facts at one row, and an inlined CTE is then re-run per aggregate row (O(heroes x stats)
        # window sorts, 14s for a 1.4k-row career).
        best_result_cte = (
            sa.select(
                ranked_cte.c.entity_id,
                ranked_cte.c.stat_code,
                ranked_cte.c.value.label("best_value"),
                self._matches.c.encounter_id,
                models.CatalogEntity.name.label("map_name"),
                models.CatalogEntity.image_path.label("map_link"),
                models.Tournament.name.label("tournament_name"),
            )
            .select_from(ranked_cte)
            .join(self._matches, self._matches.c.id == ranked_cte.c.match_id)
            .join(
                models.CatalogEntity,
                sa.and_(
                    models.CatalogEntity.id == self._matches.c.map_entity_id,
                    models.CatalogEntity.kind == "map",
                    models.CatalogEntity.discipline == self.discipline,
                ),
            )
            .join(models.Encounter, models.Encounter.id == self._matches.c.encounter_id)
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(models.Tournament.discipline == self.discipline)
            .where(ranked_cte.c.row_num == 1)
            .cte("best_result_cte")
            .prefix_with("MATERIALIZED")
        )

        return (
            sa.select(
                agg_cte.c.stat_code,
                models.CatalogEntity,
                agg_cte.c.total_value.label("total_value"),
                best_result_cte.c.best_value.label("best_value"),
                (agg_cte.c.total_value / sa.func.nullif(agg_cte.c.total_time, 0) * 600).label("avg_per_10min"),
                sa.func.jsonb_build_object(
                    "encounter_id",
                    best_result_cte.c.encounter_id,
                    "map_name",
                    best_result_cte.c.map_name,
                    "map_image_path",
                    best_result_cte.c.map_link,
                    "tournament_name",
                    best_result_cte.c.tournament_name,
                ).label("best_metadata"),
            )
            .select_from(agg_cte)
            .join(models.CatalogEntity, models.CatalogEntity.id == agg_cte.c.entity_id)
            .join(
                best_result_cte,
                sa.and_(
                    best_result_cte.c.entity_id == agg_cte.c.entity_id,
                    best_result_cte.c.stat_code == agg_cte.c.stat_code,
                ),
            )
            .where(models.CatalogEntity.kind == "character", models.CatalogEntity.discipline == self.discipline)
        )

    async def get_statistics_by_heroes(
        self,
        session: AsyncSession,
        user_id: int,
        stats: list[enums.LogStatsName] | None = None,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
    ) -> typing.Sequence[tuple[enums.LogStatsName, models.CatalogEntity, float, float, float, dict]]:
        """A user's hero statistics as ``(stat name, hero, total, best value, per-10-minute
        average, best-performance metadata)`` rows.

        The metadata dict carries the encounter id, map name, map image path and
        tournament name of the best result.
        """
        query = self._statistics_by_heroes_query(
            user_id=user_id,
            stats=stats,
            tournament_id=tournament_id,
            workspace_id=workspace_id,
        )
        result = await session.execute(query)
        return [(enums.LogStatsName(code), *values) for code, *values in result.all()]

    def _read_hero_global_stats_query(self, stats: list[enums.LogStatsName] | None) -> sa.Select:
        """Global OW records from the native MV; workspace reads use scoped facts."""
        mv = mv_entity_global_stats
        query = (
            sa.select(
                models.StatDef.code,
                mv.c.entity_id,
                mv.c.best_value,
                mv.c["avg"],
                mv.c["metadata"],
            )
            .select_from(mv)
            .join(
                models.StatDef,
                sa.and_(
                    models.StatDef.id == mv.c.stat_id,
                    models.StatDef.discipline == mv.c.discipline,
                ),
            )
            .where(mv.c.discipline == self.discipline)
        )
        if stats:
            query = query.where(models.StatDef.code.in_([stat.value for stat in stats]))
        return query.order_by(mv.c.entity_id)

    async def get_statistics_by_heroes_all_values(
        self,
        session: AsyncSession,
        stats: list[enums.LogStatsName] | None = None,
    ) -> typing.Sequence[tuple[enums.LogStatsName, int, float, float, dict]]:
        """Best value (+ metadata) and global per-10min average for every (hero, stat).

        An unpopulated native MV is an operational error, not an empty result.
        ``stats=None`` reads every OW stat; a non-empty list narrows the view scan.
        """
        result = await session.execute(self._read_hero_global_stats_query(stats))
        return [(enums.LogStatsName(code), *values) for code, *values in result.all()]

    async def get_best_teammates(
        self,
        session: AsyncSession,
        user_id: int,
        params: pagination.PaginationSortParams,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[tuple[models.User, float, int, int, float | None, float | None]], int]:
        """A user's best teammates as ``(teammate, win rate together, tournaments together,
        distinct maps together, average impact rank, average KDA)`` rows, plus the total count.
        """
        self_player = sa.orm.aliased(models.Player, name="self_player")
        teammate_player = sa.orm.aliased(models.Player, name="teammate_player")
        self_member = sa.orm.aliased(models.WorkspaceMember, name="self_member")
        teammate_member = sa.orm.aliased(models.WorkspaceMember, name="teammate_member")

        shared_teams_select = (
            sa.select(
                teammate_member.player_id.label("teammate_id"),
                teammate_player.team_id.label("team_id"),
                teammate_player.tournament_id.label("tournament_id"),
            )
            .select_from(self_player)
            .join(teammate_player, teammate_player.team_id == self_player.team_id)
            .join(self_member, self_member.id == self_player.workspace_member_id)
            .join(teammate_member, teammate_member.id == teammate_player.workspace_member_id)
            .join(models.Tournament, models.Tournament.id == self_player.tournament_id)
            .where(
                self_member.player_id == user_id,
                self_player.is_substitution.is_(False),
                teammate_player.is_substitution.is_(False),
                teammate_member.player_id != user_id,
                models.Tournament.discipline == self.discipline,
            )
            .distinct()
        )

        if workspace_id is not None:
            shared_teams_select = shared_teams_select.where(models.Tournament.workspace_id == workspace_id)

        shared_teams = shared_teams_select.cte("shared_teams")

        encounter_seat = Seat(name="teammate_seat")
        teammate_encounters = encounter_seat.join(
            sa.select(
                shared_teams.c.teammate_id.label("teammate_id"),
                models.Encounter.tournament_id.label("tournament_id"),
                encounter_seat.maps_won.label("won_score"),
                encounter_seat.maps_lost.label("lost_score"),
            ).select_from(shared_teams),
            shared_teams.c.team_id,
        ).cte("teammate_encounters")

        teammates_query = (
            sa.select(
                teammate_encounters.c.teammate_id.label("user_id"),
                (
                    sa.func.sum(teammate_encounters.c.won_score)
                    / sa.func.nullif(
                        sa.func.sum(teammate_encounters.c.won_score + teammate_encounters.c.lost_score),
                        0,
                    )
                ).label("winrate"),
                sa.func.count(sa.distinct(teammate_encounters.c.tournament_id)).label("tournaments"),
            )
            .group_by(teammate_encounters.c.teammate_id)
            .having(sa.func.count(sa.distinct(teammate_encounters.c.tournament_id)) > 1)
        ).cte("teammates_query")

        # Teammate "MVP" column is the per-match ImpactRank average (a match without one does not count), same as
        # services.user.queries.encounters.get_roster_avg_mvp_bulk. First collapse each match's rows into one
        # (impact_rank, kda) pair via an outer join (keeps a teammate with zero stat rows in the result with
        # NULLs), THEN average per teammate.
        teammate_codes = [enums.LogStatsName.ImpactRank, enums.LogStatsName.KDA]
        stats_per_match = (
            sa.select(
                shared_teams.c.teammate_id.label("user_id"),
                self._facts.c.match_id.label("match_id"),
                sa.func.max(
                    sa.case((self._facts.c.stat_code == enums.LogStatsName.ImpactRank, self._facts.c.value))
                ).label("impact_rank"),
                sa.func.max(sa.case((self._facts.c.stat_code == enums.LogStatsName.KDA, self._facts.c.value))).label(
                    "kda"
                ),
            )
            .select_from(shared_teams)
            .join(teammates_query, teammates_query.c.user_id == shared_teams.c.teammate_id)
            .outerjoin(
                self._facts,
                sa.and_(
                    self._facts.c.tournament_team_id == shared_teams.c.team_id,
                    self._facts.c.player_id == shared_teams.c.teammate_id,
                    self._facts.c.segment == 0,
                    self._facts.c.entity_id.is_(None),
                    self._facts.c.stat_code.in_(teammate_codes),
                    # The same stats by id: lets the fact index probe (member, stat) directly instead of reading every
                    # stat of each match and joining stat_def per row (44k lookups for a 950-match career).
                    self._facts.c.stat_id.in_(
                        sa.select(models.StatDef.id).where(
                            models.StatDef.discipline == self.discipline, models.StatDef.code.in_(teammate_codes)
                        )
                    ),
                ),
            )
            .group_by(shared_teams.c.teammate_id, self._facts.c.match_id)
        ).cte("teammate_stats_per_match")

        mvp_placement = stats_per_match.c.impact_rank
        # MATERIALIZED (and maps_query below): under pgBouncer the statement is a reused server-side prepared
        # statement, and its generic plan estimates teammates_query at one row and re-runs an inlined aggregate once
        # per teammate (1.1s instead of 70ms).
        stats_query = (
            sa.select(
                stats_per_match.c.user_id,
                sa.func.avg(aggregate_order_by(mvp_placement, stats_per_match.c.match_id)).label("impact_rank"),
                sa.func.avg(aggregate_order_by(stats_per_match.c.kda, stats_per_match.c.match_id)).label("kda"),
            )
            .group_by(stats_per_match.c.user_id)
            .cte("stats_query")
            .prefix_with("MATERIALIZED")
        )

        # Distinct maps played together (separate CTE so the encounter→match fan-out
        # does not skew the winrate/tournament aggregates in teammates_query).
        map_seat = Seat(name="teammate_map_seat")
        map_sides = (
            map_seat.join(
                sa.select(
                    shared_teams.c.teammate_id.label("user_id"),
                    self._matches.c.map_entity_id.label("map_id"),
                )
                .select_from(shared_teams)
                .join(teammates_query, teammates_query.c.user_id == shared_teams.c.teammate_id),
                shared_teams.c.team_id,
                duel=False,
            )
            .outerjoin(self._matches, self._matches.c.encounter_id == models.Encounter.id)
            .subquery("teammate_map_sides")
        )
        maps_query = (
            sa.select(
                map_sides.c.user_id,
                sa.func.count(sa.distinct(map_sides.c.map_id)).label("maps"),
            )
            .group_by(map_sides.c.user_id)
            .cte("maps_query")
            .prefix_with("MATERIALIZED")
        )

        count_query = sa.select(sa.func.count(teammates_query.c.user_id))

        query = (
            sa.select(
                models.User,
                teammates_query.c.winrate,
                teammates_query.c.tournaments,
                maps_query.c.maps,
                stats_query.c.impact_rank,
                stats_query.c.kda,
            )
            .select_from(teammates_query)
            .join(models.User, models.User.id == teammates_query.c.user_id)
            .join(stats_query, stats_query.c.user_id == teammates_query.c.user_id)
            .join(maps_query, maps_query.c.user_id == teammates_query.c.user_id)
        )

        query = params.apply_pagination_sort(query)
        result = await session.execute(query)
        count_result = await session.execute(count_query)
        return result.all(), count_result.scalar_one()  # type: ignore
