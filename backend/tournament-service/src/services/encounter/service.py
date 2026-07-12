import typing
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.services.tournament_visibility import visible_tournament_ids_subquery
from src import models, schemas
from src.core import enums, pagination, utils
from src.core.workspace import workspace_filter
from src.services.map import service as map_service
from src.services.team import service as team_service
from src.services.tournament import service as tournament_service

hero_jsonb_object = sa.func.jsonb_build_object(
    "id",
    models.Hero.id,
    "created_at",
    models.Hero.created_at,
    "updated_at",
    models.Hero.updated_at,
    "name",
    models.Hero.name,
    "slug",
    models.Hero.slug,
    "image_path",
    models.Hero.image_path,
    "color",
    models.Hero.color,
    "type",
    models.Hero.type,
)


match_jsonb_object = sa.func.jsonb_build_object(
    "id",
    models.Match.id,
    "created_at",
    models.Match.created_at,
    "updated_at",
    models.Match.updated_at,
    "time",
    models.Match.time,
    "home_team_id",
    models.Match.home_team_id,
    "away_team_id",
    models.Match.away_team_id,
    "home_score",
    models.Match.home_score,
    "away_score",
    models.Match.away_score,
    "encounter_id",
    models.Match.encounter_id,
    "map_id",
    models.Match.map_id,
)


def _team_encounter_match_identity(
    row: typing.Sequence[typing.Any],
) -> tuple[int, int, int | None]:
    team, encounter, match, *_ = row
    return team.id, encounter.id, match.id if match is not None else None


def _encounter_match_identity(
    row: typing.Sequence[typing.Any],
) -> tuple[int, int | None]:
    encounter, match, *_ = row
    return encounter.id, match.id if match is not None else None


def encounter_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """
    Generates a list of SQLAlchemy loading options for related entities of an encounter.

    Parameters:
        in_entities (list[str]): A list of entity names to load (e.g., ["tournament", "teams"]).
        child (typing.Any | None): Optional child entity for nested loading.

    Returns:
        list[_AbstractLoad]: A list of SQLAlchemy loading options.
    """
    entities = []
    if "tournament" in in_entities:
        tournament_entity = utils.join_entity(child, models.Encounter.tournament)
        entities.append(tournament_entity)
        entities.extend(
            tournament_service.tournament_entities(utils.prepare_entities(in_entities, "tournament"), tournament_entity)
        )
    if "stage" in in_entities:
        stage_entity = utils.join_entity(child, models.Encounter.stage)
        entities.append(stage_entity)
    if "stage_item" in in_entities:
        stage_item_entity = utils.join_entity(child, models.Encounter.stage_item)
        entities.append(stage_item_entity)
    if "tournament_group" in in_entities:
        entities.append(utils.join_entity(child, models.Encounter.tournament_group))
    if "group" in in_entities:
        entities.append(utils.join_entity(child, models.Encounter.tournament_group))
    include_teams = "teams" in in_entities
    include_home_team = include_teams or "home_team" in in_entities
    include_away_team = include_teams or "away_team" in in_entities
    if include_home_team:
        home_team_entity = utils.join_entity(child, models.Encounter.home_team)
        entities.append(home_team_entity)
        home_team_entities = (
            utils.prepare_entities(in_entities, "teams")
            if include_teams
            else utils.prepare_entities(in_entities, "home_team")
        )
        entities.extend(team_service.team_entities(home_team_entities, home_team_entity))
    if include_away_team:
        away_team_entity = utils.join_entity(child, models.Encounter.away_team)
        entities.append(away_team_entity)
        entities.extend(
            team_service.team_entities(
                (
                    utils.prepare_entities(in_entities, "teams")
                    if include_teams
                    else utils.prepare_entities(in_entities, "away_team")
                ),
                away_team_entity,
            )
        )
    if "matches" in in_entities:
        matches_entity = utils.join_entity(child, models.Encounter.matches)
        entities.append(matches_entity)
        entities.extend(match_entities(utils.prepare_entities(in_entities, "matches"), matches_entity))

    return entities


def match_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """
    Generates a list of SQLAlchemy loading options for related entities of a match.

    Parameters:
        in_entities (list[str]): A list of entity names to load (e.g., ["teams", "map"]).
        child (typing.Any | None): Optional child entity for nested loading.

    Returns:
        list[_AbstractLoad]: A list of SQLAlchemy loading options.
    """
    entities = []

    include_teams = "teams" in in_entities
    include_home_team = include_teams or "home_team" in in_entities
    include_away_team = include_teams or "away_team" in in_entities
    if include_home_team:
        home_team_entity = utils.join_entity(child, models.Match.home_team)
        entities.append(home_team_entity)
        entities.extend(
            team_service.team_entities(
                (
                    utils.prepare_entities(in_entities, "teams")
                    if include_teams
                    else utils.prepare_entities(in_entities, "home_team")
                ),
                home_team_entity,
            )
        )
    if include_away_team:
        away_team_entity = utils.join_entity(child, models.Match.away_team)
        entities.append(away_team_entity)
        entities.extend(
            team_service.team_entities(
                (
                    utils.prepare_entities(in_entities, "teams")
                    if include_teams
                    else utils.prepare_entities(in_entities, "away_team")
                ),
                away_team_entity,
            )
        )
    if "encounter" in in_entities:
        encounter_entity = utils.join_entity(child, models.Match.encounter)
        entities.append(encounter_entity)

        if "encounter.matches" in in_entities:
            in_entities.remove("encounter.matches")

        entities.extend(encounter_entities(utils.prepare_entities(in_entities, "encounter"), encounter_entity))
    if "map" in in_entities:
        map_entity = utils.join_entity(child, models.Match.map)
        entities.append(map_entity)
        entities.extend(map_service.map_entities(utils.prepare_entities(in_entities, "map"), map_entity))
    return entities


def join_encounter_entities(query: sa.Select, in_entities: list[str]) -> sa.Select:
    """
    Joins related entities to an encounter query based on the provided entity list.

    Parameters:
        query (sa.Select): The SQLAlchemy select query.
        in_entities (list[str]): A list of entity names to join (e.g., ["tournament", "group"]).

    Returns:
        sa.Select: The modified query with joins.
    """
    if "tournament" in in_entities:
        query = query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
    if "group" in in_entities:
        query = query.join(
            models.TournamentGroup,
            models.Encounter.tournament_group_id == models.TournamentGroup.id,
        )
    return query


def _coerce_encounter_status(value: str) -> enums.EncounterStatus:
    try:
        return enums.EncounterStatus(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(item.value for item in enums.EncounterStatus)}",
        ) from exc


def _apply_encounter_filters(
    query: sa.Select,
    params: schemas.EncounterSearchParams,
    *,
    workspace_id: int | None = None,
    viewer_auth_user_id: int | None = None,
    joined_tournament: bool = False,
) -> sa.Select:
    if params.query:
        query = params.apply_search(query, models.Encounter)

    if params.tournament_id:
        query = query.where(models.Encounter.tournament_id == params.tournament_id)
    else:
        # Cross-tournament browse: never surface hidden tournaments (issue #115).
        # A specific tournament_id is authorized upstream by assert_tournament_viewable.
        query = query.where(models.Encounter.tournament_id.in_(visible_tournament_ids_subquery(None)))
    if params.stage_id is not None:
        query = query.where(models.Encounter.stage_id == params.stage_id)
    if params.stage_item_id is not None:
        query = query.where(models.Encounter.stage_item_id == params.stage_item_id)
    if params.best_of is not None:
        query = query.where(models.Encounter.best_of == params.best_of)
    if params.status:
        query = query.where(models.Encounter.status == _coerce_encounter_status(params.status))
    if params.has_logs is not None:
        query = query.where(models.Encounter.has_logs.is_(params.has_logs))
    if params.closeness_min is not None:
        query = query.where(models.Encounter.closeness.isnot(None), models.Encounter.closeness >= params.closeness_min)
    if params.closeness_max is not None:
        query = query.where(models.Encounter.closeness.isnot(None), models.Encounter.closeness <= params.closeness_max)

    if workspace_id is not None:
        if not joined_tournament:
            query = query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
            joined_tournament = True
        query = query.where(*workspace_filter(workspace_id))

    if params.scope == "my_team":
        if viewer_auth_user_id is None:
            query = query.where(sa.false())
        else:
            linked_player_ids = sa.select(models.User.id).where(models.User.auth_user_id == viewer_auth_user_id)
            query = query.join(
                models.Player,
                sa.and_(
                    models.Player.tournament_id == models.Encounter.tournament_id,
                    models.Player.workspace_member.has(models.WorkspaceMember.player_id.in_(linked_player_ids)),
                    sa.or_(
                        models.Player.team_id == models.Encounter.home_team_id,
                        models.Player.team_id == models.Encounter.away_team_id,
                    ),
                ),
            )

    return query


def _encounter_ids_query(
    params: schemas.EncounterSearchParams,
    *,
    workspace_id: int | None = None,
    viewer_auth_user_id: int | None = None,
) -> sa.Select:
    query = sa.select(models.Encounter.id)
    query = _apply_encounter_filters(
        query,
        params,
        workspace_id=workspace_id,
        viewer_auth_user_id=viewer_auth_user_id,
    )
    return query.distinct()


def _live_condition(now: datetime) -> sa.ColumnElement[bool]:
    return sa.or_(
        sa.and_(
            models.Encounter.started_at.isnot(None),
            models.Encounter.ended_at.is_(None),
        ),
        sa.and_(
            models.Encounter.status == enums.EncounterStatus.PENDING,
            models.Encounter.current_map_index.isnot(None),
        ),
        sa.and_(
            models.Encounter.status == enums.EncounterStatus.PENDING,
            models.Encounter.scheduled_at <= now,
            models.Encounter.ended_at.is_(None),
        ),
    )


def _upcoming_condition(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        models.Encounter.scheduled_at.isnot(None),
        models.Encounter.scheduled_at > now,
        models.Encounter.status.in_([enums.EncounterStatus.OPEN, enums.EncounterStatus.PENDING]),
    )


async def get_match(
    session: AsyncSession,
    id: int,
    entities: list[str],
    workspace_id: int | None = None,
) -> models.Match | None:
    """
    Retrieves a match by its ID.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        id (int): The ID of the match to retrieve.
        entities (list[str]): A list of related entities to load (e.g., ["teams", "map"]).

    Returns:
        models.Match | None: The Match object if found, otherwise None.
    """
    query = sa.select(models.Match).where(sa.and_(models.Match.id == id)).options(*match_entities(entities))
    if workspace_id is not None:
        query = query.join(models.Encounter, models.Match.encounter_id == models.Encounter.id).join(
            models.Tournament,
            models.Encounter.tournament_id == models.Tournament.id,
        )
        query = query.where(models.Tournament.workspace_id == workspace_id)
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_by_user_with_teams(
    session: AsyncSession, user_id: int, entities: list[str]
) -> typing.Sequence[tuple[models.Encounter, models.Match, int, list[dict]]]:
    """
    Retrieves encounters, matches, and related data for a specific user, including performance and hero data.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        user_id (int): The ID of the user.
        entities (list[str]): A list of related entities to load (e.g., ["teams", "map"]).

    Returns:
        typing.Sequence[tuple[models.Encounter, models.Match, int, list[dict]]]: A sequence of tuples containing encounter, match, performance, and hero data.
    """
    performance_cte = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.value.label("value"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.match_id == models.Match.id,
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.Performance,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
            )
        )
        .cte("performance_cte")
    )

    heroes_cte = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            sa.func.jsonb_agg(hero_jsonb_object).label("value"),
        )
        .select_from(models.MatchStatistics)
        .join(models.Hero, models.MatchStatistics.hero_id == models.Hero.id)
        .where(
            sa.and_(
                models.MatchStatistics.match_id == models.Match.id,
                models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.hero_id.isnot(None),
                models.MatchStatistics.value > 60,
                models.MatchStatistics.round == 0,
            )
        )
        .group_by(models.MatchStatistics.match_id)
        .cte("heroes_cte")
    )

    query = (
        sa.select(
            models.Team,
            models.Encounter,
            models.Match,
            performance_cte.c.value.label("performance"),
            heroes_cte.c.value.label("heroes"),
        )
        .select_from(models.Player)
        .options(*match_entities(entities))
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Player.team_id,
                models.Encounter.away_team_id == models.Player.team_id,
            ),
        )
        .join(models.Team, models.Player.team_id == models.Team.id)
        .join(models.Match, models.Encounter.id == models.Match.encounter_id, isouter=True)
        .outerjoin(performance_cte, performance_cte.c.match_id == models.Match.id)
        .outerjoin(heroes_cte, heroes_cte.c.match_id == models.Match.id)
        .where(
            sa.and_(
                models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id),
                models.Player.is_substitution.is_(False),
            )
        )
        .order_by(models.Team.id, models.Encounter.id)
    )

    result = await session.execute(query)
    return result.unique(_team_encounter_match_identity).all()  # type: ignore


async def get_by_user(
    session: AsyncSession, user_id: int, params: pagination.PaginationSortParams, workspace_id: int | None = None
) -> tuple[typing.Sequence[tuple[models.Encounter, models.Match, int, list[dict]]], int]:
    """
    Retrieves paginated encounters, matches, and related data for a specific user.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        user_id (int): The ID of the user.
        params (pagination.PaginationSortParams): Pagination and sorting parameters.

    Returns:
        tuple[typing.Sequence[tuple[models.Encounter, models.Match, int, list[dict]]], int]: A tuple containing:
            - A sequence of tuples containing encounter, match, performance, and hero data.
            - The total count of encounters.
    """
    total_query = (
        sa.select(sa.func.count(models.Encounter.id))
        .join(
            models.Player,
            sa.or_(
                models.Encounter.home_team_id == models.Player.team_id,
                models.Encounter.away_team_id == models.Player.team_id,
            ),
        )
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
        .where(sa.and_(models.WorkspaceMember.player_id == user_id))
    )

    encounters_query = (
        sa.select(
            models.Encounter,
            models.Player.id.label("player_id"),
        )
        .select_from(models.Player)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Player.team_id,
                models.Encounter.away_team_id == models.Player.team_id,
            ),
        )
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
        .where(sa.and_(models.WorkspaceMember.player_id == user_id))
    )

    if workspace_id is not None:
        total_query = total_query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id).where(
            *workspace_filter(workspace_id)
        )
        encounters_query = encounters_query.join(
            models.Tournament, models.Encounter.tournament_id == models.Tournament.id
        ).where(*workspace_filter(workspace_id))

    encounters_query = params.apply_pagination_sort(encounters_query)
    encounters_query = encounters_query.subquery()

    performance_cte = (
        sa.select(
            models.MatchStatistics.match_id,
            models.MatchStatistics.value.label("performance"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.Performance,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
            )
        )
        .cte("performance_cte")
    )

    heroes_cte = (
        sa.select(
            models.MatchStatistics.match_id,
            sa.func.jsonb_agg(hero_jsonb_object).label("heroes"),
        )
        .join(models.Hero, models.MatchStatistics.hero_id == models.Hero.id)
        .where(
            sa.and_(
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
                models.MatchStatistics.hero_id.isnot(None),
                models.MatchStatistics.value > 60,
                models.MatchStatistics.round == 0,
            )
        )
        .group_by(models.MatchStatistics.match_id)
        .cte("heroes_cte")
    )

    query = (
        sa.select(
            models.Encounter,
            models.Match,
            performance_cte.c.performance,
            heroes_cte.c.heroes,
        )
        .select_from(encounters_query)
        .options(*[*match_entities(params.entities), *encounter_entities(params.entities)])
        .join(models.Encounter, encounters_query.c.id == models.Encounter.id)
        .join(models.Match, models.Encounter.id == models.Match.encounter_id, isouter=True)
        .join(performance_cte, performance_cte.c.match_id == models.Match.id, isouter=True)
        .join(heroes_cte, heroes_cte.c.match_id == models.Match.id, isouter=True)
    )
    query = params.apply_sort(query)
    result = await session.execute(query)
    total_result = await session.execute(total_query)
    return result.unique(_encounter_match_identity).all(), total_result.scalar_one()  # type: ignore


async def get_encounter(session: AsyncSession, id: int, entities: list[str]) -> models.Encounter | None:
    """
    Retrieves an encounter by its ID.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        id (int): The ID of the encounter to retrieve.
        entities (list[str]): A list of related entities to load (e.g., ["tournament", "teams"]).

    Returns:
        models.Encounter | None: The Encounter object if found, otherwise None.
    """
    query = sa.select(models.Encounter).options(*encounter_entities(entities)).where(sa.and_(models.Encounter.id == id))
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_all_encounters(
    session: AsyncSession,
    params: schemas.EncounterSearchParams,
    workspace_id: int | None = None,
    viewer_auth_user_id: int | None = None,
) -> tuple[typing.Sequence[models.Encounter], int]:
    """
    Retrieves a paginated list of encounters based on search parameters.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (schemas.EncounterSearchParams): Search, pagination, and sorting parameters.
        workspace_id (int | None): Optional workspace ID to filter encounters.

    Returns:
        tuple[typing.Sequence[models.Encounter], int]: A tuple containing:
            - A sequence of Encounter objects.
            - The total count of encounters.
    """
    query = sa.select(models.Encounter).options(*encounter_entities(params.entities))
    total_query = sa.select(sa.func.count(sa.distinct(models.Encounter.id)))
    query = join_encounter_entities(query, params.entities)
    total_query = join_encounter_entities(total_query, params.entities)

    query = _apply_encounter_filters(
        query,
        params,
        workspace_id=workspace_id,
        viewer_auth_user_id=viewer_auth_user_id,
        joined_tournament="tournament" in params.entities,
    )
    total_query = _apply_encounter_filters(
        total_query,
        params,
        workspace_id=workspace_id,
        viewer_auth_user_id=viewer_auth_user_id,
        joined_tournament="tournament" in params.entities,
    )

    query = params.apply_pagination_sort(query)

    result = await session.execute(query)
    result_total = await session.execute(total_query)
    return result.unique().scalars().all(), result_total.scalar_one()


async def get_saved_views(
    session: AsyncSession,
    *,
    workspace_id: int,
    auth_user_id: int,
) -> typing.Sequence[models.EncounterSavedView]:
    result = await session.execute(
        sa.select(models.EncounterSavedView)
        .where(
            models.EncounterSavedView.workspace_id == workspace_id,
            models.EncounterSavedView.auth_user_id == auth_user_id,
        )
        .order_by(models.EncounterSavedView.sort_order.asc(), models.EncounterSavedView.created_at.asc())
    )
    return result.scalars().all()


async def upsert_saved_view(
    session: AsyncSession,
    *,
    workspace_id: int,
    auth_user_id: int,
    name: str,
    filters: dict,
) -> models.EncounterSavedView:
    result = await session.execute(
        sa.select(models.EncounterSavedView).where(
            models.EncounterSavedView.workspace_id == workspace_id,
            models.EncounterSavedView.auth_user_id == auth_user_id,
            models.EncounterSavedView.name == name,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.filters_json = filters
        await session.commit()
        await session.refresh(existing)
        return existing

    sort_order = await session.scalar(
        sa.select(sa.func.coalesce(sa.func.max(models.EncounterSavedView.sort_order), -1) + 1).where(
            models.EncounterSavedView.workspace_id == workspace_id,
            models.EncounterSavedView.auth_user_id == auth_user_id,
        )
    )
    saved_view = models.EncounterSavedView(
        workspace_id=workspace_id,
        auth_user_id=auth_user_id,
        name=name,
        filters_json=filters,
        sort_order=int(sort_order or 0),
    )
    session.add(saved_view)
    await session.commit()
    await session.refresh(saved_view)
    return saved_view


async def delete_saved_view(
    session: AsyncSession,
    *,
    workspace_id: int,
    auth_user_id: int,
    saved_view_id: int,
) -> None:
    result = await session.execute(
        sa.select(models.EncounterSavedView).where(
            models.EncounterSavedView.id == saved_view_id,
            models.EncounterSavedView.workspace_id == workspace_id,
            models.EncounterSavedView.auth_user_id == auth_user_id,
        )
    )
    saved_view = result.scalar_one_or_none()
    if saved_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved view not found")
    await session.delete(saved_view)
    await session.commit()


async def get_overview_data(
    session: AsyncSession,
    params: schemas.EncounterSearchParams,
    *,
    workspace_id: int | None = None,
    viewer_auth_user_id: int | None = None,
) -> dict[str, typing.Any]:
    now = datetime.now(UTC)
    recent_since = now - timedelta(days=7)
    base_ids = _encounter_ids_query(
        replace(params, page=1, per_page=-1),
        workspace_id=workspace_id,
        viewer_auth_user_id=viewer_auth_user_id,
    ).subquery()

    def encounter_base() -> sa.Select:
        return sa.select(models.Encounter).join(base_ids, base_ids.c.id == models.Encounter.id)

    async def scalar_int(query: sa.Select) -> int:
        value = await session.scalar(query)
        return int(value or 0)

    # All same-shape scalar aggregates over `Encounter JOIN base_ids` are
    # consolidated into ONE statement via `count(*) FILTER (WHERE ...)` — the
    # base_ids subquery (which re-evaluates the full search filter) would
    # otherwise run once per aggregate (this endpoint used to issue 22
    # sequential round trips per cache miss).
    completed = models.Encounter.status == enums.EncounterStatus.COMPLETED
    agg = (
        await session.execute(
            sa.select(
                sa.func.count().label("total"),
                sa.func.count().filter(models.Encounter.has_logs.is_(True)).label("with_logs"),
                sa.func.count().filter(models.Encounter.created_at >= recent_since).label("recent"),
                sa.func.count().filter(_live_condition(now)).label("live_now"),
                sa.func.count().filter(_upcoming_condition(now)).label("upcoming"),
                # avg() ignores NULL closeness natively.
                sa.func.avg(models.Encounter.closeness).label("avg_closeness"),
                sa.func.count().filter(completed).label("completed_series"),
                sa.func.count()
                .filter(
                    completed,
                    sa.or_(models.Encounter.home_score == 0, models.Encounter.away_score == 0),
                    models.Encounter.home_score != models.Encounter.away_score,
                )
                .label("sweeps"),
                sa.func.count()
                .filter(
                    completed,
                    models.Encounter.home_score + models.Encounter.away_score == models.Encounter.best_of,
                )
                .label("went_distance"),
                sa.func.count()
                .filter(completed, models.Encounter.home_score > models.Encounter.away_score)
                .label("home_wins"),
                sa.func.count()
                .filter(completed, models.Encounter.away_score > models.Encounter.home_score)
                .label("away_wins"),
                sa.func.count()
                .filter(models.Encounter.best_of >= 5, models.Encounter.closeness >= 0.6)
                .label("close_bo5"),
            )
            .select_from(models.Encounter)
            .join(base_ids, base_ids.c.id == models.Encounter.id)
        )
    ).one()

    total = int(agg.total or 0)
    with_logs_count = int(agg.with_logs or 0)
    recent_count = int(agg.recent or 0)
    live_now_count = int(agg.live_now or 0)
    upcoming_count = int(agg.upcoming or 0)
    avg_closeness = agg.avg_closeness
    completed_series_count = int(agg.completed_series or 0)
    sweep_count = int(agg.sweeps or 0)
    went_distance_count = int(agg.went_distance or 0)
    home_wins = int(agg.home_wins or 0)
    away_wins = int(agg.away_wins or 0)
    close_bo5_count = int(agg.close_bo5 or 0)

    bucket_expr = sa.case(
        (models.Encounter.closeness >= 1, 9),
        else_=sa.func.floor(models.Encounter.closeness * 10),
    ).label("bucket")
    histogram_rows = await session.execute(
        sa.select(bucket_expr, sa.func.count(models.Encounter.id))
        .join(base_ids, base_ids.c.id == models.Encounter.id)
        .where(models.Encounter.closeness.isnot(None))
        .group_by(bucket_expr)
    )

    score_rows = await session.execute(
        sa.select(models.Encounter.home_score, models.Encounter.away_score, sa.func.count(models.Encounter.id))
        .join(base_ids, base_ids.c.id == models.Encounter.id)
        .where(models.Encounter.status == enums.EncounterStatus.COMPLETED)
        .group_by(models.Encounter.home_score, models.Encounter.away_score)
    )

    stage_name = sa.func.coalesce(models.StageItem.name, models.Stage.name, "Unassigned").label("stage_name")
    stage_rows = await session.execute(
        sa.select(stage_name, sa.func.count(models.Encounter.id))
        .select_from(models.Encounter)
        .join(base_ids, base_ids.c.id == models.Encounter.id)
        .outerjoin(models.Stage, models.Encounter.stage_id == models.Stage.id)
        .outerjoin(models.StageItem, models.Encounter.stage_item_id == models.StageItem.id)
        .group_by(stage_name)
        .order_by(sa.func.count(models.Encounter.id).desc())
    )

    hot_map_rows = await session.execute(
        sa.select(models.Map.name, sa.func.count(models.Match.id))
        .select_from(models.Match)
        .join(base_ids, base_ids.c.id == models.Match.encounter_id)
        .join(models.Map, models.Match.map_id == models.Map.id)
        .group_by(models.Map.name)
        .order_by(sa.func.count(models.Match.id).desc())
        .limit(6)
    )

    duration_by_encounter = (
        sa.select(models.Match.encounter_id.label("encounter_id"), sa.func.sum(models.Match.time).label("seconds"))
        .join(base_ids, base_ids.c.id == models.Match.encounter_id)
        .group_by(models.Match.encounter_id)
        .subquery()
    )
    avg_series_seconds = await session.scalar(sa.select(sa.func.avg(duration_by_encounter.c.seconds)))

    closest_rows = await session.execute(
        encounter_base()
        .where(models.Encounter.closeness.isnot(None))
        .options(
            *encounter_entities(
                ["tournament", "stage", "stage_item", "home_team", "away_team", "matches", "matches.map"]
            )
        )
        .order_by(
            models.Encounter.closeness.desc(),
            models.Encounter.updated_at.desc().nullslast(),
            models.Encounter.id.desc(),
        )
        .limit(4)
    )
    upcoming_rows = await session.execute(
        encounter_base()
        .where(_upcoming_condition(now))
        .options(
            *encounter_entities(
                ["tournament", "stage", "stage_item", "home_team", "away_team", "matches", "matches.map"]
            )
        )
        .order_by(models.Encounter.scheduled_at.asc(), models.Encounter.id.desc())
        .limit(4)
    )
    live_rows = await session.execute(
        encounter_base()
        .where(_live_condition(now))
        .options(
            *encounter_entities(
                ["tournament", "stage", "stage_item", "home_team", "away_team", "matches", "matches.map"]
            )
        )
        .order_by(models.Encounter.started_at.desc().nullslast(), models.Encounter.id.desc())
        .limit(4)
    )

    finals_count = await scalar_int(
        sa.select(sa.func.count(sa.distinct(models.Encounter.id)))
        .select_from(models.Encounter)
        .join(base_ids, base_ids.c.id == models.Encounter.id)
        .outerjoin(models.Stage, models.Encounter.stage_id == models.Stage.id)
        .outerjoin(models.StageItem, models.Encounter.stage_item_id == models.StageItem.id)
        .where(sa.or_(models.Stage.name.ilike("%final%"), models.StageItem.name.ilike("%final%")))
    )
    home_standing = aliased(models.Standing)
    away_standing = aliased(models.Standing)
    upset_count = await scalar_int(
        sa.select(sa.func.count(sa.distinct(models.Encounter.id)))
        .select_from(models.Encounter)
        .join(base_ids, base_ids.c.id == models.Encounter.id)
        .join(
            home_standing,
            sa.and_(
                home_standing.tournament_id == models.Encounter.tournament_id,
                home_standing.team_id == models.Encounter.home_team_id,
                home_standing.stage_id == models.Encounter.stage_id,
                home_standing.stage_item_id == models.Encounter.stage_item_id,
            ),
        )
        .join(
            away_standing,
            sa.and_(
                away_standing.tournament_id == models.Encounter.tournament_id,
                away_standing.team_id == models.Encounter.away_team_id,
                away_standing.stage_id == models.Encounter.stage_id,
                away_standing.stage_item_id == models.Encounter.stage_item_id,
            ),
        )
        .where(
            models.Encounter.status == enums.EncounterStatus.COMPLETED,
            sa.or_(
                sa.and_(
                    models.Encounter.home_score > models.Encounter.away_score,
                    home_standing.position > away_standing.position,
                ),
                sa.and_(
                    models.Encounter.away_score > models.Encounter.home_score,
                    away_standing.position > home_standing.position,
                ),
            ),
        )
    )
    my_team_count = 0
    if viewer_auth_user_id is not None:
        my_team_ids = _encounter_ids_query(
            replace(params, page=1, per_page=-1, scope="my_team"),
            workspace_id=workspace_id,
            viewer_auth_user_id=viewer_auth_user_id,
        ).subquery()
        my_team_count = await scalar_int(sa.select(sa.func.count()).select_from(my_team_ids))

    return {
        "total": total,
        "recent_count": recent_count,
        "with_logs_count": with_logs_count,
        "avg_closeness": float(avg_closeness) if avg_closeness is not None else None,
        "live_now_count": live_now_count,
        "upcoming_count": upcoming_count,
        "histogram_rows": list(histogram_rows.all()),
        "score_rows": list(score_rows.all()),
        "stage_rows": list(stage_rows.all()),
        "hot_map_rows": list(hot_map_rows.all()),
        "avg_series_seconds": float(avg_series_seconds) if avg_series_seconds is not None else None,
        "completed_series_count": completed_series_count,
        "sweep_count": sweep_count,
        "went_distance_count": went_distance_count,
        "home_wins": home_wins,
        "away_wins": away_wins,
        "closest": closest_rows.unique().scalars().all(),
        "upcoming": upcoming_rows.unique().scalars().all(),
        "live": live_rows.unique().scalars().all(),
        "preset_counts": {
            "all": total,
            "my_team": my_team_count,
            "finals": finals_count,
            "close_bo5": close_bo5_count,
            "upsets": upset_count,
            "with_logs": with_logs_count,
        },
    }


async def get_match_stats_for_user(
    session: AsyncSession, match_id: int, user_id: int
) -> tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]:
    """
    Retrieves match statistics and hero data for a specific user.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        match_id (int): The ID of the match.
        user_id (int): The ID of the user.

    Returns:
        tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]: A tuple containing:
            - A dictionary of round-based statistics.
            - A dictionary of round-based hero data.
    """
    query = (
        sa.select(
            models.MatchStatistics.round,
            models.MatchStatistics.name,
            sa.func.sum(models.MatchStatistics.value).cast(sa.Numeric(10, 2)).label("value"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.match_id == match_id,
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.hero_id.is_(None),
            )
        )
        .group_by(models.MatchStatistics.name, models.MatchStatistics.round)
    )

    heroes_round = (
        sa.select(models.MatchStatistics.round, sa.func.jsonb_agg(hero_jsonb_object))
        .select_from(models.MatchStatistics)
        .join(models.Hero, models.MatchStatistics.hero_id == models.Hero.id)
        .where(
            sa.and_(
                models.MatchStatistics.match_id == match_id,
                models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.hero_id.isnot(None),
                models.MatchStatistics.value > 60,
            )
        )
        .group_by(models.MatchStatistics.round)
    )

    stats_result = await session.execute(query)
    heroes_result = await session.execute(heroes_round)

    stats_out: dict[int, dict[enums.LogStatsName, int]] = {}
    heroes_out: dict[int, list[dict]] = {}

    for match_round, name, value in stats_result.all():
        stats_out.setdefault(match_round, {})[name] = value

    for match_round, value in heroes_result.all():
        heroes_out[match_round] = value

    return stats_out, heroes_out


async def get_match_stats_for_users(
    session: AsyncSession, match_id: int, user_ids: list[int]
) -> dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]]:
    """Batched variant of :func:`get_match_stats_for_user` for a full roster.

    Runs the same two aggregate queries once with ``user_id IN (...)`` instead
    of 2×N round trips when serializing a match page (the hottest public read).
    Users without rows are still present in the result with empty dicts.
    """
    out: dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]] = {
        user_id: ({}, {}) for user_id in user_ids
    }
    if not user_ids:
        return out

    query = (
        sa.select(
            models.MatchStatistics.user_id,
            models.MatchStatistics.round,
            models.MatchStatistics.name,
            sa.func.sum(models.MatchStatistics.value).cast(sa.Numeric(10, 2)).label("value"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.match_id == match_id,
                models.MatchStatistics.user_id.in_(user_ids),
                models.MatchStatistics.hero_id.is_(None),
            )
        )
        .group_by(models.MatchStatistics.user_id, models.MatchStatistics.name, models.MatchStatistics.round)
    )

    heroes_round = (
        sa.select(
            models.MatchStatistics.user_id,
            models.MatchStatistics.round,
            sa.func.jsonb_agg(hero_jsonb_object),
        )
        .select_from(models.MatchStatistics)
        .join(models.Hero, models.MatchStatistics.hero_id == models.Hero.id)
        .where(
            sa.and_(
                models.MatchStatistics.match_id == match_id,
                models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
                models.MatchStatistics.user_id.in_(user_ids),
                models.MatchStatistics.hero_id.isnot(None),
                models.MatchStatistics.value > 60,
            )
        )
        .group_by(models.MatchStatistics.user_id, models.MatchStatistics.round)
    )

    stats_result = await session.execute(query)
    heroes_result = await session.execute(heroes_round)

    for user_id, match_round, name, value in stats_result.all():
        out[user_id][0].setdefault(match_round, {})[name] = value

    for user_id, match_round, value in heroes_result.all():
        out[user_id][1][match_round] = value

    return out


async def get_match_kill_feed(
    session: AsyncSession,
    match_id: int,
) -> tuple[list[typing.Any], list[typing.Any]]:
    """Raw kill-feed + timeline-event rows for one match, ordered chronologically.

    Returns ``(kill_rows, event_rows)`` where each kill row is
    ``(MatchKillFeed, killer_hero, victim_hero)`` and each event row is
    ``(MatchEvent, hero | None)``. The hero *at event time* is joined (it can
    differ from the aggregate roster hero); player names are resolved by the
    caller/client from the roster to keep the payload lean. Only timeline-worthy
    events (ultimate casts, resurrects) are returned — per-hit assists are
    already surfaced as aggregate stats.
    """
    killer_hero = aliased(models.Hero)
    victim_hero = aliased(models.Hero)
    kf = models.MatchKillFeed

    kills_query = (
        sa.select(kf, killer_hero, victim_hero)
        .join(killer_hero, killer_hero.id == kf.killer_hero_id)
        .join(victim_hero, victim_hero.id == kf.victim_hero_id)
        .where(kf.match_id == match_id)
        .order_by(kf.round.asc(), kf.time.asc(), kf.id.asc())
    )

    ev = models.MatchEvent
    timeline_events = (
        enums.MatchEvent.UltimateStart,
        enums.MatchEvent.UltimateEnd,
        enums.MatchEvent.MercyRez,
    )
    events_query = (
        sa.select(ev, models.Hero)
        .outerjoin(models.Hero, models.Hero.id == ev.hero_id)
        .where(sa.and_(ev.match_id == match_id, ev.name.in_(timeline_events)))
        .order_by(ev.round.asc(), ev.time.asc(), ev.id.asc())
    )

    kill_rows = (await session.execute(kills_query)).all()
    event_rows = (await session.execute(events_query)).all()
    return list(kill_rows), list(event_rows)


async def get_by_stage_id(
    session: AsyncSession,
    tournament_id: int,
    stage_id: int,
    entities: list[str],
) -> typing.Sequence[models.Encounter]:
    query = (
        sa.select(models.Encounter)
        .options(*encounter_entities(entities))
        .where(
            sa.and_(
                models.Encounter.tournament_id == tournament_id,
                models.Encounter.stage_id == stage_id,
            )
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_all_matches(
    session: AsyncSession, params: schemas.MatchSearchParams, workspace_id: int | None = None
) -> tuple[typing.Sequence[models.Match], int]:
    """
    Retrieves a paginated list of matches based on search parameters.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (schemas.MatchSearchParams): Search, pagination, and sorting parameters.

    Returns:
        tuple[typing.Sequence[models.Match], int]: A tuple containing:
            - A sequence of Match objects.
            - The total count of matches.
    """
    query = sa.select(models.Match).options(*match_entities(params.entities))
    total_query = sa.select(sa.func.count(models.Match.id))
    if params.query:
        query = params.apply_search(query, models.Match)
        total_query = params.apply_search(total_query, models.Match)

    encounter_joined: bool = False

    if params.tournament_id:
        encounter_joined = True
        query = query.join(models.Encounter, models.Match.encounter_id == models.Encounter.id).where(
            sa.and_(models.Encounter.tournament_id == params.tournament_id)
        )
        total_query = total_query.join(models.Encounter, models.Match.encounter_id == models.Encounter.id).where(
            sa.and_(models.Encounter.tournament_id == params.tournament_id)
        )
    else:
        # Cross-tournament browse: exclude matches of hidden tournaments (issue #115).
        _visible_encounter_ids = sa.select(models.Encounter.id).where(
            models.Encounter.tournament_id.in_(visible_tournament_ids_subquery(None))
        )
        query = query.where(models.Match.encounter_id.in_(_visible_encounter_ids))
        total_query = total_query.where(models.Match.encounter_id.in_(_visible_encounter_ids))

    if params.home_team_id:
        if not encounter_joined:
            query = query.join(models.Encounter, models.Match.encounter_id == models.Encounter.id)
            total_query = total_query.join(models.Encounter, models.Match.encounter_id == models.Encounter.id)

        query = query.where(sa.and_(models.Match.home_team_id == params.home_team_id))
        total_query = total_query.where(sa.and_(models.Match.home_team_id == params.home_team_id))

    if params.away_team_id:
        if not encounter_joined:
            query = query.join(models.Encounter, models.Match.encounter_id == models.Encounter.id)
            total_query = total_query.join(models.Encounter, models.Match.encounter_id == models.Encounter.id)

        query = query.where(sa.and_(models.Match.away_team_id == params.away_team_id))
        total_query = total_query.where(sa.and_(models.Match.away_team_id == params.away_team_id))

    if workspace_id is not None:
        if not encounter_joined:
            query = query.join(models.Encounter, models.Match.encounter_id == models.Encounter.id)
            total_query = total_query.join(models.Encounter, models.Match.encounter_id == models.Encounter.id)
        query = query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
        total_query = total_query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
        query = query.where(models.Tournament.workspace_id == workspace_id)
        total_query = total_query.where(models.Tournament.workspace_id == workspace_id)

    query = params.apply_pagination_sort(query, models.Match)

    result = await session.execute(query)
    result_total = await session.execute(total_query)
    return result.unique().scalars().all(), result_total.scalar_one()


async def get_match_bulk(
    session: AsyncSession, matches_id: list[int], entities: list[str]
) -> typing.Sequence[models.Match]:
    """
    Retrieves a list of matches by their IDs.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        matches_id (list[int]): A list of match IDs to retrieve.
        entities (list[str]): A list of related entities to load (e.g., ["teams", "map"]).

    Returns:
        typing.Sequence[models.Match]: A sequence of Match objects.
    """
    query = sa.select(models.Match).where(models.Match.id.in_(matches_id)).options(*match_entities(entities))
    result = await session.execute(query)
    return result.unique().scalars().all()
