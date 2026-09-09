"""Overview / catalog list queries for the ``/users`` grid."""

import typing
from collections import defaultdict

import sqlalchemy as sa
from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.division_grid import DivisionGrid
from shared.services.achievement_effective import build_effective_achievement_rows_subquery
from src import models
from src.core import config, enums, pagination

from ._scope import (
    _apply_overview_role_filters,
    _apply_workspace_member_filter,
    _compare_player_scope_filters,
    _compare_team_scope_exists,
    _compare_tournament_scope_exists,
    union_encounter_team_sides,
)

if typing.TYPE_CHECKING:
    from src import schemas as app_schemas

# Overview sorts whose ORDER BY is a correlated scalar subquery evaluated over the
# whole filtered population (not just the page). Cached id-order applies to these.
_EXPENSIVE_OVERVIEW_SORTS = frozenset({"tournaments_count", "achievements_count", "avg_placement"})

OVERVIEW_HERO_METRICS: tuple[enums.LogStatsName, ...] = (
    enums.LogStatsName.Eliminations,
    enums.LogStatsName.FinalBlows,
    enums.LogStatsName.HeroDamageDealt,
    enums.LogStatsName.HealingDealt,
)


class UserOverviewQueries:
    """Population-wide list queries: the users grid, its KPI header and the catalog."""

    def _overview_scope_where(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: enums.HeroClass | None,
        div_min: int | None,
        div_max: int | None,
        tournament_id: int | None,
        grid: DivisionGrid,
        extra: typing.Sequence[typing.Any] = (),
    ) -> list[typing.Any]:
        """WHERE list shared by every correlated overview aggregate.

        ``extra`` slots in between the finished/league predicates and the
        optional tournament pin, which is where each caller used to put its own
        extra predicate — keeping the emitted SQL order unchanged.
        """
        where_conditions: list[typing.Any] = [
            *_compare_player_scope_filters(
                models.Player,
                user_id_column,
                role=role,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                grid=grid,
            ),
            models.Tournament.is_finished.is_(True),
            models.Tournament.is_league.is_(False),
            *extra,
        ]
        if tournament_id is not None:
            where_conditions.append(models.Tournament.id == tournament_id)
        return where_conditions

    @staticmethod
    def _overview_standing_select(*columns: typing.Any) -> sa.Select:
        """Player -> Team -> Tournament -> Standing chain (placement aggregates)."""
        return (
            sa.select(*columns)
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .join(
                models.Standing,
                sa.and_(
                    models.Standing.team_id == models.Player.team_id,
                    models.Standing.tournament_id == models.Player.tournament_id,
                ),
            )
        )

    def _overview_encounter_select(
        self,
        build_columns: typing.Callable[[typing.Any, typing.Any, typing.Any], typing.Sequence[typing.Any]],
        *where_conditions: typing.Any,
    ) -> sa.CompoundSelect:
        """Player -> Team -> Encounter -> Tournament via UNION ALL of equality joins.

        `home_team_id = team.id OR away_team_id = team.id` cannot use either FK
        index (OWT-TOURNAMENTS-21T). Same split as page-level closeness.
        `build_columns(team_fk, maps_won, maps_lost)` is evaluated per side;
        wrap the union in AVG/SUM yourself.
        """

        def _side(team_fk, won, lost):
            return (
                sa.select(*build_columns(team_fk, won, lost))
                .select_from(models.Player)
                .join(models.Team, models.Team.id == models.Player.team_id)
                .join(models.Encounter, team_fk == models.Team.id)
                .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
                .where(*where_conditions)
            )

        return union_encounter_team_sides(_side)

    def _overview_tournaments_count_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.ScalarSelect:
        where_conditions = self._overview_scope_where(
            user_id_column,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
        )
        return (
            sa.select(sa.func.count(sa.distinct(models.Team.tournament_id)))
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(*where_conditions)
            .scalar_subquery()
        )

    def _overview_achievements_count_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.ScalarSelect:
        effective_rows = build_effective_achievement_rows_subquery(
            user_ids=None,
            name="overview_effective_achievement_rows",
        )
        query = sa.select(sa.func.count(sa.distinct(effective_rows.c.achievement_rule_id))).where(
            effective_rows.c.user_id == user_id_column
        )

        if role is None and div_min is None and div_max is None and tournament_id is None:
            return query.scalar_subquery()

        achievement_match = aliased(models.Match)
        achievement_encounter = aliased(models.Encounter)
        tournament_scope = _compare_tournament_scope_exists(
            user_id_column,
            effective_rows.c.tournament_id,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
        )
        match_scope = sa.exists(
            sa.select(1)
            .select_from(achievement_match)
            .join(achievement_encounter, achievement_encounter.id == achievement_match.encounter_id)
            .where(
                achievement_match.id == effective_rows.c.match_id,
                _compare_tournament_scope_exists(
                    user_id_column,
                    achievement_encounter.tournament_id,
                    role=role,
                    div_min=div_min,
                    div_max=div_max,
                    tournament_id=tournament_id,
                    grid=grid,
                ),
            )
        )

        return query.where(sa.or_(tournament_scope, match_scope)).scalar_subquery()

    def _overview_avg_placement_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.ScalarSelect:
        where_conditions = self._overview_scope_where(
            user_id_column,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
        )
        team_placement_subquery = (
            self._overview_standing_select(
                models.Player.team_id.label("team_id"),
                sa.func.min(models.Standing.overall_position).label("overall_position"),
            )
            .where(*where_conditions)
            .group_by(models.Player.team_id)
            .subquery()
        )

        return (
            sa.select(sa.func.avg(team_placement_subquery.c.overall_position))
            .select_from(team_placement_subquery)
            .scalar_subquery()
        )

    def _overview_avg_playoff_placement_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.ScalarSelect:
        where_conditions = self._overview_scope_where(
            user_id_column,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
            extra=(models.Standing.buchholz.is_(None),),
        )
        return (
            self._overview_standing_select(sa.func.avg(models.Standing.position))
            .where(*where_conditions)
            .scalar_subquery()
        )

    def _overview_avg_group_placement_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.ScalarSelect:
        where_conditions = self._overview_scope_where(
            user_id_column,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
            extra=(models.Standing.buchholz.isnot(None),),
        )
        return (
            self._overview_standing_select(sa.func.avg(models.Standing.position))
            .where(*where_conditions)
            .scalar_subquery()
        )

    def _overview_avg_closeness_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.ScalarSelect:
        where_conditions = self._overview_scope_where(
            user_id_column,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
            extra=(models.Encounter.closeness.isnot(None),),
        )
        sides = self._overview_encounter_select(
            lambda _fk, _won, _lost: (models.Encounter.closeness.label("value"),),
            *where_conditions,
        ).subquery("overview_avg_closeness_sides")
        return sa.select(sa.func.avg(sides.c.value)).select_from(sides).scalar_subquery()

    def _overview_maps_won_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.ScalarSelect:
        where_conditions = self._overview_scope_where(
            user_id_column,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
        )
        sides = self._overview_encounter_select(
            lambda _fk, won, _lost: (won.label("value"),),
            *where_conditions,
        ).subquery("overview_maps_won_sides")
        return sa.select(sa.func.coalesce(sa.func.sum(sides.c.value), 0)).select_from(sides).scalar_subquery()

    def _overview_maps_lost_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.ScalarSelect:
        where_conditions = self._overview_scope_where(
            user_id_column,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
        )
        sides = self._overview_encounter_select(
            lambda _fk, _won, lost: (lost.label("value"),),
            *where_conditions,
        ).subquery("overview_maps_lost_sides")
        return sa.select(sa.func.coalesce(sa.func.sum(sides.c.value), 0)).select_from(sides).scalar_subquery()

    def _overview_match_stat_avg_10_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        stat: enums.LogStatsName,
        *,
        role: enums.HeroClass | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
    ) -> sa.ScalarSelect:
        hero_time_alias = aliased(models.MatchStatistics)
        where_conditions: list[typing.Any] = [
            models.MatchStatistics.user_id == user_id_column,
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.isnot(None),
            models.MatchStatistics.name == stat,
            sa.exists(
                sa.select(1)
                .select_from(hero_time_alias)
                .where(
                    hero_time_alias.match_id == models.MatchStatistics.match_id,
                    hero_time_alias.user_id == models.MatchStatistics.user_id,
                    hero_time_alias.hero_id == models.MatchStatistics.hero_id,
                    hero_time_alias.name == enums.LogStatsName.HeroTimePlayed,
                    hero_time_alias.round == 0,
                    hero_time_alias.value > 60,
                )
            ),
        ]

        if role is not None or div_min is not None or div_max is not None:
            where_conditions.append(
                _compare_team_scope_exists(
                    user_id_column,
                    models.MatchStatistics.team_id,
                    role=role,
                    div_min=div_min,
                    div_max=div_max,
                    tournament_id=tournament_id,
                    grid=grid,
                )
            )

        query = (
            sa.select(
                sa.func.sum(models.MatchStatistics.value) / sa.func.nullif(sa.func.sum(models.Match.time), 0) * 600
            )
            .select_from(models.MatchStatistics)
            .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        )

        if tournament_id is not None:
            query = query.join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
            where_conditions.append(models.Encounter.tournament_id == tournament_id)

        return query.where(*where_conditions).scalar_subquery()

    def _overview_sort_expr(self, sort_key: str, grid: DivisionGrid) -> sa.ColumnElement[typing.Any]:
        if sort_key == "tournaments_count":
            return self._overview_tournaments_count_expr(models.User.id, grid=grid)
        if sort_key == "achievements_count":
            return self._overview_achievements_count_expr(models.User.id, grid=grid)
        if sort_key == "avg_placement":
            return self._overview_avg_placement_expr(models.User.id, grid=grid)
        return models.User.depth_get_column(sort_key.split("."))

    # Cache key intentionally omits `session`/`grid` (see get_profile). For the sorts
    # this path serves — the correlated aggregates with *no* role/division/search
    # filter — the ordering depends only on (workspace, sort, direction); `grid` only
    # feeds the division predicates, which are absent here. Short TTL + invalidation
    # on a tournament.standings invalidation (services.cache_resources) bound staleness.
    @cache(
        ttl=config.settings.users_cache_ttl,
        key="backend:user_overview_order:{workspace_id}:{sort_key}:{descending}",
    )
    async def _overview_ordered_ids(
        self,
        session: AsyncSession,
        *,
        workspace_id: int | None,
        sort_key: str,
        descending: bool,
        grid: DivisionGrid,
    ) -> tuple[list[int], int]:
        """Full workspace-scoped user-id order + total for an expensive overview sort.

        The correlated aggregate in ORDER BY is evaluated over the whole population,
        so this whole-population sort is cached per (workspace, sort, direction)
        instead of being recomputed for every page and every concurrent viewer.
        """
        id_query = _apply_workspace_member_filter(sa.select(models.User.id), workspace_id)
        sort_expr = self._overview_sort_expr(sort_key, grid)
        if descending:
            id_query = id_query.order_by(sort_expr.desc(), models.User.id.asc())
        else:
            id_query = id_query.order_by(sort_expr.asc(), models.User.id.asc())
        ids = list((await session.execute(id_query)).scalars().all())
        # EXISTS-scoped User.id is unique — len(ids) is the count query.
        return ids, len(ids)

    async def get_overview_users(
        self,
        session: AsyncSession,
        params: app_schemas.UserOverviewParams,
        grid: DivisionGrid,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[models.User], int]:
        is_desc = params.order == pagination.SortOrder.DESC or params.order == "desc"
        sort_key = params.sort

        # Fast path (H13): an expensive correlated sort with no search/role/division
        # filter has a population-wide ORDER BY that depends only on
        # (workspace, sort, direction). Reuse a short-TTL cached id order and fetch
        # only the page, instead of re-sorting the whole population on every request.
        if (
            sort_key in _EXPENSIVE_OVERVIEW_SORTS
            and not params.query
            and params.role is None
            and params.div_min is None
            and params.div_max is None
        ):
            ordered_ids, total = await self._overview_ordered_ids(
                session,
                workspace_id=workspace_id,
                sort_key=sort_key,
                descending=is_desc,
                grid=grid,
            )
            offset = (params.page - 1) * params.per_page
            page_ids = ordered_ids[offset : offset + params.per_page]
            if not page_ids:
                return [], total
            rows = await session.execute(sa.select(models.User).where(models.User.id.in_(page_ids)))
            by_id = {user.id: user for user in rows.unique().scalars().all()}
            # Preserve the cached ORDER BY sequence (IN (...) is unordered).
            return [by_id[uid] for uid in page_ids if uid in by_id], total

        query = sa.select(models.User)
        total_query = sa.select(sa.func.count(sa.distinct(models.User.id)))

        query = _apply_workspace_member_filter(query, workspace_id)
        total_query = _apply_workspace_member_filter(total_query, workspace_id)

        if params.query:
            query = params.apply_search(query, models.User)
            total_query = params.apply_search(total_query, models.User)

        if params.role is not None or params.div_min is not None or params.div_max is not None:
            query = _apply_overview_role_filters(
                query,
                role=params.role,
                div_min=params.div_min,
                div_max=params.div_max,
                grid=grid,
            )
            total_query = _apply_overview_role_filters(
                total_query,
                role=params.role,
                div_min=params.div_min,
                div_max=params.div_max,
                grid=grid,
            )

        sort_expr = self._overview_sort_expr(sort_key, grid)

        if is_desc:
            query = query.order_by(sort_expr.desc(), models.User.id.asc())
        else:
            query = query.order_by(sort_expr.asc(), models.User.id.asc())

        paged = params.apply_pagination(query.add_columns(sa.func.count().over().label("overview_total")))
        rows = (await session.execute(paged)).unique().all()
        if not rows:
            return [], (await session.execute(total_query)).scalar_one()
        return [row[0] for row in rows], int(rows[0][-1])

    async def get_overview_role_divisions(
        self,
        session: AsyncSession,
        user_ids: list[int],
        workspace_id: int | None = None,
    ) -> dict[int, list[tuple[enums.HeroClass, int, int | None]]]:
        """Return (role, rank, division_grid_version_id) for each user's most recent entry per role.

        Division computation is intentionally deferred to the caller so that each
        player's rank can be normalised through the tournament's own grid version
        rather than a single global grid. When ``workspace_id`` is given, only that
        workspace's tournaments are considered (so the "latest" rank per role is the
        latest *within the workspace*), matching the scoped user list.
        """
        if not user_ids:
            return {}

        latest_roles_select = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Player.role.label("role"),
                models.Player.rank.label("rank"),
                models.Player.tournament_id.label("tournament_id"),
                sa.func.row_number()
                .over(
                    partition_by=[models.WorkspaceMember.player_id, models.Player.role],
                    order_by=[models.Player.tournament_id.desc(), models.Player.id.desc()],
                )
                .label("row_num"),
            )
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(user_ids),
                models.Player.is_substitution.is_(False),
                models.Player.role.isnot(None),
            )
        )
        if workspace_id is not None:
            latest_roles_select = latest_roles_select.join(
                models.Tournament, models.Tournament.id == models.Player.tournament_id
            ).where(models.Tournament.workspace_id == workspace_id)
        latest_roles_subquery = latest_roles_select.subquery()

        query = (
            sa.select(
                latest_roles_subquery.c.user_id,
                latest_roles_subquery.c.role,
                latest_roles_subquery.c.rank,
                models.Tournament.division_grid_version_id,
            )
            .join(models.Tournament, models.Tournament.id == latest_roles_subquery.c.tournament_id)
            .where(latest_roles_subquery.c.row_num == 1)
        )

        result = await session.execute(query)

        payload: dict[int, list[tuple[enums.HeroClass, int, int | None]]] = defaultdict(list)
        for user_id, role, rank, version_id in result.all():
            if role is None:
                continue
            payload[user_id].append((role, rank, version_id))

        role_order = {
            enums.HeroClass.tank: 0,
            enums.HeroClass.damage: 1,
            enums.HeroClass.support: 2,
        }

        for user_id in payload:
            payload[user_id].sort(key=lambda row: role_order.get(row[0], 99))

        return dict(payload)

    async def get_overview_tournaments_count(
        self,
        session: AsyncSession,
        user_ids: list[int],
        workspace_id: int | None = None,
    ) -> dict[int, int]:
        if not user_ids:
            return {}

        query = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                sa.func.count(sa.distinct(models.Team.tournament_id)).label("tournaments_count"),
            )
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(user_ids),
                models.Player.is_substitution.is_(False),
                models.Tournament.is_finished.is_(True),
                models.Tournament.is_league.is_(False),
            )
            .group_by(models.WorkspaceMember.player_id)
        )

        if workspace_id is not None:
            query = query.where(models.Tournament.workspace_id == workspace_id)

        result = await session.execute(query)
        return dict(result.all())

    async def get_overview_achievements_count(
        self,
        session: AsyncSession,
        user_ids: list[int],
        workspace_id: int | None = None,
    ) -> dict[int, int]:
        if not user_ids:
            return {}

        effective_rows = build_effective_achievement_rows_subquery(
            user_ids=user_ids,
            workspace_id=workspace_id,
            name="overview_achievement_count_rows",
        )
        query = sa.select(
            effective_rows.c.user_id,
            sa.func.count(sa.distinct(effective_rows.c.achievement_rule_id)).label("achievements_count"),
        ).group_by(effective_rows.c.user_id)

        result = await session.execute(query)
        return dict(result.all())

    async def get_overview_averages(
        self,
        session: AsyncSession,
        user_ids: list[int],
        workspace_id: int | None = None,
    ) -> dict[int, tuple[float | None, float | None, float | None, float | None]]:
        if not user_ids:
            return {}

        ws_filter = [models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []

        team_overall_subquery = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Player.team_id.label("team_id"),
                sa.func.min(models.Standing.overall_position).label("overall_position"),
            )
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .join(
                models.Standing,
                sa.and_(
                    models.Standing.team_id == models.Player.team_id,
                    models.Standing.tournament_id == models.Player.tournament_id,
                ),
            )
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(user_ids),
                models.Player.is_substitution.is_(False),
                models.Tournament.is_finished.is_(True),
                models.Tournament.is_league.is_(False),
                *ws_filter,
            )
            .group_by(models.WorkspaceMember.player_id, models.Player.team_id)
            .cte("overview_team_overall")
        )

        placement_query = sa.select(
            team_overall_subquery.c.user_id,
            sa.func.avg(team_overall_subquery.c.overall_position).label("avg_placement"),
        ).group_by(team_overall_subquery.c.user_id)

        placement_stage_query = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                sa.func.avg(
                    sa.case((models.Standing.buchholz.isnot(None), models.Standing.position), else_=None)
                ).label("avg_group_placement"),
                sa.func.avg(sa.case((models.Standing.buchholz.is_(None), models.Standing.position), else_=None)).label(
                    "avg_playoff_placement"
                ),
            )
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .join(
                models.Standing,
                sa.and_(
                    models.Standing.team_id == models.Player.team_id,
                    models.Standing.tournament_id == models.Player.tournament_id,
                ),
            )
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(user_ids),
                models.Player.is_substitution.is_(False),
                models.Tournament.is_finished.is_(True),
                models.Tournament.is_league.is_(False),
                *ws_filter,
            )
            .group_by(models.WorkspaceMember.player_id)
        )

        def _closeness_side(team_fk, _won, _lost):
            return (
                sa.select(
                    models.WorkspaceMember.player_id.label("user_id"),
                    models.Encounter.closeness.label("closeness"),
                )
                .select_from(models.Player)
                .join(models.Team, models.Team.id == models.Player.team_id)
                .join(models.Encounter, team_fk == models.Team.id)
                .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
                .where(
                    models.WorkspaceMember.player_id.in_(user_ids),
                    models.Player.is_substitution.is_(False),
                    models.Tournament.is_finished.is_(True),
                    models.Tournament.is_league.is_(False),
                    models.Encounter.closeness.isnot(None),
                    *ws_filter,
                )
            )

        closeness_sides = union_encounter_team_sides(_closeness_side).subquery("overview_closeness_sides")
        closeness_query = sa.select(
            closeness_sides.c.user_id,
            sa.func.avg(closeness_sides.c.closeness).label("avg_closeness"),
        ).group_by(closeness_sides.c.user_id)

        placement_result = await session.execute(placement_query)
        placement_stage_result = await session.execute(placement_stage_query)
        closeness_result = await session.execute(closeness_query)

        payload: dict[int, tuple[float | None, float | None, float | None, float | None]] = dict.fromkeys(
            user_ids, (None, None, None, None)
        )

        for user_id, avg_placement in placement_result.all():
            _, _, _, current_closeness = payload.get(user_id, (None, None, None, None))
            payload[user_id] = (avg_placement, None, None, current_closeness)

        for user_id, avg_group_placement, avg_playoff_placement in placement_stage_result.all():
            avg_placement, _, _, current_closeness = payload.get(user_id, (None, None, None, None))
            payload[user_id] = (avg_placement, avg_playoff_placement, avg_group_placement, current_closeness)

        for user_id, avg_closeness in closeness_result.all():
            avg_placement, avg_playoff_placement, avg_group_placement, _ = payload.get(
                user_id, (None, None, None, None)
            )
            payload[user_id] = (avg_placement, avg_playoff_placement, avg_group_placement, avg_closeness)

        return payload

    async def get_overview_top_heroes(
        self,
        session: AsyncSession,
        user_ids: list[int],
        *,
        limit: int = 5,
        workspace_id: int | None = None,
    ) -> dict[int, list[tuple[models.Hero, float]]]:
        if not user_ids:
            return {}

        playtime_select = (
            sa.select(
                models.MatchStatistics.user_id.label("user_id"),
                models.MatchStatistics.hero_id.label("hero_id"),
                sa.func.sum(models.MatchStatistics.value).label("playtime_seconds"),
                sa.func.row_number()
                .over(
                    partition_by=models.MatchStatistics.user_id,
                    order_by=[
                        sa.func.sum(models.MatchStatistics.value).desc(),
                        models.MatchStatistics.hero_id.asc(),
                    ],
                )
                .label("row_num"),
            )
            .where(
                models.MatchStatistics.user_id.in_(user_ids),
                models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
                models.MatchStatistics.round == 0,
                models.MatchStatistics.hero_id.isnot(None),
                models.MatchStatistics.value > 0,
            )
            .group_by(models.MatchStatistics.user_id, models.MatchStatistics.hero_id)
        )
        if workspace_id is not None:
            # MatchStatistics -> Match -> Encounter -> Tournament (all 1:1 per stat
            # row, so the playtime sum is unchanged) to scope heroes to the workspace.
            playtime_select = (
                playtime_select.join(models.Match, models.Match.id == models.MatchStatistics.match_id)
                .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
                .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
                .where(models.Tournament.workspace_id == workspace_id)
            )
        playtime_subquery = playtime_select.cte("overview_user_hero_playtime")

        query = (
            sa.select(
                playtime_subquery.c.user_id,
                playtime_subquery.c.playtime_seconds,
                models.Hero,
            )
            .join(models.Hero, models.Hero.id == playtime_subquery.c.hero_id)
            .where(playtime_subquery.c.row_num <= limit)
            .order_by(playtime_subquery.c.user_id.asc(), playtime_subquery.c.row_num.asc())
        )

        result = await session.execute(query)

        payload: dict[int, list[tuple[models.Hero, float]]] = defaultdict(list)
        for user_id, playtime_seconds, hero in result.all():
            payload[user_id].append((hero, playtime_seconds))

        return dict(payload)

    async def get_overview_top_hero_metrics(
        self,
        session: AsyncSession,
        top_heroes: dict[int, list[tuple[models.Hero, float]]],
        workspace_id: int | None = None,
    ) -> dict[tuple[int, int], dict[enums.LogStatsName, float]]:
        if not top_heroes:
            return {}

        hero_pairs = [(user_id, hero.id) for user_id, heroes in top_heroes.items() for hero, _ in heroes]
        if not hero_pairs:
            return {}

        hero_playtime_stat = sa.alias(models.MatchStatistics)
        eligible_stats = (
            sa.select(
                models.MatchStatistics.match_id.label("match_id"),
                models.MatchStatistics.user_id.label("user_id"),
                models.MatchStatistics.hero_id.label("hero_id"),
                models.MatchStatistics.name.label("name"),
                models.MatchStatistics.value.label("value"),
            )
            .where(
                models.MatchStatistics.round == 0,
                models.MatchStatistics.hero_id.isnot(None),
                models.MatchStatistics.name.in_(OVERVIEW_HERO_METRICS),
                sa.tuple_(models.MatchStatistics.user_id, models.MatchStatistics.hero_id).in_(hero_pairs),
                sa.exists(
                    sa.select(1)
                    .select_from(hero_playtime_stat)
                    .where(
                        hero_playtime_stat.c.match_id == models.MatchStatistics.match_id,
                        hero_playtime_stat.c.user_id == models.MatchStatistics.user_id,
                        hero_playtime_stat.c.hero_id == models.MatchStatistics.hero_id,
                        hero_playtime_stat.c.name == enums.LogStatsName.HeroTimePlayed,
                        hero_playtime_stat.c.round == 0,
                        hero_playtime_stat.c.value > 60,
                    )
                ),
            )
            .cte("overview_eligible_stats")
        )

        query = (
            sa.select(
                eligible_stats.c.user_id,
                eligible_stats.c.hero_id,
                eligible_stats.c.name,
                (sa.func.sum(eligible_stats.c.value) / sa.func.nullif(sa.func.sum(models.Match.time), 0) * 600).label(
                    "avg_10"
                ),
            )
            .join(models.Match, models.Match.id == eligible_stats.c.match_id)
            .group_by(eligible_stats.c.user_id, eligible_stats.c.hero_id, eligible_stats.c.name)
        )
        if workspace_id is not None:
            # Scope the per-metric aggregation to the workspace's matches
            # (Match -> Encounter -> Tournament, all 1:1) so avg_10 reflects
            # workspace-only performance, consistent with the scoped hero list.
            query = (
                query.join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
                .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
                .where(models.Tournament.workspace_id == workspace_id)
            )

        result = await session.execute(query)

        payload: dict[tuple[int, int], dict[enums.LogStatsName, float]] = defaultdict(dict)
        for user_id, hero_id, stat_name, avg_10 in result.all():
            payload[(user_id, hero_id)][stat_name] = avg_10

        return dict(payload)

    async def get_overview_stats(
        self,
        session: AsyncSession,
        *,
        role: enums.HeroClass | None,
        div_min: int | None,
        div_max: int | None,
        query: str | None,
        grid: DivisionGrid,
        workspace_id: int | None = None,
    ) -> dict[str, typing.Any]:
        """Compute KPI numbers for the users hero header.

        Counts respect the same filter chips as the main overview table:
        role, division range, and search query. The result includes:
          - total_players: distinct users matching the filters
          - with_logs_count / with_logs_pct: how many have at least one parsed match stat row
          - avg_tournaments_per_player / median_tournaments_per_player
          - active_last_30d / active_last_30d_pct: distinct players in tournaments
            whose start_date or end_date falls within the last 30 days
          - tank / damage / support / flex counts (distinct roles per user)
        """
        base_query = sa.select(models.User.id).select_from(models.User)
        base_query = _apply_workspace_member_filter(base_query, workspace_id)

        if query:
            base_query = pagination.apply_search(models.User, base_query, query, ["name"])

        if role is not None or div_min is not None or div_max is not None:
            base_query = _apply_overview_role_filters(
                base_query,
                role=role,
                div_min=div_min,
                div_max=div_max,
                grid=grid,
            )

        # The candidate set stays in SQL. Every sub-aggregate below semi-joins
        # against this CTE instead of the old shape, which pulled every matching
        # user id into Python and re-inlined it as a literal ``IN (...)`` list
        # into four further statements.
        candidates = base_query.distinct().cte("overview_candidates")
        candidate_ids = sa.select(candidates.c.id)

        total_players = int(
            (await session.execute(sa.select(sa.func.count()).select_from(candidates))).scalar_one() or 0
        )

        if not total_players:
            return {
                "total_players": 0,
                "with_logs_count": 0,
                "with_logs_pct": 0.0,
                "avg_tournaments_per_player": 0.0,
                "median_tournaments_per_player": 0.0,
                "active_last_30d": 0,
                "active_last_30d_pct": 0.0,
                "tank_count": 0,
                "damage_count": 0,
                "support_count": 0,
                "flex_count": 0,
            }

        # Scope the KPI sub-aggregates to the workspace so they stay consistent with
        # the workspace-scoped candidate set (total_players).
        ws_filter = [models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []

        # NB: "has any parsed logs" is intentionally NOT workspace-scoped — reaching
        # the workspace from match_statistics requires a Match->Encounter->Tournament
        # join over that (very large) table, which times out for big workspaces. The
        # candidate set is already workspace-scoped, so this counts scoped players who
        # have parsed logs anywhere; the slight cross-workspace leniency is acceptable.
        with_logs_query = sa.select(sa.func.count(sa.distinct(models.MatchStatistics.user_id))).where(
            models.MatchStatistics.user_id.in_(candidate_ids)
        )
        with_logs_count = (await session.execute(with_logs_query)).scalar_one() or 0

        tournaments_query = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                sa.func.count(sa.distinct(models.Team.tournament_id)).label("tournaments_count"),
            )
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(candidate_ids),
                models.Player.is_substitution.is_(False),
                models.Tournament.is_finished.is_(True),
                models.Tournament.is_league.is_(False),
                *ws_filter,
            )
            .group_by(models.WorkspaceMember.player_id)
        )
        tournament_counts = [int(count) for _user_id, count in (await session.execute(tournaments_query)).all()]
        counts_with_zero = tournament_counts + [0] * (total_players - len(tournament_counts))
        avg_tournaments = sum(counts_with_zero) / total_players if total_players else 0.0
        sorted_counts = sorted(counts_with_zero)
        if sorted_counts:
            mid = len(sorted_counts) // 2
            if len(sorted_counts) % 2 == 0:
                median_tournaments = (sorted_counts[mid - 1] + sorted_counts[mid]) / 2
            else:
                median_tournaments = float(sorted_counts[mid])
        else:
            median_tournaments = 0.0

        cutoff = sa.func.now() - sa.text("INTERVAL '30 days'")
        active_query = (
            sa.select(sa.func.count(sa.distinct(models.WorkspaceMember.player_id)))
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(candidate_ids),
                models.Player.is_substitution.is_(False),
                models.Tournament.is_league.is_(False),
                sa.or_(
                    sa.and_(models.Tournament.end_date.isnot(None), models.Tournament.end_date >= cutoff),
                    sa.and_(models.Tournament.start_date.isnot(None), models.Tournament.start_date >= cutoff),
                ),
                *ws_filter,
            )
        )
        active_last_30d = (await session.execute(active_query)).scalar_one() or 0

        roles_query = (
            sa.select(models.WorkspaceMember.player_id.label("user_id"), models.Player.role)
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(candidate_ids),
                models.Player.is_substitution.is_(False),
                models.Player.role.isnot(None),
            )
            .distinct()
        )
        if workspace_id is not None:
            roles_query = roles_query.join(
                models.Tournament, models.Tournament.id == models.Player.tournament_id
            ).where(models.Tournament.workspace_id == workspace_id)
        user_roles: dict[int, set[enums.HeroClass]] = defaultdict(set)
        for user_id, player_role in (await session.execute(roles_query)).all():
            user_roles[user_id].add(player_role)

        tank_count = damage_count = support_count = flex_count = 0
        for roles_set in user_roles.values():
            # "Flex" here means "plays anything", which a player reaches two ways:
            # by having been rostered on more than one role, or by carrying the
            # explicit HeroClass.flex a role-less roster assigns. Before flex
            # existed only the first was possible; an explicitly flex player has a
            # one-element role set and would otherwise land in no bucket at all.
            if len(roles_set) > 1 or enums.HeroClass.flex in roles_set:
                flex_count += 1
            if enums.HeroClass.tank in roles_set:
                tank_count += 1
            if enums.HeroClass.damage in roles_set:
                damage_count += 1
            if enums.HeroClass.support in roles_set:
                support_count += 1

        return {
            "total_players": total_players,
            "with_logs_count": int(with_logs_count),
            "with_logs_pct": round(with_logs_count / total_players * 100, 1) if total_players else 0.0,
            "avg_tournaments_per_player": round(avg_tournaments, 1),
            "median_tournaments_per_player": round(median_tournaments, 1),
            "active_last_30d": int(active_last_30d),
            "active_last_30d_pct": round(active_last_30d / total_players * 100, 1) if total_players else 0.0,
            "tank_count": tank_count,
            "damage_count": damage_count,
            "support_count": support_count,
            "flex_count": flex_count,
        }

    def _classify_letter(self, name: str) -> str:
        """Bucket the first character of a name into A..Z or '#'."""
        if not name:
            return "#"
        first_char = name[0].upper()
        if "A" <= first_char <= "Z":
            return first_char
        return "#"

    async def get_catalog_users(
        self,
        session: AsyncSession,
        *,
        role: enums.HeroClass | None,
        div_min: int | None,
        div_max: int | None,
        query: str | None,
        letter: str | None,
        per_letter: int,
        max_letters: int,
        grid: DivisionGrid,
        workspace_id: int | None = None,
    ) -> tuple[list[tuple[str, list[models.User]]], int, list[str]]:
        """Return (letters_with_users, total_users, available_letters).

        Users are loaded across the full filtered set, grouped by their starting
        letter (or '#' for non-alpha names), then per-letter capped at `per_letter`.
        If `letter` is specified, only that bucket is returned (still capped).
        `available_letters` reports every letter that has at least one matching user
        (used to grey out empty letters in the alphabet index).
        """
        base_query = (
            sa.select(models.User)
            .select_from(models.User)
            .order_by(sa.func.lower(models.User.name).asc(), models.User.id.asc())
        )
        base_query = _apply_workspace_member_filter(base_query, workspace_id)

        if query:
            base_query = pagination.apply_search(models.User, base_query, query, ["name"])

        if role is not None or div_min is not None or div_max is not None:
            base_query = _apply_overview_role_filters(
                base_query,
                role=role,
                div_min=div_min,
                div_max=div_max,
                grid=grid,
            )

        all_users = list((await session.execute(base_query)).unique().scalars().all())

        grouped: dict[str, list[models.User]] = defaultdict(list)
        for user in all_users:
            grouped[self._classify_letter(user.name)].append(user)

        available_letters = sorted(grouped.keys(), key=lambda x: (x != "#", x))

        if letter is not None:
            letter_key = letter.upper() if letter != "#" else "#"
            bucket = grouped.get(letter_key, [])
            letters_with_users = [(letter_key, bucket[:per_letter])] if bucket else []
        else:
            sorted_letters = sorted(grouped.keys(), key=lambda x: (x != "#", x))
            letters_with_users = [(lbl, grouped[lbl][:per_letter]) for lbl in sorted_letters[:max_letters]]

        return letters_with_users, len(all_users), available_letters


overview = UserOverviewQueries()
