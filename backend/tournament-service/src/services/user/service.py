import typing
from collections import defaultdict

import sqlalchemy as sa
from cashews import cache
from shared.division_grid import DivisionGrid, division_case_expr
from shared.services.achievement_effective import build_effective_achievement_rows_subquery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from src import models
from src.core import enums, pagination, utils
from src.services.team import service as team_service

if typing.TYPE_CHECKING:
    from src import schemas as app_schemas

home_score_case = sa.case(
    (models.Encounter.home_team_id == models.Team.id, models.Encounter.home_score),
    else_=models.Encounter.away_score,
)
away_score_case = sa.case(
    (models.Encounter.home_team_id == models.Team.id, models.Encounter.away_score),
    else_=models.Encounter.home_score,
)

winrate_sum = sa.func.sum(home_score_case) / (sa.func.sum(home_score_case) + sa.func.sum(away_score_case))

USER_RELATION_ENTITIES = {"battle_tag", "discord", "twitch"}

OVERVIEW_HERO_METRICS: tuple[enums.LogStatsName, ...] = (
    enums.LogStatsName.Eliminations,
    enums.LogStatsName.FinalBlows,
    enums.LogStatsName.HeroDamageDealt,
    enums.LogStatsName.HealingDealt,
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


def user_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """
    Constructs a list of SQLAlchemy load options for querying related entities of a `User` model.

    Args:
        in_entities: A list of strings representing the names of related entities to load.
        child: An optional SQLAlchemy relationship or join entity to chain the load options.

    Returns:
        A list of SQLAlchemy load options (`_AbstractLoad`) for the specified entities.
    """
    entities = []
    if "battle_tag" in in_entities:
        entities.append(utils.join_entity(child, models.User.battle_tag))
    if "discord" in in_entities:
        entities.append(utils.join_entity(child, models.User.discord))
    if "twitch" in in_entities:
        entities.append(utils.join_entity(child, models.User.twitch))
    return entities


def join_entities(query: sa.Select, in_entities: list[str]) -> sa.Select:
    """
    Joins related entities to a SQLAlchemy query based on the provided entity names.

    Args:
        query: The SQLAlchemy query to modify.
        in_entities: A list of strings representing the names of related entities to join.

    Returns:
        The modified SQLAlchemy query with the specified joins.
    """
    if "battle_tag" in in_entities:
        query = query.join(models.UserBattleTag, models.User.id == models.UserBattleTag.user_id)
    if "discord" in in_entities:
        query = query.join(models.UserDiscord, models.User.id == models.UserDiscord.user_id)
    if "twitch" in in_entities:
        query = query.join(models.UserTwitch, models.User.id == models.UserTwitch.user_id)

    return query


def _sort_field_name(sort: str) -> str:
    if sort.startswith("similarity"):
        parts = sort.split(":", 1)
        if len(parts) == 2:
            return parts[1]
    return sort


def _relation_entities_for_user_query(fields: list[str], sort: str) -> list[str]:
    relation_entities: set[str] = set()

    for field in fields:
        top_level_field = field.split(".", 1)[0]
        if top_level_field in USER_RELATION_ENTITIES:
            relation_entities.add(top_level_field)

    sort_field = _sort_field_name(sort).split(".", 1)[0]
    if sort_field in USER_RELATION_ENTITIES:
        relation_entities.add(sort_field)

    return list(relation_entities)


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
    hero_playtime_stat = sa.alias(models.MatchStatistics)

    where_conditions: list[typing.Any] = [
        models.MatchStatistics.round == 0,
        models.MatchStatistics.hero_id.isnot(None),
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
    ]
    if user_id is not None:
        where_conditions.append(models.MatchStatistics.user_id == user_id)
    if stats:
        where_conditions.append(models.MatchStatistics.name.in_(stats))

    base_select = sa.select(
        models.MatchStatistics.match_id.label("match_id"),
        models.MatchStatistics.user_id.label("user_id"),
        models.MatchStatistics.hero_id.label("hero_id"),
        models.MatchStatistics.name.label("name"),
        models.MatchStatistics.value.label("value"),
    ).where(*where_conditions)

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
) -> sa.Select:
    div_expr = division_case_expr(models.Player.rank, grid)
    role_filters: list[typing.Any] = [
        models.Player.user_id == models.User.id,
        models.Player.is_substitution.is_(False),
    ]

    if role is not None:
        role_filters.append(models.Player.role == role)
    if div_min is not None:
        role_filters.append(div_expr >= div_min)
    if div_max is not None:
        role_filters.append(div_expr <= div_max)

    role_exists = sa.exists(sa.select(1).select_from(models.Player).where(*role_filters))
    return query.where(role_exists)


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
    div_expr = division_case_expr(player_model.rank, grid)
    filters: list[typing.Any] = [
        player_model.user_id == user_id_column,
        player_model.is_substitution.is_(False),
    ]

    if role is not None:
        filters.append(player_model.role == role)
    if div_min is not None:
        filters.append(div_expr >= div_min)
    if div_max is not None:
        filters.append(div_expr <= div_max)
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


def _overview_tournaments_count_expr(
    user_id_column: sa.ColumnElement[typing.Any],
    *,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ScalarSelect:
    player_filters = _compare_player_scope_filters(
        models.Player,
        user_id_column,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
    )
    where_conditions: list[typing.Any] = [
        *player_filters,
        models.Tournament.is_finished.is_(True),
        models.Tournament.is_league.is_(False),
    ]
    if tournament_id is not None:
        where_conditions.append(models.Tournament.id == tournament_id)
    return (
        sa.select(sa.func.count(sa.distinct(models.Team.tournament_id)))
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
        .where(*where_conditions)
        .scalar_subquery()
    )


def _overview_achievements_count_expr(
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
    user_id_column: sa.ColumnElement[typing.Any],
    *,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ScalarSelect:
    player_filters = _compare_player_scope_filters(
        models.Player,
        user_id_column,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
    )
    where_conditions: list[typing.Any] = [
        *player_filters,
        models.Tournament.is_finished.is_(True),
        models.Tournament.is_league.is_(False),
    ]
    if tournament_id is not None:
        where_conditions.append(models.Tournament.id == tournament_id)
    team_placement_subquery = (
        sa.select(
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
    user_id_column: sa.ColumnElement[typing.Any],
    *,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ScalarSelect:
    player_filters = _compare_player_scope_filters(
        models.Player,
        user_id_column,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
    )
    where_conditions: list[typing.Any] = [
        *player_filters,
        models.Tournament.is_finished.is_(True),
        models.Tournament.is_league.is_(False),
        models.Standing.buchholz.is_(None),
    ]
    if tournament_id is not None:
        where_conditions.append(models.Tournament.id == tournament_id)
    return (
        sa.select(sa.func.avg(models.Standing.position))
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
        .where(*where_conditions)
        .scalar_subquery()
    )


def _overview_avg_group_placement_expr(
    user_id_column: sa.ColumnElement[typing.Any],
    *,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ScalarSelect:
    player_filters = _compare_player_scope_filters(
        models.Player,
        user_id_column,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
    )
    where_conditions: list[typing.Any] = [
        *player_filters,
        models.Tournament.is_finished.is_(True),
        models.Tournament.is_league.is_(False),
        models.Standing.buchholz.isnot(None),
    ]
    if tournament_id is not None:
        where_conditions.append(models.Tournament.id == tournament_id)
    return (
        sa.select(sa.func.avg(models.Standing.position))
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
        .where(*where_conditions)
        .scalar_subquery()
    )


def _overview_avg_closeness_expr(
    user_id_column: sa.ColumnElement[typing.Any],
    *,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ScalarSelect:
    player_filters = _compare_player_scope_filters(
        models.Player,
        user_id_column,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
    )
    where_conditions: list[typing.Any] = [
        *player_filters,
        models.Tournament.is_finished.is_(True),
        models.Tournament.is_league.is_(False),
        models.Encounter.closeness.isnot(None),
    ]
    if tournament_id is not None:
        where_conditions.append(models.Tournament.id == tournament_id)
    return (
        sa.select(sa.func.avg(models.Encounter.closeness))
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(*where_conditions)
        .scalar_subquery()
    )


def _overview_maps_won_expr(
    user_id_column: sa.ColumnElement[typing.Any],
    *,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ScalarSelect:
    player_filters = _compare_player_scope_filters(
        models.Player,
        user_id_column,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
    )
    where_conditions: list[typing.Any] = [
        *player_filters,
        models.Tournament.is_finished.is_(True),
        models.Tournament.is_league.is_(False),
    ]
    if tournament_id is not None:
        where_conditions.append(models.Tournament.id == tournament_id)
    return (
        sa.select(sa.func.coalesce(sa.func.sum(home_score_case), 0))
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(*where_conditions)
        .scalar_subquery()
    )


def _overview_maps_lost_expr(
    user_id_column: sa.ColumnElement[typing.Any],
    *,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ScalarSelect:
    player_filters = _compare_player_scope_filters(
        models.Player,
        user_id_column,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
    )
    where_conditions: list[typing.Any] = [
        *player_filters,
        models.Tournament.is_finished.is_(True),
        models.Tournament.is_league.is_(False),
    ]
    if tournament_id is not None:
        where_conditions.append(models.Tournament.id == tournament_id)
    return (
        sa.select(sa.func.coalesce(sa.func.sum(away_score_case), 0))
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(*where_conditions)
        .scalar_subquery()
    )


def _overview_match_stat_avg(
    user_id_column: sa.ColumnElement[typing.Any],
    stat: enums.LogStatsName,
    hero_id_is_not_none: bool = True,
    *,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ScalarSelect:
    where_conditions: list[typing.Any] = [
        models.MatchStatistics.user_id == user_id_column,
        models.MatchStatistics.round == 0,
        models.MatchStatistics.hero_id.isnot(None) if hero_id_is_not_none else sa.literal(True),
        models.MatchStatistics.name == stat,
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
        sa.select(sa.func.avg(models.MatchStatistics.value))
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
    )

    if tournament_id is not None:
        query = query.join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        where_conditions.append(models.Encounter.tournament_id == tournament_id)

    return query.where(*where_conditions).scalar_subquery()


def _overview_match_stat_avg_10_expr(
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
        sa.select(sa.func.sum(models.MatchStatistics.value) / sa.func.nullif(sa.func.sum(models.Match.time), 0) * 600)
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
    )

    if tournament_id is not None:
        query = query.join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        where_conditions.append(models.Encounter.tournament_id == tournament_id)

    return query.where(*where_conditions).scalar_subquery()


async def get(session: AsyncSession, user_id: int, entities: list[str]) -> models.User | None:
    """
    Retrieves a `User` model instance by its ID, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `User` model instance if found, otherwise `None`.
    """
    query = sa.select(models.User).options(*user_entities(entities)).where(sa.and_(models.User.id == user_id))
    result = await session.execute(query)
    return result.unique().scalar_one_or_none()


async def get_all(
    session: AsyncSession, params: pagination.PaginationSortSearchParams
) -> tuple[typing.Sequence[models.User], int]:
    """
    Retrieves a paginated list of `User` model instances based on filtering and sorting parameters.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        params: An instance of `SearchPaginationParams` containing pagination, sorting, and filtering parameters.

    Returns:
        A tuple containing:
        1. A sequence of `User` model instances.
        2. The total count of users matching the filtering criteria.
    """
    query = sa.select(models.User).options(*user_entities(params.entities))
    total_query = sa.select(sa.func.count(sa.distinct(models.User.id)))

    relation_entities = _relation_entities_for_user_query(params.fields, params.sort)
    if relation_entities:
        query = join_entities(query, relation_entities)
        total_query = join_entities(total_query, relation_entities)

    if params.query:
        query = params.apply_search(query, models.User)
        total_query = params.apply_search(total_query, models.User)

    query = params.apply_pagination_sort(query, models.User)

    result = await session.execute(query)
    result_total = await session.execute(total_query)
    return result.unique().scalars().all(), result_total.scalar_one()


async def get_overview_users(
    session: AsyncSession,
    params: "app_schemas.UserOverviewParams",
    grid: DivisionGrid,
) -> tuple[typing.Sequence[models.User], int]:
    query = sa.select(models.User)
    total_query = sa.select(sa.func.count(sa.distinct(models.User.id)))

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

    sort_key = params.sort
    if sort_key == "tournaments_count":
        sort_expr = _overview_tournaments_count_expr(models.User.id, grid=grid)
    elif sort_key == "achievements_count":
        sort_expr = _overview_achievements_count_expr(models.User.id, grid=grid)
    elif sort_key == "avg_placement":
        sort_expr = _overview_avg_placement_expr(models.User.id, grid=grid)
    else:
        sort_expr = models.User.depth_get_column(sort_key.split("."))

    is_desc = params.order == pagination.SortOrder.DESC or params.order == "desc"
    if is_desc:
        query = query.order_by(sort_expr.desc(), models.User.id.asc())
    else:
        query = query.order_by(sort_expr.asc(), models.User.id.asc())

    query = params.apply_pagination(query)

    result = await session.execute(query)
    result_total = await session.execute(total_query)
    return result.unique().scalars().all(), result_total.scalar_one()


async def get_overview_role_divisions(
    session: AsyncSession,
    user_ids: list[int],
) -> dict[int, list[tuple[enums.HeroClass, int, int | None]]]:
    """Return (role, rank, division_grid_version_id) for each user's most recent entry per role.

    Division computation is intentionally deferred to the caller so that each
    player's rank can be normalised through the tournament's own grid version
    rather than a single global grid.
    """
    if not user_ids:
        return {}

    latest_roles_subquery = (
        sa.select(
            models.Player.user_id.label("user_id"),
            models.Player.role.label("role"),
            models.Player.rank.label("rank"),
            models.Player.tournament_id.label("tournament_id"),
            sa.func.row_number()
            .over(
                partition_by=[models.Player.user_id, models.Player.role],
                order_by=[models.Player.tournament_id.desc(), models.Player.id.desc()],
            )
            .label("row_num"),
        )
        .where(
            models.Player.user_id.in_(user_ids),
            models.Player.is_substitution.is_(False),
            models.Player.role.isnot(None),
        )
        .subquery()
    )

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
    session: AsyncSession,
    user_ids: list[int],
    workspace_id: int | None = None,
) -> dict[int, int]:
    if not user_ids:
        return {}

    query = (
        sa.select(
            models.Player.user_id,
            sa.func.count(sa.distinct(models.Team.tournament_id)).label("tournaments_count"),
        )
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
        .where(
            models.Player.user_id.in_(user_ids),
            models.Player.is_substitution.is_(False),
            models.Tournament.is_finished.is_(True),
            models.Tournament.is_league.is_(False),
        )
        .group_by(models.Player.user_id)
    )

    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)

    result = await session.execute(query)
    return dict(result.all())


async def get_overview_achievements_count(
    session: AsyncSession,
    user_ids: list[int],
) -> dict[int, int]:
    if not user_ids:
        return {}

    effective_rows = build_effective_achievement_rows_subquery(
        user_ids=user_ids,
        name="overview_achievement_count_rows",
    )
    query = sa.select(
        effective_rows.c.user_id,
        sa.func.count(sa.distinct(effective_rows.c.achievement_rule_id)).label("achievements_count"),
    ).group_by(effective_rows.c.user_id)

    result = await session.execute(query)
    return dict(result.all())


async def get_overview_averages(
    session: AsyncSession,
    user_ids: list[int],
) -> dict[int, tuple[float | None, float | None, float | None, float | None]]:
    if not user_ids:
        return {}

    team_overall_subquery = (
        sa.select(
            models.Player.user_id.label("user_id"),
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
        .where(
            models.Player.user_id.in_(user_ids),
            models.Player.is_substitution.is_(False),
            models.Tournament.is_finished.is_(True),
            models.Tournament.is_league.is_(False),
        )
        .group_by(models.Player.user_id, models.Player.team_id)
        .cte("overview_team_overall")
    )

    placement_query = sa.select(
        team_overall_subquery.c.user_id,
        sa.func.avg(team_overall_subquery.c.overall_position).label("avg_placement"),
    ).group_by(team_overall_subquery.c.user_id)

    placement_stage_query = (
        sa.select(
            models.Player.user_id,
            sa.func.avg(sa.case((models.Standing.buchholz.isnot(None), models.Standing.position), else_=None)).label(
                "avg_group_placement"
            ),
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
        .where(
            models.Player.user_id.in_(user_ids),
            models.Player.is_substitution.is_(False),
            models.Tournament.is_finished.is_(True),
            models.Tournament.is_league.is_(False),
        )
        .group_by(models.Player.user_id)
    )

    closeness_query = (
        sa.select(
            models.Player.user_id,
            sa.func.avg(models.Encounter.closeness).label("avg_closeness"),
        )
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            models.Player.user_id.in_(user_ids),
            models.Player.is_substitution.is_(False),
            models.Tournament.is_finished.is_(True),
            models.Tournament.is_league.is_(False),
            models.Encounter.closeness.isnot(None),
        )
        .group_by(models.Player.user_id)
    )

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
        avg_placement, avg_playoff_placement, avg_group_placement, _ = payload.get(user_id, (None, None, None, None))
        payload[user_id] = (avg_placement, avg_playoff_placement, avg_group_placement, avg_closeness)

    return payload


async def get_overview_top_heroes(
    session: AsyncSession,
    user_ids: list[int],
    *,
    limit: int = 5,
) -> dict[int, list[tuple[models.Hero, float]]]:
    if not user_ids:
        return {}

    playtime_subquery = (
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
        .cte("overview_user_hero_playtime")
    )

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
    session: AsyncSession,
    top_heroes: dict[int, list[tuple[models.Hero, float]]],
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

    result = await session.execute(query)

    payload: dict[tuple[int, int], dict[enums.LogStatsName, float]] = defaultdict(dict)
    for user_id, hero_id, stat_name, avg_10 in result.all():
        payload[(user_id, hero_id)][stat_name] = avg_10

    return dict(payload)


def _compare_metrics_query(
    *,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> sa.Select:
    gk = {
        "role": role,
        "div_min": div_min,
        "div_max": div_max,
        "tournament_id": tournament_id,
        "grid": grid,
    }
    maps_won_expr = _overview_maps_won_expr(models.User.id, **gk)
    maps_lost_expr = _overview_maps_lost_expr(models.User.id, **gk)
    maps_total_expr = sa.func.coalesce(maps_won_expr, 0) + sa.func.coalesce(maps_lost_expr, 0)
    maps_winrate_expr = sa.func.coalesce(maps_won_expr / sa.func.nullif(maps_total_expr, 0), 0)

    uid = models.User.id
    return sa.select(
        uid.label("id"),
        models.User.name.label("name"),
        _overview_tournaments_count_expr(uid, **gk).label("tournaments_count"),
        _overview_achievements_count_expr(uid, **gk).label("achievements_count"),
        maps_won_expr.label("maps_won"),
        maps_total_expr.label("maps_total"),
        maps_winrate_expr.label("maps_winrate"),
        _overview_avg_placement_expr(uid, **gk).label("avg_placement"),
        _overview_avg_playoff_placement_expr(uid, **gk).label("avg_playoff_placement"),
        _overview_avg_group_placement_expr(uid, **gk).label("avg_group_placement"),
        _overview_avg_closeness_expr(uid, **gk).label("avg_closeness"),
        _overview_match_stat_avg_10_expr(uid, enums.LogStatsName.Eliminations, **gk).label("eliminations_avg_10"),
        _overview_match_stat_avg_10_expr(uid, enums.LogStatsName.FinalBlows, **gk).label("final_blows_avg_10"),
        _overview_match_stat_avg_10_expr(uid, enums.LogStatsName.HeroDamageDealt, **gk).label(
            "hero_damage_dealt_avg_10"
        ),
        _overview_match_stat_avg_10_expr(uid, enums.LogStatsName.HealingDealt, **gk).label("healing_dealt_avg_10"),
        _overview_match_stat_avg(uid, enums.LogStatsName.Performance, False, **gk).label("mvp_score_avg"),
    )


def _normalize_compare_value(value: typing.Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def get_compare_population(
    session: AsyncSession,
    *,
    user_ids: list[int] | None = None,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> list[dict[str, typing.Any]]:
    query = _compare_metrics_query(role=role, div_min=div_min, div_max=div_max, tournament_id=tournament_id, grid=grid)

    if user_ids is not None:
        if not user_ids:
            return []
        query = query.where(models.User.id.in_(user_ids))

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

    result = await session.execute(query)
    payload: list[dict[str, typing.Any]] = []

    for row in result.mappings().all():
        item: dict[str, typing.Any] = {
            "id": row["id"],
            "name": row["name"],
        }
        for key, _label, _higher_is_better in COMPARE_METRIC_DEFINITIONS:
            item[key] = _normalize_compare_value(row.get(key))
        payload.append(item)

    return payload


async def get_compare_population_users(
    session: AsyncSession,
    *,
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> list[tuple[int, str]]:
    query = sa.select(models.User.id, models.User.name)

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

    result = await session.execute(query)
    return [(int(user_id), str(name)) for user_id, name in result.all()]


async def get_user_hero_compare_stats(
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
    playtime_query = (
        sa.select(sa.func.coalesce(sa.func.sum(models.MatchStatistics.value), 0.0))
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .where(
            models.MatchStatistics.user_id == user_id,
            models.MatchStatistics.round == 0,
            models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
            models.MatchStatistics.hero_id.isnot(None),
        )
    )

    if role is not None or div_min is not None or div_max is not None:
        playtime_query = playtime_query.where(
            _compare_team_scope_exists(
                user_id,
                models.MatchStatistics.team_id,
                role=role,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                grid=grid,
            )
        )

    if tournament_id is not None:
        playtime_query = playtime_query.join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        playtime_query = playtime_query.where(models.Encounter.tournament_id == tournament_id)

    if hero_id is not None:
        playtime_query = playtime_query.where(models.MatchStatistics.hero_id == hero_id)
    if map_id is not None:
        playtime_query = playtime_query.where(models.Match.map_id == map_id)

    playtime_result = await session.execute(playtime_query)
    playtime_seconds = float(playtime_result.scalar_one() or 0.0)

    if not stats:
        stats = list(DEFAULT_HERO_COMPARE_STATS)

    hero_time_alias = aliased(models.MatchStatistics)
    stats_where: list[typing.Any] = [
        models.MatchStatistics.user_id == user_id,
        models.MatchStatistics.round == 0,
        _hero_compare_stat_visibility_condition(
            models.MatchStatistics.name,
            models.MatchStatistics.hero_id,
            hero_id=hero_id,
        ),
        models.MatchStatistics.name.in_(stats),
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

    stats_query = (
        sa.select(
            models.MatchStatistics.name,
            (sa.func.sum(models.MatchStatistics.value) / sa.func.nullif(sa.func.sum(models.Match.time), 0) * 600).label(
                "avg_10"
            ),
        )
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .where(*stats_where)
        .group_by(models.MatchStatistics.name)
    )

    if role is not None or div_min is not None or div_max is not None:
        stats_query = stats_query.where(
            _compare_team_scope_exists(
                user_id,
                models.MatchStatistics.team_id,
                role=role,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                grid=grid,
            )
        )

    if tournament_id is not None:
        stats_query = stats_query.join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        stats_query = stats_query.where(models.Encounter.tournament_id == tournament_id)

    if map_id is not None:
        stats_query = stats_query.where(models.Match.map_id == map_id)

    stats_result = await session.execute(stats_query)
    stats_payload = {name: float(avg_10) for name, avg_10 in stats_result.all() if avg_10 is not None}
    return playtime_seconds, stats_payload


async def get_users_hero_compare_stats(
    session: AsyncSession,
    *,
    user_ids: list[int],
    hero_id: int | None,
    map_id: int | None,
    stats: list[enums.LogStatsName],
    role: enums.HeroClass | None = None,
    div_min: int | None = None,
    div_max: int | None = None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
) -> tuple[dict[int, float], dict[tuple[int, enums.LogStatsName], float]]:
    if not user_ids:
        return {}, {}

    playtime_query = (
        sa.select(
            models.MatchStatistics.user_id,
            sa.func.coalesce(sa.func.sum(models.MatchStatistics.value), 0.0).label("playtime_seconds"),
        )
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .where(
            models.MatchStatistics.user_id.in_(user_ids),
            models.MatchStatistics.round == 0,
            models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
            models.MatchStatistics.hero_id.isnot(None),
        )
        .group_by(models.MatchStatistics.user_id)
    )

    if role is not None or div_min is not None or div_max is not None:
        playtime_query = playtime_query.where(
            _compare_team_scope_exists(
                models.MatchStatistics.user_id,
                models.MatchStatistics.team_id,
                role=role,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                grid=grid,
            )
        )

    if tournament_id is not None:
        playtime_query = playtime_query.join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        playtime_query = playtime_query.where(models.Encounter.tournament_id == tournament_id)

    if hero_id is not None:
        playtime_query = playtime_query.where(models.MatchStatistics.hero_id == hero_id)
    if map_id is not None:
        playtime_query = playtime_query.where(models.Match.map_id == map_id)

    playtime_result = await session.execute(playtime_query)
    playtime_payload = {int(user_id): float(playtime or 0.0) for user_id, playtime in playtime_result.all()}

    if not stats:
        stats = list(DEFAULT_HERO_COMPARE_STATS)

    hero_time_alias = aliased(models.MatchStatistics)
    stats_where: list[typing.Any] = [
        models.MatchStatistics.user_id.in_(user_ids),
        models.MatchStatistics.round == 0,
        _hero_compare_stat_visibility_condition(
            models.MatchStatistics.name,
            models.MatchStatistics.hero_id,
            hero_id=hero_id,
        ),
        models.MatchStatistics.name.in_(stats),
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

    stats_query = (
        sa.select(
            models.MatchStatistics.user_id,
            models.MatchStatistics.name,
            (sa.func.sum(models.MatchStatistics.value) / sa.func.nullif(sa.func.sum(models.Match.time), 0) * 600).label(
                "avg_10"
            ),
        )
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .where(*stats_where)
        .group_by(models.MatchStatistics.user_id, models.MatchStatistics.name)
    )

    if role is not None or div_min is not None or div_max is not None:
        stats_query = stats_query.where(
            _compare_team_scope_exists(
                models.MatchStatistics.user_id,
                models.MatchStatistics.team_id,
                role=role,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                grid=grid,
            )
        )

    if tournament_id is not None:
        stats_query = stats_query.join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        stats_query = stats_query.where(models.Encounter.tournament_id == tournament_id)

    if map_id is not None:
        stats_query = stats_query.where(models.Match.map_id == map_id)

    stats_result = await session.execute(stats_query)
    stats_payload: dict[tuple[int, enums.LogStatsName], float] = {}
    for user_id, stat_name, avg_10 in stats_result.all():
        if avg_10 is None:
            continue
        stats_payload[(int(user_id), stat_name)] = float(avg_10)

    return playtime_payload, stats_payload


async def search_by_name(session: AsyncSession, query: str, fields: list[str]) -> typing.Sequence[models.UserBattleTag]:
    """
    Retrieves a `UserBattleTag` model instance by its name, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        query: The name of the user to retrieve.
        fields: A list of strings representing the fields to search by.

    Returns:
        A `UserBattleTag` model instance if found, otherwise `None`.
    """
    query = query.strip().replace("-", "#")
    if not query or len(query) < 2:
        return []

    if not fields:
        fields = ["battle_tag"]

    columns = [models.UserBattleTag.depth_get_column(field.split(".")) for field in fields]
    if not columns:
        return []

    like_query = f"{query}%" if len(query) < 3 else f"%{query}%"
    query_lower = query.lower()

    exact_scores = [sa.case((sa.func.lower(column) == query_lower, 0), else_=1) for column in columns]
    prefix_scores = [sa.case((sa.func.lower(column).like(f"{query_lower}%"), 0), else_=1) for column in columns]
    similarity_scores = [sa.func.word_similarity(column, query) for column in columns]

    best_exact = sa.func.least(*exact_scores) if len(exact_scores) > 1 else exact_scores[0]
    best_prefix = sa.func.least(*prefix_scores) if len(prefix_scores) > 1 else prefix_scores[0]
    best_similarity = sa.func.greatest(*similarity_scores) if len(similarity_scores) > 1 else similarity_scores[0]

    conditions = [column.ilike(like_query) for column in columns]
    if len(query) >= 3:
        conditions.extend([column.op("%")(query) for column in columns])

    stmt = (
        sa.select(models.UserBattleTag)
        .where(sa.or_(*conditions))
        .order_by(
            best_exact.asc(),
            best_prefix.asc(),
            best_similarity.desc(),
            models.UserBattleTag.battle_tag.asc(),
        )
        .limit(10)
    )
    result = await session.scalars(stmt)
    return result.unique().all()


async def find_by_battle_tag(session: AsyncSession, battle_tag: str, entities: list[str]) -> models.User | None:
    """
    Retrieves a `User` model instance by its battle tag, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        battle_tag: The battle tag of the user to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `User` model instance if found, otherwise `None`.
    """
    normalized_battle_tag = battle_tag.strip().replace("-", "#")
    if not normalized_battle_tag:
        return None

    battle_tag_lower = normalized_battle_tag.lower()
    exact_user_name_match = sa.func.lower(models.User.name) == battle_tag_lower

    query = (
        sa.select(models.User)
        .options(*user_entities(entities))
        .outerjoin(models.UserBattleTag, models.User.id == models.UserBattleTag.user_id)
        .where(
            sa.or_(
                exact_user_name_match,
                sa.func.lower(models.UserBattleTag.battle_tag) == battle_tag_lower,
                sa.func.lower(models.UserBattleTag.name) == battle_tag_lower,
            )
        )
        .order_by(
            sa.case((exact_user_name_match, 0), else_=1),
            models.User.id.asc(),
        )
        .limit(1)
    )
    result = await session.execute(query)
    return result.unique().scalar_one_or_none()


async def get_by_discord(session: AsyncSession, discord: str, entities: list[str]) -> models.User | None:
    """
    Retrieves a `User` model instance by its Discord ID.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        discord: The Discord ID of the user to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `User` model instance if found, otherwise `None`.
    """
    query = (
        sa.select(models.User)
        .options(*user_entities(entities))
        .join(models.UserDiscord, models.User.id == models.UserDiscord.user_id)
        .where(models.UserDiscord.name == discord)
    )
    result = await session.scalars(query)
    return result.unique().first()


async def get_overall_statistics(
    session: AsyncSession, user_id: int, workspace_id: int | None = None
) -> tuple[int, int, int]:
    """
    Retrieves overall statistics for a user, including maps won, maps lost, and average closeness.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve statistics for.

    Returns:
        A tuple containing:
        1. The number of maps won.
        2. The number of maps lost.
        3. The average closeness of encounters.
    """
    query = (
        sa.select(
            sa.func.sum(home_score_case).label("won_maps"),
            sa.func.sum(away_score_case).label("lost_maps"),
            sa.func.avg(models.Encounter.closeness).label("closeness"),
        )
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .where(
            sa.and_(
                models.Player.is_substitution.is_(False),
                models.Player.user_id == user_id,
            )
        )
        .group_by(models.Player.user_id)
    )

    if workspace_id is not None:
        query = query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id).where(
            models.Tournament.workspace_id == workspace_id
        )

    matches = await session.execute(query)
    return matches.first()


async def get_teams(
    session: AsyncSession,
    user_id: int,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
) -> tuple[typing.Sequence[models.Team], int]:
    """
    Retrieves a paginated list of teams associated with a user, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve teams for.
        params: An instance of `PaginationParams` containing pagination parameters.

    Returns:
        A tuple containing:
        1. A sequence of `Team` model instances.
        2. The total count of teams associated with the user.
    """
    total_query = (
        sa.select(sa.func.count(sa.distinct(models.Team.id)))
        .join(models.Player, models.Player.team_id == models.Team.id)
        .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
        .where(
            sa.and_(
                models.Player.user_id == user_id,
                models.Player.is_substitution.is_(False),
                models.Tournament.is_finished.is_(True),
            )
        )
    )

    query = (
        sa.select(models.Team)
        .options(*team_service.team_entities(params.entities))
        .join(models.Player, models.Player.team_id == models.Team.id)
        .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
        .where(
            sa.and_(
                models.Player.user_id == user_id,
                models.Player.is_substitution.is_(False),
                models.Tournament.is_finished.is_(True),
            )
        )
    )
    if workspace_id is not None:
        total_query = total_query.where(models.Tournament.workspace_id == workspace_id)
        query = query.where(models.Tournament.workspace_id == workspace_id)

    query = params.apply_pagination_sort(query, models.Team)
    result = await session.scalars(query)
    result_total = await session.execute(total_query)
    return result.unique().all(), result_total.scalar_one()


async def get_roles(
    session: AsyncSession, user_id: int, workspace_id: int | None = None, *, grid: DivisionGrid
) -> typing.Sequence[tuple[enums.HeroClass, int, int, list[dict]]]:
    """
    Retrieves the roles and statistics for a user across tournaments.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve roles for.

    Returns:
        A sequence of tuples containing:
        1. The role (e.g., tank, damage, support).
        2. The number of maps won.
        3. The number of maps lost.
        4. A list of dictionaries containing tournament and division information.
    """
    query = (
        sa.select(
            models.Player.role,
            sa.func.sum(home_score_case).label("won_maps"),
            sa.func.sum(away_score_case).label("lost_maps"),
            sa.func.jsonb_agg(
                sa.func.jsonb_build_object(
                    "tournament",
                    models.Team.tournament_id,
                    "rank",
                    models.Player.rank,
                    "division_grid_version_id",
                    models.Tournament.division_grid_version_id,
                )
            ),
        )
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .where(
            sa.and_(
                models.Player.is_substitution.is_(False),
                models.Player.user_id == user_id,
            )
        )
        .group_by(models.Player.role)
    )
    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)
    result = await session.execute(query)
    return result.all()  # type: ignore


async def get_tournament_role(
    session: AsyncSession, tournament: models.Tournament, user_id: int, *, grid: DivisionGrid
) -> tuple[enums.HeroClass, int]:
    """
    Retrieves the role and division of a user in a specific tournament.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        tournament: The `Tournament` model instance to filter by.
        user_id: The ID of the user to retrieve the role for.

    Returns:
        A tuple containing:
        1. The role of the user in the tournament.
        2. The division of the user in the tournament.
    """
    query = (
        sa.select(models.Player.role, division_case_expr(models.Player.rank, grid).label("div"))
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .where(
            sa.and_(
                models.Team.tournament_id == tournament.id,
                models.Player.user_id == user_id,
                models.Player.is_substitution.is_(False),
            )
        )
    )
    result_role = await session.execute(query)
    return result_role.one()  # type: ignore


async def get_tournaments_with_stats(
    session: AsyncSession,
    user_id: int,
    workspace_id: int | None = None,
) -> typing.Sequence[tuple[models.Team, int, int, int]]:
    """
    Retrieves a user's tournament history with statistics, including maps won, maps lost, and average closeness.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve tournament history for.

    Returns:
        A sequence of tuples containing:
        1. A `Team` model instance.
        2. The number of maps won.
        3. The number of maps lost.
        4. The average closeness of encounters.
    """
    query = (
        sa.select(
            models.Team,
            sa.func.sum(home_score_case).label("won_maps"),
            sa.func.sum(away_score_case).label("lost_maps"),
            sa.func.avg(models.Encounter.closeness).label("closeness"),
        )
        .select_from(models.Player)
        .options(
            selectinload(models.Team.players).selectinload(models.Player.user),
            selectinload(models.Team.tournament).selectinload(models.Tournament.standings),
            selectinload(models.Team.tournament).selectinload(models.Tournament.division_grid_version),
            selectinload(models.Team.standings).selectinload(models.Standing.group),
        )
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
        .where(
            sa.and_(
                models.Player.user_id == user_id,
                models.Player.is_substitution.is_(False),
            )
        )
        .group_by(models.Team.id)
    )

    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)

    result = await session.execute(query)
    return result.unique().all()


async def get_tournament_stats_overall(
    session: AsyncSession, tournament: models.Tournament, user_id: int
) -> tuple[int, int, int, float]:
    """
    Retrieves overall statistics for a user in a specific tournament, including maps won, maps lost, closeness, and playtime.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        tournament: The `Tournament` model instance to filter by.
        user_id: The ID of the user to retrieve statistics for.

    Returns:
        A tuple containing:
        1. The number of maps won.
        2. The number of maps lost.
        3. The average closeness of encounters.
        4. The total playtime in seconds.
    """
    playtime_subquery = (
        sa.select(sa.func.sum(models.MatchStatistics.value))
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .join(models.Match, models.Match.encounter_id == models.Encounter.id)
        .join(models.MatchStatistics, models.MatchStatistics.match_id == models.Match.id)
        .where(
            models.Player.user_id == user_id,
            models.Player.is_substitution.is_(False),
            models.Team.tournament_id == tournament.id,
            models.MatchStatistics.user_id == models.Player.user_id,
            models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
            models.MatchStatistics.hero_id.is_(None),
            models.MatchStatistics.round == 0,
        )
        .scalar_subquery()
    )

    query = (
        sa.select(
            sa.func.coalesce(sa.func.sum(home_score_case), 0).label("won_maps"),
            sa.func.coalesce(sa.func.sum(away_score_case), 0).label("lost_maps"),
            sa.func.coalesce(sa.func.avg(models.Encounter.closeness), 0).label("closeness"),
            sa.func.coalesce(playtime_subquery, 0).label("playtime"),
        )
        .select_from(models.Player)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .where(
            models.Player.user_id == user_id,
            models.Player.is_substitution.is_(False),
            models.Team.tournament_id == tournament.id,
        )
    )
    result = await session.execute(query)
    row = result.one_or_none()
    if not row:
        return 0, 0, 0, 0

    won_maps, lost_maps, closeness, playtime = row
    return won_maps, lost_maps, closeness, playtime


async def get_statistics_by_heroes(
    session: AsyncSession,
    user_id: int,
    stats: list[enums.LogStatsName] | None = None,
    tournament_id: int | None = None,
    workspace_id: int | None = None,
) -> typing.Sequence[tuple[enums.LogStatsName, models.Hero, float, float, float, dict]]:
    """
    Retrieves a user's hero statistics, including total value, max value, average value, and best performance metadata.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve hero statistics for.

    Returns:
        A sequence of tuples containing:
        1. The statistic name (e.g., HeroDamageDealt, Eliminations).
        2. The `Hero` model instance.
        3. The total value of the statistic.
        4. The maximum value of the statistic.
        5. The average value of the statistic (per 10 minutes).
        6. A dictionary containing metadata about the best performance (e.g., encounter ID, map name, tournament name).
    """
    eligible_stats = _build_eligible_hero_stats_cte(
        user_id=user_id,
        stats=stats,
        cte_name="eligible_user_hero_stats",
        tournament_id=tournament_id,
        workspace_id=workspace_id,
    )
    direction_score = _hero_direction_score(eligible_stats.c.value, eligible_stats.c.name)

    best_result_cte = (
        sa.select(
            eligible_stats.c.hero_id,
            eligible_stats.c.name,
            models.Match.encounter_id,
            models.Map.name.label("map_name"),
            models.Map.image_path.label("map_link"),
            models.Tournament.name.label("tournament_name"),
            eligible_stats.c.value,
            sa.func.row_number()
            .over(
                partition_by=[
                    eligible_stats.c.hero_id,
                    eligible_stats.c.name,
                ],
                order_by=[direction_score.desc(), models.Match.id.desc()],
            )
            .label("row_num"),
        )
        .join(models.Match, eligible_stats.c.match_id == models.Match.id)
        .join(models.Map, models.Map.id == models.Match.map_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .cte("best_result_cte")
    )

    query = (
        sa.select(
            eligible_stats.c.name,
            models.Hero,
            sa.func.sum(eligible_stats.c.value).label("total_value"),
            best_result_cte.c.value.label("best_value"),
            (sa.func.sum(eligible_stats.c.value) / sa.func.nullif(sa.func.sum(models.Match.time), 0) * 600).label(
                "avg_per_10min"
            ),
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
        .select_from(eligible_stats)
        .join(models.Match, models.Match.id == eligible_stats.c.match_id)
        .join(models.Hero, models.Hero.id == eligible_stats.c.hero_id)
        .join(
            best_result_cte,
            sa.and_(
                best_result_cte.c.hero_id == eligible_stats.c.hero_id,
                best_result_cte.c.name == eligible_stats.c.name,
                best_result_cte.c.row_num == 1,
            ),
        )
        .group_by(
            eligible_stats.c.name,
            models.Hero.id,
            best_result_cte.c.encounter_id,
            best_result_cte.c.map_name,
            best_result_cte.c.map_link,
            best_result_cte.c.tournament_name,
            best_result_cte.c.value,
        )
    )

    result = await session.execute(query)
    return result.all()


async def _get_statistics_by_heroes_all_values_impl(
    session: AsyncSession,
    stats: list[enums.LogStatsName] | None,
) -> typing.Sequence[tuple[enums.LogStatsName, int, float, float, dict]]:
    """
    Retrieves the best statistics for all heroes across all users, including max value, average value, and metadata.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.

    Returns:
        A sequence of tuples containing:
        1. The statistic name (e.g., HeroDamageDealt, Eliminations).
        2. The hero ID.
        3. The maximum value of the statistic.
        4. The average value of the statistic (per 10 minutes).
        5. A dictionary containing metadata about the best performance (e.g., encounter ID, map name, tournament name, username).
    """
    eligible_stats = _build_eligible_hero_stats_cte(
        user_id=None,
        stats=stats,
        cte_name="eligible_global_hero_stats",
    )
    direction_score = _hero_direction_score(eligible_stats.c.value, eligible_stats.c.name)

    best_encounter_cte = (
        sa.select(
            eligible_stats.c.hero_id,
            eligible_stats.c.name,
            models.Match.encounter_id,
            models.Map.name.label("map_name"),
            models.Map.image_path.label("map_image_path"),
            models.Tournament.name.label("tournament_name"),
            models.User.name.label("username"),
            eligible_stats.c.value,
            sa.func.row_number()
            .over(
                partition_by=[
                    eligible_stats.c.hero_id,
                    eligible_stats.c.name,
                ],
                order_by=[direction_score.desc(), models.Match.id.desc()],
            )
            .label("row_num"),
        )
        .join(models.Match, eligible_stats.c.match_id == models.Match.id)
        .join(models.Map, models.Map.id == models.Match.map_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .join(models.User, models.User.id == eligible_stats.c.user_id)
        .cte("best_global_hero_result")
    )

    query = (
        sa.select(
            eligible_stats.c.name,
            models.Hero.id,
            best_encounter_cte.c.value.label("best_value"),
            (sa.func.sum(eligible_stats.c.value) / sa.func.nullif(sa.func.sum(models.Match.time), 0) * 600).label(
                "avg"
            ),
            sa.func.jsonb_build_object(
                "encounter_id",
                best_encounter_cte.c.encounter_id,
                "map_name",
                best_encounter_cte.c.map_name,
                "map_image_path",
                best_encounter_cte.c.map_image_path,
                "tournament_name",
                best_encounter_cte.c.tournament_name,
                "username",
                best_encounter_cte.c.username,
            ).label("metadata"),
        )
        .select_from(eligible_stats)
        .join(models.Match, models.Match.id == eligible_stats.c.match_id)
        .join(models.Hero, models.Hero.id == eligible_stats.c.hero_id)
        .join(
            best_encounter_cte,
            sa.and_(
                best_encounter_cte.c.hero_id == eligible_stats.c.hero_id,
                best_encounter_cte.c.name == eligible_stats.c.name,
                best_encounter_cte.c.row_num == 1,
            ),
        )
        .group_by(
            eligible_stats.c.name,
            models.Hero.id,
            best_encounter_cte.c.encounter_id,
            best_encounter_cte.c.map_name,
            best_encounter_cte.c.map_image_path,
            best_encounter_cte.c.tournament_name,
            best_encounter_cte.c.username,
            best_encounter_cte.c.value,
        )
        .order_by(models.Hero.id)
    )

    result_all = await session.execute(query)
    return result_all.all()  # type: ignore


@cache(ttl="1d", key="get_statistics_by_heroes_all_values", prefix="backend:")
async def get_statistics_by_heroes_all_values(
    session: AsyncSession,
) -> typing.Sequence[tuple[enums.LogStatsName, int, float, float, dict]]:
    return await _get_statistics_by_heroes_all_values_impl(session, stats=None)


async def get_statistics_by_heroes_all_values_filtered(
    session: AsyncSession,
    stats: list[enums.LogStatsName],
) -> typing.Sequence[tuple[enums.LogStatsName, int, float, float, dict]]:
    return await _get_statistics_by_heroes_all_values_impl(session, stats=stats)


async def get_best_teammates(
    session: AsyncSession,
    user_id: int,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
) -> tuple[typing.Sequence[tuple[models.User, float, int, float | None, float | None]], int]:
    """
    Retrieves a user's best teammates, including win rate, tournaments played together, and performance statistics.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve best teammates for.
        params: An instance of `PaginationParams` containing pagination parameters.

    Returns:
        A tuple containing:
        1. A sequence of tuples containing:
            - A `User` model instance representing the teammate.
            - The win rate with the user.
            - The number of tournaments played together.
            - The average performance statistic.
            - The average KDA statistic.
        2. The total count of the best teammates.
    """
    self_player = sa.orm.aliased(models.Player, name="self_player")
    teammate_player = sa.orm.aliased(models.Player, name="teammate_player")

    shared_teams_select = (
        sa.select(
            teammate_player.user_id.label("teammate_id"),
            teammate_player.team_id.label("team_id"),
            teammate_player.tournament_id.label("tournament_id"),
        )
        .select_from(self_player)
        .join(teammate_player, teammate_player.team_id == self_player.team_id)
        .where(
            self_player.user_id == user_id,
            self_player.is_substitution.is_(False),
            teammate_player.is_substitution.is_(False),
            teammate_player.user_id != user_id,
        )
        .distinct()
    )

    if workspace_id is not None:
        shared_teams_select = shared_teams_select.join(
            models.Tournament, models.Tournament.id == self_player.tournament_id
        ).where(models.Tournament.workspace_id == workspace_id)

    shared_teams = shared_teams_select.cte("shared_teams")

    teammate_encounters = (
        sa.select(
            shared_teams.c.teammate_id,
            models.Encounter.tournament_id.label("tournament_id"),
            sa.case(
                (models.Encounter.home_team_id == shared_teams.c.team_id, models.Encounter.home_score),
                else_=models.Encounter.away_score,
            ).label("won_score"),
            sa.case(
                (models.Encounter.home_team_id == shared_teams.c.team_id, models.Encounter.away_score),
                else_=models.Encounter.home_score,
            ).label("lost_score"),
        )
        .select_from(shared_teams)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == shared_teams.c.team_id,
                models.Encounter.away_team_id == shared_teams.c.team_id,
            ),
        )
        .cte("teammate_encounters")
    )

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

    stats_query = (
        sa.select(
            shared_teams.c.teammate_id.label("user_id"),
            sa.func.avg(models.MatchStatistics.value)
            .filter(models.MatchStatistics.name == enums.LogStatsName.Performance)
            .label("performance"),
            sa.func.avg(models.MatchStatistics.value)
            .filter(models.MatchStatistics.name == enums.LogStatsName.KDA)
            .label("kda"),
        )
        .select_from(shared_teams)
        .join(teammates_query, teammates_query.c.user_id == shared_teams.c.teammate_id)
        .outerjoin(
            models.MatchStatistics,
            sa.and_(
                models.MatchStatistics.team_id == shared_teams.c.team_id,
                models.MatchStatistics.user_id == shared_teams.c.teammate_id,
                models.MatchStatistics.round == 0,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.name.in_(
                    [
                        enums.LogStatsName.Performance,
                        enums.LogStatsName.KDA,
                    ]
                ),
            ),
        )
        .group_by(shared_teams.c.teammate_id)
    ).cte("stats_query")

    count_query = sa.select(sa.func.count(teammates_query.c.user_id))

    query = (
        sa.select(
            models.User,
            teammates_query.c.winrate,
            teammates_query.c.tournaments,
            stats_query.c.performance,
            stats_query.c.kda,
        )
        .select_from(teammates_query)
        .join(models.User, models.User.id == teammates_query.c.user_id)
        .join(stats_query, stats_query.c.user_id == teammates_query.c.user_id)
    )

    query = params.apply_pagination_sort(query)
    result = await session.execute(query)
    count_result = await session.execute(count_query)
    return result.all(), count_result.scalar_one()  # type: ignore
