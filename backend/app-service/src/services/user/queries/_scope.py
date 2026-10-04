"""Shared SQL scope predicates and load-option helpers for the user queries.

Module-level on purpose: these are pure builders with no state, reused by
:mod:`.overview`, :mod:`.compare`, :mod:`.profile` and :mod:`.encounters`.
"""

import typing

import sqlalchemy as sa
from sqlalchemy.orm import aliased, joinedload, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared.division_grid import DivisionGrid, division_filter_predicates
from shared.services.division_grid.access import effective_division_filter_predicates
from src import models
from src.core import enums, utils

home_score_case = sa.case(
    (models.Encounter.home_team_id == models.Team.id, models.Encounter.home_score),
    else_=models.Encounter.away_score,
)


away_score_case = sa.case(
    (models.Encounter.home_team_id == models.Team.id, models.Encounter.away_score),
    else_=models.Encounter.home_score,
)


# Equality-join sides. `home_team_id = team.id OR away_team_id = team.id` cannot
# use either FK index and is what timed compare out (OWT-TOURNAMENTS-21T).
ENCOUNTER_TEAM_SIDES: tuple[
    tuple[sa.ColumnElement[typing.Any], sa.ColumnElement[typing.Any], sa.ColumnElement[typing.Any]],
    tuple[sa.ColumnElement[typing.Any], sa.ColumnElement[typing.Any], sa.ColumnElement[typing.Any]],
] = (
    (models.Encounter.home_team_id, models.Encounter.home_score, models.Encounter.away_score),
    (models.Encounter.away_team_id, models.Encounter.away_score, models.Encounter.home_score),
)


def union_encounter_team_sides(
    build_side: typing.Callable[[typing.Any, typing.Any, typing.Any], sa.Select],
) -> sa.CompoundSelect:
    """``UNION ALL`` of ``build_side(team_fk, maps_won, maps_lost)`` per side."""
    home, away = ENCOUNTER_TEAM_SIDES
    return build_side(*home).union_all(build_side(*away))


def team_has_played_encounter(team_id_column: typing.Any = models.Team.id) -> sa.ColumnElement[bool]:
    """Indexable EXISTS: the team appeared as home or as away."""
    return sa.or_(
        sa.exists(sa.select(1).select_from(models.Encounter).where(models.Encounter.home_team_id == team_id_column)),
        sa.exists(sa.select(1).select_from(models.Encounter).where(models.Encounter.away_team_id == team_id_column)),
    )


def _team_load_options(entities: list[str]) -> list[_AbstractLoad]:
    """Load options for selecting Team with optional related entities.

    Replaces the dependency on services/team — kept local because the only
    consumer of this function in app-service is get_teams() below, which
    passes entities=["tournament", "placement"].
    """
    opts: list[_AbstractLoad] = []
    if "tournament" in entities:
        opts.append(joinedload(models.Team.tournament))
    if "placement" in entities:
        opts.append(selectinload(models.Team.standings))
    return opts


def user_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """SQLAlchemy load options for the related entities named in ``in_entities``.

    ``child`` is an existing relationship/join entity to chain the options onto
    instead of loading straight off ``User``.
    """
    entities = []
    # Unified identity source consumed by ``UserService.to_read``. Loaded whenever any
    # identity entity token is requested (legacy ``battle_tag``/``discord``/
    # ``twitch`` tokens are still accepted for caller/API compatibility).
    if any(name in in_entities for name in ("social_accounts", "battle_tag", "discord", "twitch")):
        # Eager-load each account's visibility rows alongside it so ``to_read`` can
        # compute ``visible_global`` and (on public reads) drop hidden accounts
        # without a lazy load outside the async greenlet.
        social_load = utils.join_entity(child, models.User.social_accounts)
        entities.append(social_load.selectinload(models.SocialAccount.visibilities))
    return entities


def _hero_direction_score(value_column: sa.ColumnElement[typing.Any], name_column: sa.ColumnElement[typing.Any]):
    ascending_stats = [stat for stat, direction in enums.LOG_STATS_DEFAULT_DIRECTION.items() if direction == "asc"]
    direction_multiplier = sa.case(
        (name_column.in_(ascending_stats), -1.0),
        else_=1.0,
    )
    return value_column * direction_multiplier


def _build_eligible_hero_stats_cte(
    *,
    user_id: int | None,
    stats: list[enums.LogStatsName] | None,
    cte_name: str,
    tournament_id: int | None = None,
    workspace_id: int | None = None,
) -> sa.CTE:
    # (match, user, hero) combos that actually played the hero (HeroTimePlayed
    # > 60s). Expressed as a DISTINCT semi-join CTE rather than a correlated
    # EXISTS so the planner joins it once (backed by ix_match_statistics_playtime_r0)
    # instead of re-probing matches.statistics per candidate row. DISTINCT keeps
    # the join a true semi-join: even if a (match, user, hero) ever had duplicate
    # playtime rows, the eligible set is not fanned out.
    qualified_where: list[typing.Any] = [
        models.MatchStatistics.round == 0,
        models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
        models.MatchStatistics.value > 60,
    ]
    if user_id is not None:
        # Scope the playtime probe to the same user as the eligible base: a
        # per-user query then touches only that user's rows (a user-leading
        # index seek) instead of DISTINCT-scanning every player's playtime stats.
        qualified_where.append(models.MatchStatistics.user_id == user_id)
    qualified_combos = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.user_id.label("user_id"),
            models.MatchStatistics.hero_id.label("hero_id"),
        )
        .where(*qualified_where)
        .distinct()
        .cte(f"{cte_name}_qualified")
    )

    where_conditions: list[typing.Any] = [
        models.MatchStatistics.round == 0,
        models.MatchStatistics.hero_id.isnot(None),
    ]
    if user_id is not None:
        where_conditions.append(models.MatchStatistics.user_id == user_id)
    if stats:
        where_conditions.append(models.MatchStatistics.name.in_(stats))

    base_select = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.user_id.label("user_id"),
            models.MatchStatistics.hero_id.label("hero_id"),
            models.MatchStatistics.name.label("name"),
            models.MatchStatistics.value.label("value"),
        )
        .join(
            qualified_combos,
            sa.and_(
                qualified_combos.c.match_id == models.MatchStatistics.match_id,
                qualified_combos.c.user_id == models.MatchStatistics.user_id,
                qualified_combos.c.hero_id == models.MatchStatistics.hero_id,
            ),
        )
        .where(*where_conditions)
    )

    if tournament_id is not None or workspace_id is not None:
        base_select = base_select.join(models.Match, models.Match.id == models.MatchStatistics.match_id).join(
            models.Encounter, models.Encounter.id == models.Match.encounter_id
        )
        if tournament_id is not None:
            base_select = base_select.where(models.Encounter.tournament_id == tournament_id)
        if workspace_id is not None:
            base_select = base_select.join(
                models.Tournament, models.Tournament.id == models.Encounter.tournament_id
            ).where(models.Tournament.workspace_id == workspace_id)

    return base_select.cte(cte_name)


def _apply_overview_role_filters(
    query: sa.Select,
    *,
    role: enums.HeroClass | None,
    div_min: int | None,
    div_max: int | None,
    grid: DivisionGrid,
    workspace_id: int | None = None,
) -> sa.Select:
    """Keep users who have a player row matching the role/division chips.

    Workspace-scoped reads resolve the division range against the one
    workspace grid. The all-workspaces read (``workspace_id is None``) cannot:
    the same rank is a different division in different grids, so each player
    row is matched against its own tournament's effective grid.
    """
    role_filters: list[typing.Any] = [
        models.Player.workspace_member.has(models.WorkspaceMember.player_id == models.User.id),
        models.Player.is_substitution.is_(False),
    ]

    if role is not None:
        role_filters.append(models.Player.role == role)
    if workspace_id is None:
        role_filters.extend(
            effective_division_filter_predicates(
                models.Player.rank,
                models.Player.tournament_id,
                div_min,
                div_max,
            )
        )
    else:
        role_filters.extend(division_filter_predicates(models.Player.rank, div_min, div_max, grid))

    role_exists = sa.exists(sa.select(1).select_from(models.Player).where(*role_filters).correlate(models.User))
    return query.where(role_exists)


def _apply_workspace_member_filter(query: sa.Select, workspace_id: int | None) -> sa.Select:
    """Scope a ``User``-selecting query to members of the given workspace.

    Post identity/workspace refactor, workspace membership is anchored on
    ``workspace_member.player_id -> players.user.id``. When ``workspace_id`` is
    ``None`` the query is returned unchanged (no scoping), mirroring the
    ``workspace_filter`` contract in ``core.workspace``.
    """
    if workspace_id is None:
        return query
    member_exists = sa.exists(
        sa.select(1)
        .select_from(models.WorkspaceMember)
        .where(
            models.WorkspaceMember.player_id == models.User.id,
            models.WorkspaceMember.workspace_id == workspace_id,
        )
    )
    return query.where(member_exists)


def _compare_player_scope_filters(
    player_model: type[models.Player],
    user_id_column: sa.ColumnElement[typing.Any] | int,
    *,
    role: enums.HeroClass | None,
    div_min: int | None,
    div_max: int | None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> list[typing.Any]:
    filters: list[typing.Any] = [
        player_model.workspace_member.has(models.WorkspaceMember.player_id == user_id_column),
        player_model.is_substitution.is_(False),
    ]

    if role is not None:
        filters.append(player_model.role == role)
    filters.extend(division_filter_predicates(player_model.rank, div_min, div_max, grid))
    if tournament_id is not None:
        filters.append(player_model.tournament_id == tournament_id)

    return filters


def _compare_tournament_scope_exists(
    user_id_column: sa.ColumnElement[typing.Any] | int,
    tournament_id_column: sa.ColumnElement[typing.Any],
    *,
    role: enums.HeroClass | None,
    div_min: int | None,
    div_max: int | None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ColumnElement[bool]:
    scoped_player = aliased(models.Player)
    scoped_tournament = aliased(models.Tournament)
    filters = _compare_player_scope_filters(
        scoped_player,
        user_id_column,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
    )
    filters.append(scoped_player.tournament_id == tournament_id_column)
    filters.extend(
        [
            scoped_tournament.id == scoped_player.tournament_id,
            scoped_tournament.is_finished.is_(True),
            scoped_tournament.is_league.is_(False),
        ]
    )
    return sa.exists(sa.select(1).select_from(scoped_player).select_from(scoped_tournament).where(*filters))


def _compare_team_scope_exists(
    user_id_column: sa.ColumnElement[typing.Any] | int,
    team_id_column: sa.ColumnElement[typing.Any],
    *,
    role: enums.HeroClass | None,
    div_min: int | None,
    div_max: int | None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ColumnElement[bool]:
    scoped_player = aliased(models.Player)
    filters = _compare_player_scope_filters(
        scoped_player,
        user_id_column,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
    )
    filters.append(scoped_player.team_id == team_id_column)
    return sa.exists(sa.select(1).select_from(scoped_player).where(*filters))


def _compare_user_scope_exists(
    user_id_column: sa.ColumnElement[typing.Any] | int,
    *,
    role: enums.HeroClass | None,
    div_min: int | None,
    div_max: int | None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ColumnElement[bool]:
    scoped_player = aliased(models.Player)
    scoped_tournament = aliased(models.Tournament)
    filters = _compare_player_scope_filters(
        scoped_player,
        user_id_column,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
    )
    filters.extend(
        [
            scoped_tournament.id == scoped_player.tournament_id,
            scoped_tournament.is_finished.is_(True),
            scoped_tournament.is_league.is_(False),
        ]
    )
    return sa.exists(sa.select(1).select_from(scoped_player).select_from(scoped_tournament).where(*filters))


def _hero_compare_stat_visibility_condition(
    name_column: sa.ColumnElement[typing.Any],
    hero_id_column: sa.ColumnElement[typing.Any],
    *,
    hero_id: int | None,
) -> sa.ColumnElement[bool]:
    if hero_id is not None:
        return hero_id_column == hero_id

    return sa.or_(
        hero_id_column.isnot(None),
        name_column == enums.LogStatsName.Performance,
    )
