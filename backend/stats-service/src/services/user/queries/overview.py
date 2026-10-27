"""Overview / catalog list queries for the ``/users`` grid."""

import datetime
import typing
from collections import Counter, defaultdict

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.core import enums, pagination
from shared.disciplines import DISCIPLINES, discipline, rated_role_codes
from shared.division_grid import DivisionGrid, division_case_expr, ladder_grid
from shared.schemas.role import RoleRef
from shared.services.achievement_effective import build_effective_achievement_rows_subquery
from shared.services.cache_generations import versioned
from shared.services.division_grid.access import (
    canonical_division_expr,
    tournament_effective_version_id_expr,
    tournament_grid_versions,
)
from shared.services.user_cache import TOURNAMENT_DATA
from src.core import config
from src.services.discipline_queries import DisciplineQueries
from src.services.encounter_seats import Seat

from ._scope import (
    _apply_overview_role_filters,
    _apply_workspace_member_filter,
    _compare_player_scope_filters,
    _compare_tournament_scope_exists,
    apply_has_logs_filter,
    player_role_filter,
    user_has_logs,
)

if typing.TYPE_CHECKING:
    from src import schemas as app_schemas

# Overview sorts whose ORDER BY is an aggregate (a correlated scalar subquery; winrate's a
# grouped pass) evaluated over the whole filtered population (not just the page). Cached
# id-order applies to these.
_EXPENSIVE_OVERVIEW_SORTS = frozenset(
    {"tournaments_count", "achievements_count", "avg_placement", "winrate", "best_placement"}
)


class UserOverviewQueries(DisciplineQueries):
    """Population-wide list queries: the users grid, its KPI header and the catalog."""

    def _overview_scope_where(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: RoleRef | None,
        div_min: int | None,
        div_max: int | None,
        tournament_id: int | None,
        grid: DivisionGrid,
        workspace_id: int | None = None,
        extra: typing.Sequence[typing.Any] = (),
    ) -> list[typing.Any]:
        """WHERE list shared by every correlated overview aggregate.

        ``extra`` slots in between the finished/league predicates and the
        optional tournament pin. Every caller joins ``Tournament``, so
        ``workspace_id`` scopes the aggregate to the same workspace as the value
        the row displays.
        """
        where_conditions: list[typing.Any] = [
            *_compare_player_scope_filters(
                models.Player,
                user_id_column,
                discipline=self._discipline,
                role=role,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                grid=grid,
                workspace_id=workspace_id,
            ),
            models.Tournament.is_finished.is_(True),
            models.Tournament.is_league.is_(False),
            *extra,
        ]
        if workspace_id is not None:
            where_conditions.append(models.Tournament.workspace_id == workspace_id)
        if tournament_id is not None:
            where_conditions.append(models.Tournament.id == tournament_id)
        return where_conditions

    def _overview_standing_select(self, *columns: typing.Any) -> sa.Select:
        """Player -> Team -> Tournament -> Standing chain (placement aggregates) of this game's tournaments."""
        return (
            sa.select(*columns)
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
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
        build_columns: typing.Callable[[Seat], typing.Sequence[typing.Any]],
        *where_conditions: typing.Any,
    ) -> sa.Select:
        """Player -> Team -> seat -> Encounter -> Tournament, one row per encounter the team played.

        ``build_columns(seat)`` names the selected columns; wrap the result in
        AVG/SUM yourself. Two-seat encounters only: the maps columns read the
        series score.
        """
        seat = Seat()
        query = (
            sa.select(*build_columns(seat))
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
        )
        return (
            seat.join(query, models.Team.id)
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
            .where(*where_conditions)
        )

    def _overview_tournaments_count_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: RoleRef | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
        workspace_id: int | None = None,
    ) -> sa.ScalarSelect:
        where_conditions = self._overview_scope_where(
            user_id_column,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
            workspace_id=workspace_id,
        )
        return (
            sa.select(sa.func.count(sa.distinct(models.Team.tournament_id)))
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
            .where(*where_conditions)
            .scalar_subquery()
        )

    def _overview_achievements_count_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: RoleRef | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
        workspace_id: int | None = None,
    ) -> sa.ScalarSelect:
        # The workspace and game filters live inside the effective-rows subquery, the same
        # way the displayed per-page count builds it: only this game's rules count.
        effective_rows = build_effective_achievement_rows_subquery(
            user_ids=None,
            workspace_id=workspace_id,
            discipline=self._discipline,
            name="overview_effective_achievement_rows",
        )
        query = sa.select(sa.func.count(sa.distinct(effective_rows.c.achievement_rule_id))).where(
            effective_rows.c.user_id == user_id_column
        )

        if role is None and div_min is None and div_max is None and tournament_id is None:
            return query.scalar_subquery()

        achievement_match = self._matches.alias()
        achievement_encounter = aliased(models.Encounter)
        tournament_scope = _compare_tournament_scope_exists(
            user_id_column,
            effective_rows.c.tournament_id,
            discipline=self.discipline,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
            workspace_id=workspace_id,
        )
        match_scope = sa.exists(
            sa.select(1)
            .select_from(achievement_match)
            .join(achievement_encounter, achievement_encounter.id == achievement_match.c.encounter_id)
            .where(
                achievement_match.c.id == effective_rows.c.match_id,
                _compare_tournament_scope_exists(
                    user_id_column,
                    achievement_encounter.tournament_id,
                    discipline=self.discipline,
                    role=role,
                    div_min=div_min,
                    div_max=div_max,
                    tournament_id=tournament_id,
                    grid=grid,
                    workspace_id=workspace_id,
                ),
            )
        )

        return query.where(sa.or_(tournament_scope, match_scope)).scalar_subquery()

    def _overview_avg_placement_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: RoleRef | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
        workspace_id: int | None = None,
    ) -> sa.ScalarSelect:
        where_conditions = self._overview_scope_where(
            user_id_column,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
            workspace_id=workspace_id,
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

    def _overview_best_placement_expr(
        self,
        user_id_column: sa.ColumnElement[typing.Any],
        *,
        role: RoleRef | None = None,
        div_min: int | None = None,
        div_max: int | None = None,
        tournament_id: int | None = None,
        grid: DivisionGrid,
        workspace_id: int | None = None,
    ) -> sa.ScalarSelect:
        """Best (lowest, positive) overall position — NULL when never placed."""
        where_conditions = self._overview_scope_where(
            user_id_column,
            role=role,
            div_min=div_min,
            div_max=div_max,
            tournament_id=tournament_id,
            grid=grid,
            workspace_id=workspace_id,
            extra=(models.Standing.overall_position > 0,),
        )
        return (
            self._overview_standing_select(sa.func.min(models.Standing.overall_position))
            .where(*where_conditions)
            .scalar_subquery()
        )

    def _overview_winrate_sample(self, *, workspace_id: int | None) -> sa.Subquery:
        """Per user: map winrate over the scoped two-seat encounters (NULL without maps) and how many of them have a
        result (``encounters``, the winrate's sample size) -- the winrate sort's keys, for every user at once.

        Each seat's maps are computed once (``MATERIALIZED``) and only then fanned out to its roster: as two
        correlated subqueries per user, every rostered player re-ran the seat's maps subqueries twice, so the cached
        whole-population order took ~1.5 s. Same scope as :meth:`_overview_scope_where` with no role, division or
        tournament filter.
        """
        seat = Seat(name="overview_winrate_seat")
        seat_maps = (
            seat.join(
                sa.select(
                    models.Team.id.label("team_id"),
                    models.Encounter.id.label("encounter_id"),
                    seat.maps_won.label("won"),
                    seat.maps_lost.label("lost"),
                ).select_from(models.Team),
                models.Team.id,
            )
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(
                *self.discipline_filter(models.Tournament.discipline),
                models.Tournament.is_finished.is_(True),
                models.Tournament.is_league.is_(False),
                *([models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []),
            )
            .cte("overview_winrate_seat_maps")
            .prefix_with("MATERIALIZED")
        )
        sides = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                seat_maps.c.encounter_id,
                seat_maps.c.won,
                seat_maps.c.lost,
            )
            .select_from(models.Player)
            .join(seat_maps, seat_maps.c.team_id == models.Player.team_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.Player.is_substitution.is_(False),
                # The roster entry's own tournament too, as ``_compare_player_scope_filters`` has it.
                *[models.Player.tournament.has(cond) for cond in self.discipline_filter(models.Tournament.discipline)],
            )
            .subquery("overview_winrate_sides")
        )
        maps = sides.c.won + sides.c.lost
        return (
            sa.select(
                sides.c.user_id,
                sa.func.count(sa.distinct(sa.case((maps > 0, sides.c.encounter_id)))).label("encounters"),
                (sa.func.sum(sides.c.won) / sa.func.nullif(sa.func.sum(maps), 0).cast(sa.Float)).label("winrate"),
            )
            .group_by(sides.c.user_id)
            .subquery("overview_winrate_sample")
        )

    def _overview_order_by(
        self,
        query: sa.Select,
        sort_key: str,
        *,
        descending: bool,
        grid: DivisionGrid,
        workspace_id: int | None,
        min_encounters: int,
    ) -> sa.Select:
        """``query`` (selecting from ``User``) ordered by an overview sort, workspace-scoped like the displayed values.

        ``models.User.id`` is always the final tiebreaker so paging is stable.
        """

        def _directed(expr: sa.ColumnElement[typing.Any]) -> sa.ColumnElement[typing.Any]:
            # NULL (never placed / no maps) always sorts last, in both directions.
            return expr.desc().nullslast() if descending else expr.asc().nullslast()

        if sort_key == "tournaments_count":
            expr = self._overview_tournaments_count_expr(models.User.id, grid=grid, workspace_id=workspace_id)
        elif sort_key == "achievements_count":
            expr = self._overview_achievements_count_expr(models.User.id, grid=grid, workspace_id=workspace_id)
        elif sort_key == "avg_placement":
            expr = self._overview_avg_placement_expr(models.User.id, grid=grid, workspace_id=workspace_id)
        elif sort_key == "best_placement":
            expr = self._overview_best_placement_expr(models.User.id, grid=grid, workspace_id=workspace_id)
        elif sort_key == "winrate":
            sample = self._overview_winrate_sample(workspace_id=workspace_id)
            # Thin samples go after everybody else whichever way the column is
            # sorted: a 100% winrate off two maps is not the top of the table.
            return query.outerjoin(sample, sample.c.user_id == models.User.id).order_by(
                sa.case((sa.func.coalesce(sample.c.encounters, 0) >= min_encounters, 0), else_=1).asc(),
                _directed(sample.c.winrate),
                models.User.id.asc(),
            )
        else:
            expr = models.User.depth_get_column(sort_key.split("."))

        return query.order_by(_directed(expr), models.User.id.asc())

    # Cache key intentionally omits `session`/`grid` (see get_profile). For the sorts
    # this path serves — the correlated aggregates with *no* role/division/logs/search
    # filter — the ordering depends only on (game, workspace, sort, direction,
    # min_encounters); `grid` only feeds the division predicates, which are absent here.
    # Short TTL + a miss after any tournament write that moves a user aggregate
    # (``user_cache.TOURNAMENT_DATA``) bound staleness.
    @versioned(
        generations=TOURNAMENT_DATA,
        ttl=config.settings.users_cache_ttl,
        key="backend:user_overview_order:{self._discipline}:{workspace_id}:{sort_key}:{descending}:{min_encounters}",
    )
    async def _overview_ordered_ids(
        self,
        session: AsyncSession,
        *,
        workspace_id: int | None,
        sort_key: str,
        descending: bool,
        min_encounters: int,
        grid: DivisionGrid,
    ) -> tuple[list[int], int]:
        """Full workspace-scoped user-id order + total for an expensive overview sort.

        The correlated aggregate in ORDER BY is evaluated over the whole population,
        so this whole-population sort is cached per (workspace, sort, direction,
        min_encounters) instead of being recomputed for every page and every
        concurrent viewer.
        """
        id_query = self._overview_order_by(
            _apply_workspace_member_filter(sa.select(models.User.id), workspace_id),
            sort_key,
            descending=descending,
            grid=grid,
            workspace_id=workspace_id,
            min_encounters=min_encounters,
        )
        ids = list((await session.execute(id_query)).scalars().all())
        # EXISTS-scoped User.id is unique — len(ids) is the count query.
        return ids, len(ids)

    async def get_overview_users(
        self,
        session: AsyncSession,
        params: app_schemas.UserOverviewParams,
        grid: DivisionGrid | None,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[models.User], int]:
        is_desc = params.order == pagination.SortOrder.DESC or params.order == "desc"
        sort_key = params.sort

        # Fast path: an expensive correlated sort with no search/role/division/
        # logs filter has a population-wide ORDER BY that depends only on
        # (workspace, sort, direction, min_encounters). Reuse a short-TTL cached id
        # order and fetch only the page, instead of re-sorting the whole population
        # on every request.
        if (
            sort_key in _EXPENSIVE_OVERVIEW_SORTS
            and not params.query
            and params.role is None
            and not params.has_role_filter
            and not params.divisions
            and not params.has_logs
        ):
            ordered_ids, total = await self._overview_ordered_ids(
                session,
                workspace_id=workspace_id,
                sort_key=sort_key,
                descending=is_desc,
                min_encounters=params.min_encounters,
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

        if params.has_logs:
            query = apply_has_logs_filter(query, discipline=self._discipline)
            total_query = apply_has_logs_filter(total_query, discipline=self._discipline)

        if params.has_role_filter or params.role is not None or params.divisions:
            query = _apply_overview_role_filters(
                query,
                role=params.role,
                has_role_filter=params.has_role_filter,
                divisions=params.divisions,
                grid=grid,
                workspace_id=workspace_id,
                discipline=self.discipline,
            )
            total_query = _apply_overview_role_filters(
                total_query,
                role=params.role,
                has_role_filter=params.has_role_filter,
                divisions=params.divisions,
                grid=grid,
                workspace_id=workspace_id,
                discipline=self.discipline,
            )

        query = self._overview_order_by(
            query,
            sort_key,
            descending=is_desc,
            grid=grid,
            workspace_id=workspace_id,
            min_encounters=params.min_encounters,
        )

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
    ) -> dict[int, list[tuple[RoleRef, int | None, int | None]]]:
        """Return (role, rank, division source) for each user's most recent ranked entry per role.

        Scoped (``workspace_id`` given): only that workspace's tournaments are
        considered (so the "latest" rank per role is the latest *within the
        workspace*, matching the scoped user list), and the third value is the
        tournament's *effective* grid version id (own pin, else its workspace
        default, else the system default; NULL only when no grid exists at all),
        which the caller normalizes onto the workspace grid.

        All-workspaces: the third value already is the canonical division on the
        game's native ladder (``None`` without one) — the same SQL the division
        filter matches, so a badge and the filter never disagree.

        A role never ranked keeps its newest entry with a NULL rank: no division.
        """
        # A role and its division are facts of one game: the cross-game read has none.
        if not user_ids or self._discipline is None:
            return {}

        latest_roles_select = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Player.role.label("role"),
                models.Tournament.discipline,
                models.Player.rank.label("rank"),
                models.Player.tournament_id.label("tournament_id"),
                sa.func.row_number()
                .over(
                    partition_by=[models.WorkspaceMember.player_id, models.Tournament.discipline, models.Player.role],
                    # The newest ranked event first, by start date (undated last), not id: ids follow creation, not
                    # play, so across workspaces an older event can carry the higher id.
                    order_by=[
                        models.Player.rank.is_(None),
                        models.Tournament.start_date.desc().nulls_last(),
                        models.Player.tournament_id.desc(),
                        models.Player.id.desc(),
                    ],
                )
                .label("row_num"),
            )
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
            .where(
                models.WorkspaceMember.player_id.in_(user_ids),
                models.Player.is_substitution.is_(False),
                models.Player.role.isnot(None),
            )
        )
        if workspace_id is not None:
            latest_roles_select = latest_roles_select.where(models.Tournament.workspace_id == workspace_id)
        latest_roles_subquery = latest_roles_select.subquery()

        columns = (
            latest_roles_subquery.c.user_id,
            latest_roles_subquery.c.role,
            latest_roles_subquery.c.discipline,
            latest_roles_subquery.c.rank,
        )
        if workspace_id is not None:
            query = sa.select(*columns, tournament_effective_version_id_expr(latest_roles_subquery.c.tournament_id))
        elif (ladder := ladder_grid(self.discipline)) is not None:
            versions = tournament_grid_versions(self.discipline)
            query = sa.select(
                *columns, canonical_division_expr(latest_roles_subquery.c.rank, versions.c.version_id, ladder)
            ).join(versions, versions.c.tournament_id == latest_roles_subquery.c.tournament_id)
        else:
            query = sa.select(*columns, sa.null())
        query = query.where(latest_roles_subquery.c.row_num == 1)

        result = await session.execute(query)

        payload: dict[int, list[tuple[RoleRef, int | None, int | None]]] = defaultdict(list)
        for user_id, role, discipline_code, rank, division_source in result.all():
            if role is None:
                continue
            # The role, never the latest row's sub-role: a sub-role is its parent role's (the partition above).
            payload[user_id].append(
                (RoleRef.of(discipline(discipline_code).rated_dimension.code, role), rank, division_source)
            )

        # The game's rated roles in declaration order; a role it does not declare sorts last.
        role_order = {code: index for index, code in enumerate(rated_role_codes(self.discipline))}

        for user_id in payload:
            payload[user_id].sort(key=lambda row: role_order.get(row[0].parent or row[0].role, len(role_order)))

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
            .where(*self.discipline_filter(models.Tournament.discipline))
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
            discipline=self._discipline,
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
    ) -> dict[int, tuple[float | None, float | None, float | None, float | None, int | None]]:
        if not user_ids:
            return {}

        ws_filter = [models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []

        team_overall_subquery = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Player.team_id.label("team_id"),
                sa.func.min(models.Standing.overall_position).label("overall_position"),
                # Best placement ignores 0 ("no placement"), like resolve_team_placement.
                sa.func.min(sa.case((models.Standing.overall_position > 0, models.Standing.overall_position))).label(
                    "positive_overall_position"
                ),
            )
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
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
            sa.func.min(team_overall_subquery.c.positive_overall_position).label("best_placement"),
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
            .where(*self.discipline_filter(models.Tournament.discipline))
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

        closeness_seat = Seat(name="closeness_seat")
        closeness_sides = (
            closeness_seat.join(
                sa.select(
                    models.WorkspaceMember.player_id.label("user_id"),
                    models.Encounter.closeness.label("closeness"),
                )
                .select_from(models.Player)
                .join(models.Team, models.Team.id == models.Player.team_id),
                models.Team.id,
            )
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(user_ids),
                models.Player.is_substitution.is_(False),
                models.Tournament.is_finished.is_(True),
                models.Tournament.is_league.is_(False),
                models.Encounter.closeness.isnot(None),
                *ws_filter,
            )
        ).subquery("overview_closeness_sides")
        closeness_query = sa.select(
            closeness_sides.c.user_id,
            sa.func.avg(closeness_sides.c.closeness).label("avg_closeness"),
        ).group_by(closeness_sides.c.user_id)

        placement_result = await session.execute(placement_query)
        placement_stage_result = await session.execute(placement_stage_query)
        closeness_result = await session.execute(closeness_query)

        placements = {
            user_id: (avg_placement, best_placement)
            for user_id, avg_placement, best_placement in placement_result.all()
        }
        stages = {
            user_id: (avg_playoff_placement, avg_group_placement)
            for user_id, avg_group_placement, avg_playoff_placement in placement_stage_result.all()
        }
        closeness_by_user = dict(closeness_result.all())

        return {
            user_id: (
                placements.get(user_id, (None, None))[0],
                *stages.get(user_id, (None, None)),
                closeness_by_user.get(user_id),
                placements.get(user_id, (None, None))[1],
            )
            for user_id in user_ids
        }

    async def get_overview_top_heroes(
        self,
        session: AsyncSession,
        user_ids: list[int],
        *,
        limit: int = 5,
        workspace_id: int | None = None,
    ) -> dict[int, list[tuple[models.CatalogEntity, float]]]:
        # Characters are one game's catalog: the cross-game read lists none.
        if not user_ids or self._discipline is None:
            return {}
        playtime_sum = sa.func.sum(
            aggregate_order_by(
                self._facts.c.value,
                self._facts.c.match_id,
                self._facts.c.workspace_member_id,
            )
        )

        playtime_select = (
            sa.select(
                self._facts.c.player_id.label("user_id"),
                self._facts.c.entity_id.label("hero_id"),
                playtime_sum.label("playtime_seconds"),
                sa.func.row_number()
                .over(
                    partition_by=self._facts.c.player_id,
                    order_by=[
                        playtime_sum.desc(),
                        self._facts.c.entity_id.asc(),
                    ],
                )
                .label("row_num"),
            )
            .where(
                self._facts.c.player_id.in_(user_ids),
                self._facts.c.stat_code == enums.LogStatsName.HeroTimePlayed,
                self._facts.c.segment == 0,
                self._facts.c.entity_id.isnot(None),
                self._facts.c.value > 0,
            )
            .group_by(self._facts.c.player_id, self._facts.c.entity_id)
        )
        if workspace_id is not None:
            playtime_select = playtime_select.where(self._facts.c.workspace_id == workspace_id)
        playtime_subquery = playtime_select.cte("overview_user_hero_playtime")

        query = (
            sa.select(
                playtime_subquery.c.user_id,
                playtime_subquery.c.playtime_seconds,
                models.CatalogEntity,
            )
            .join(models.CatalogEntity, models.CatalogEntity.id == playtime_subquery.c.hero_id)
            .where(
                playtime_subquery.c.row_num <= limit,
                models.CatalogEntity.kind == "character",
                models.CatalogEntity.discipline == self.discipline,
            )
            .order_by(playtime_subquery.c.user_id.asc(), playtime_subquery.c.row_num.asc())
        )

        result = await session.execute(query)

        payload: dict[int, list[tuple[models.CatalogEntity, float]]] = defaultdict(list)
        for user_id, playtime_seconds, hero in result.all():
            payload[user_id].append((hero, playtime_seconds))

        return dict(payload)

    async def get_overview_map_records(
        self,
        session: AsyncSession,
        user_ids: list[int],
        workspace_id: int | None = None,
    ) -> dict[int, tuple[int, int, int]]:
        """``(maps_won, maps_lost, encounters_played)`` per user for the page.

        Same scope as the other overview aggregates (not substitution, finished
        non-league tournaments, optional workspace), read through the team's seat
        in each two-seat encounter. "Played" is an encounter with a result (non-zero
        score sum); the DISTINCT stops a user rostered twice on one
        team from counting that encounter's maps twice.
        """
        if not user_ids:
            return {}

        ws_filter = [models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []

        seat = Seat(name="record_seat")
        sides = (
            seat.join(
                sa.select(
                    models.WorkspaceMember.player_id.label("user_id"),
                    models.Encounter.id.label("encounter_id"),
                    seat.maps_won.label("won"),
                    seat.maps_lost.label("lost"),
                )
                .select_from(models.Player)
                .join(models.Team, models.Team.id == models.Player.team_id),
                models.Team.id,
            )
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(user_ids),
                models.Player.is_substitution.is_(False),
                models.Tournament.is_finished.is_(True),
                models.Tournament.is_league.is_(False),
                *ws_filter,
            )
            .distinct()
        ).subquery("overview_map_record_sides")
        query = sa.select(
            sides.c.user_id,
            sa.func.coalesce(sa.func.sum(sides.c.won), 0),
            sa.func.coalesce(sa.func.sum(sides.c.lost), 0),
            sa.func.count(sa.distinct(sa.case(((sides.c.won + sides.c.lost) > 0, sides.c.encounter_id)))),
        ).group_by(sides.c.user_id)

        return {
            user_id: (int(won), int(lost), int(played))
            for user_id, won, lost, played in (await session.execute(query)).all()
        }

    async def get_overview_last_active(
        self,
        session: AsyncSession,
        user_ids: list[int],
        workspace_id: int | None = None,
    ) -> dict[int, datetime.datetime | None]:
        """Latest tournament date per user: ``MAX(COALESCE(end_date, start_date))``.

        Non-league and optionally workspace-scoped, exactly like the
        ``active_last_30d`` KPI — the row's "last active" has to agree with it,
        so an unfinished tournament counts: being in one right now is activity.
        """
        if not user_ids:
            return {}

        ws_filter = [models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []
        query = (
            sa.select(
                models.WorkspaceMember.player_id,
                sa.func.max(sa.func.coalesce(models.Tournament.end_date, models.Tournament.start_date)),
            )
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(*self.discipline_filter(models.Tournament.discipline))
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                models.WorkspaceMember.player_id.in_(user_ids),
                models.Player.is_substitution.is_(False),
                models.Tournament.is_league.is_(False),
                *ws_filter,
            )
            .group_by(models.WorkspaceMember.player_id)
        )
        return dict((await session.execute(query)).all())

    async def get_overview_disciplines(
        self,
        session: AsyncSession,
        user_ids: list[int],
        workspace_id: int | None = None,
    ) -> dict[int, list[str]]:
        """The games each user played (any roster seat, substitutes excluded), in installed order.

        Independent of the game this instance is bound to: a row lists every game it played in both modes.
        """
        if not user_ids:
            return {}
        query = (
            sa.select(models.WorkspaceMember.player_id, models.Tournament.discipline)
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(
                models.WorkspaceMember.player_id.in_(user_ids),
                models.Player.is_substitution.is_(False),
            )
            .distinct()
        )
        if workspace_id is not None:
            query = query.where(models.Tournament.workspace_id == workspace_id)
        installed = {code: index for index, code in enumerate(DISCIPLINES)}
        played: dict[int, list[str]] = defaultdict(list)
        for user_id, code in (await session.execute(query)).all():
            played[user_id].append(code)
        return {
            user_id: sorted(codes, key=lambda code: installed.get(code, len(installed)))
            for user_id, codes in played.items()
        }

    async def get_overview_stats(
        self,
        session: AsyncSession,
        *,
        role: RoleRef | None,
        has_role_filter: bool = False,
        divisions: typing.Sequence[int],
        has_logs: bool,
        query: str | None,
        grid: DivisionGrid | None,
        workspace_id: int | None = None,
    ) -> dict[str, typing.Any]:
        """Compute KPI numbers for the users hero header.

        Counts respect the same filter chips as the main overview table:
        role, divisions, logs and search query. The result includes:
          - total_players: distinct users matching the filters
          - with_logs_count / with_logs_pct: how many have at least one parsed match stat row
          - avg_tournaments_per_player / median_tournaments_per_player
          - active_last_30d / active_last_30d_pct: distinct players in tournaments
            whose start_date or end_date falls within the last 30 days
          - role_counts: distinct players per top-level rated role code of the game
          - flex_declared_count: what the Flex chip itself selects
          - division_counts: per-division chip counts, ignoring the division chips
        """
        base_query = sa.select(models.User.id).select_from(models.User)
        base_query = _apply_workspace_member_filter(base_query, workspace_id)

        if query:
            base_query = pagination.apply_search(models.User, base_query, query, ["name"])

        if has_logs:
            base_query = apply_has_logs_filter(base_query, discipline=self._discipline)

        if has_role_filter or role is not None:
            base_query = _apply_overview_role_filters(
                base_query,
                role=role,
                has_role_filter=has_role_filter,
                grid=grid,
                workspace_id=workspace_id,
                discipline=self.discipline,
            )

        # The candidate set stays in SQL: every sub-aggregate below semi-joins
        # against this CTE rather than an inlined ``IN (...)`` id list.
        #
        # Two sets: the division chip counts are computed *without* the division
        # chips, everything else with them.
        division_candidates = base_query.distinct().cte("overview_division_candidates")

        if divisions:
            base_query = _apply_overview_role_filters(
                base_query,
                role=role,
                has_role_filter=has_role_filter,
                divisions=divisions,
                grid=grid,
                workspace_id=workspace_id,
                discipline=self.discipline,
            )

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
                "role_counts": {},
                "flex_count": 0,
                "flex_declared_count": 0,
                "division_counts": [],
            }

        # Scope the KPI sub-aggregates to the workspace so they stay consistent with
        # the workspace-scoped candidate set (total_players).
        ws_filter = [models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []

        # has-logs counts a candidate's logs from any workspace; the statistic
        # aggregates apply their own workspace filters.
        with_logs_query = (
            sa.select(sa.func.count())
            .select_from(candidates)
            .where(user_has_logs(candidates.c.id, discipline=self._discipline))
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
            .where(*self.discipline_filter(models.Tournament.discipline))
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
            .where(*self.discipline_filter(models.Tournament.discipline))
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

        role_counts: Counter[str] = Counter()
        flex_count = flex_declared_count = 0
        division_counts: list[dict[str, int]] = []
        # Roles and divisions are one game's facets: the cross-game read reports none.
        if self._discipline is not None:
            roles_query = (
                sa.select(models.WorkspaceMember.player_id.label("user_id"), models.Player.role)
                .select_from(models.Player)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
                .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
                .where(
                    models.WorkspaceMember.player_id.in_(candidate_ids),
                    models.Player.is_substitution.is_(False),
                    models.Tournament.discipline == self.discipline,
                    *ws_filter,
                )
                .distinct()
            )
            user_roles: dict[int, set[str | None]] = defaultdict(set)
            for user_id, player_role in (await session.execute(roles_query)).all():
                user_roles[user_id].add(player_role)

            for roles_set in user_roles.values():
                # An open slot has no assignment; multi-role players also count as flex.
                if len(roles_set) > 1 or None in roles_set:
                    flex_count += 1
                if None in roles_set:
                    flex_declared_count += 1
                role_counts.update(code for code in roles_set if code is not None)

            # Per-division chip counts, over the candidate set *before* the division
            # chips were applied: picking division 5 must not zero every other chip.
            # The all-workspaces read counts canonical ladder numbers (what its filter
            # matches); a game without a native ladder has none to count.
            # ponytail: there each player row probes ``division_grid_tier`` for its
            # canonical number; add a materialized player-division view if the stats
            # call shows up in the slow log.
            division_expr: sa.ColumnElement[typing.Any] | None = None
            division_from: sa.FromClause = sa.join(
                models.Player,
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            if workspace_id is not None:
                division_expr = division_case_expr(models.Player.rank, grid)
            elif (ladder := ladder_grid(self.discipline)) is not None:
                versions = tournament_grid_versions(self.discipline)
                division_expr = canonical_division_expr(models.Player.rank, versions.c.version_id, ladder)
                division_from = division_from.join(versions, versions.c.tournament_id == models.Player.tournament_id)
            if division_expr is not None:
                division_counts_query = (
                    sa.select(
                        division_expr.label("division"), sa.func.count(sa.distinct(models.WorkspaceMember.player_id))
                    )
                    .select_from(division_from)
                    .where(
                        models.WorkspaceMember.player_id.in_(sa.select(division_candidates.c.id)),
                        models.Player.is_substitution.is_(False),
                        *([player_role_filter(models.Player, role)] if has_role_filter or role is not None else []),
                    )
                    .group_by(division_expr)
                    .order_by(division_expr)
                )
                division_counts = [
                    {"division": int(division), "count": int(count)}
                    for division, count in (await session.execute(division_counts_query)).all()
                    if division is not None
                ]

        return {
            "total_players": total_players,
            "with_logs_count": int(with_logs_count),
            "with_logs_pct": round(with_logs_count / total_players * 100, 1) if total_players else 0.0,
            "avg_tournaments_per_player": round(avg_tournaments, 1),
            "median_tournaments_per_player": round(median_tournaments, 1),
            "active_last_30d": int(active_last_30d),
            "active_last_30d_pct": round(active_last_30d / total_players * 100, 1) if total_players else 0.0,
            "role_counts": dict(role_counts),
            "flex_count": flex_count,
            "flex_declared_count": flex_declared_count,
            "division_counts": division_counts,
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
        role: RoleRef | None,
        has_role_filter: bool = False,
        divisions: typing.Sequence[int],
        has_logs: bool,
        query: str | None,
        letter: str | None,
        per_letter: int,
        max_letters: int,
        grid: DivisionGrid | None,
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

        if has_logs:
            base_query = apply_has_logs_filter(base_query, discipline=self._discipline)

        if has_role_filter or role is not None or divisions:
            base_query = _apply_overview_role_filters(
                base_query,
                role=role,
                has_role_filter=has_role_filter,
                divisions=divisions,
                grid=grid,
                workspace_id=workspace_id,
                discipline=self.discipline,
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
