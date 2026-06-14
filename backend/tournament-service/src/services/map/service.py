import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from src import models, schemas
from src.core import pagination, utils


def map_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """
    Generates a list of SQLAlchemy loading options for related entities of a map.

    Parameters:
        in_entities (list[str]): A list of entity names to load (e.g., ["gamemode"]).
        child (typing.Any | None): Optional child entity for nested loading.

    Returns:
        list[_AbstractLoad]: A list of SQLAlchemy loading options.
    """
    entities = []
    if "gamemode" in in_entities:
        entities.append(utils.join_entity(child, models.Map.gamemode))

    return entities


async def get(session: AsyncSession, id: int, entities: list[str]) -> models.Map | None:
    """
    Retrieves a map by its ID.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        id (int): The ID of the map to retrieve.
        entities (list[str]): A list of related entities to load (e.g., ["gamemode"]).

    Returns:
        models.Map | None: The Map object if found, otherwise None.
    """
    query = sa.select(models.Map).filter_by(id=id).options(*map_entities(entities))
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_by_name(session: AsyncSession, name: str, entities: list[str]) -> models.Map | None:
    """
    Retrieves a map by its name.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        name (str): The name of the map to retrieve.
        entities (list[str]): A list of related entities to load (e.g., ["gamemode"]).

    Returns:
        models.Map | None: The Map object if found, otherwise None.
    """
    query = sa.select(models.Map).where(sa.and_(models.Map.name == name)).options(*map_entities(entities))
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_by_name_and_gamemode(session: AsyncSession, name: str, gamemode: str) -> models.Map | None:
    """
    Retrieves a map by its name and associated gamemode.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        name (str): The name of the map to retrieve.
        gamemode (str): The name of the gamemode associated with the map.

    Returns:
        models.Map | None: The Map object if found, otherwise None.
    """
    query = (
        sa.select(models.Map)
        .join(models.Gamemode)
        .where(sa.and_(models.Map.name == name, models.Gamemode.name == gamemode))
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_all(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
) -> tuple[typing.Sequence[models.Map], int]:
    """
    Retrieves a paginated list of maps.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (pagination.PaginationSortParams): Pagination and sorting parameters.

    Returns:
        tuple[typing.Sequence[models.Map], int]: A tuple containing:
            - A sequence of Map objects.
            - The total count of maps.
    """
    query = sa.select(models.Map).options(*map_entities(params.entities))
    query = params.apply_pagination_sort(query, models.Map)
    result = await session.execute(query)
    total_query = sa.select(sa.func.count(models.Map.id))
    total_result = await session.execute(total_query)
    return result.scalars().all(), total_result.scalar_one()


async def get_top_maps(
    session: AsyncSession,
    user_id: int,
    params: schemas.UserMapsSearchParams,
    *,
    workspace_id: int | None = None,
) -> tuple[typing.Sequence[tuple[models.Map, int, int, int, int, float]], int]:
    """
    Retrieves a paginated list of top maps for a specific user, including statistics.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        user_id (int): The ID of the user.
        params (pagination.PaginationSortParams): Pagination and sorting parameters.

    Returns:
        tuple[typing.Sequence[tuple[models.Map, int, int, int, float]], int]: A tuple containing:
            - A sequence of tuples, each containing a Map object and its statistics (total matches, won matches, lost matches, draw matches, win rate).
            - The total count of maps.
    """
    home_team_score = sa.case(
        (models.Match.home_team_id == models.Team.id, models.Match.home_score),
        else_=models.Match.away_score,
    )
    away_team_score = sa.case(
        (models.Match.home_team_id == models.Team.id, models.Match.away_score),
        else_=models.Match.home_score,
    )
    home_team_win = sa.case((home_team_score > away_team_score, 1), else_=0)
    away_team_win = sa.case((home_team_score < away_team_score, 1), else_=0)
    draw = sa.case((home_team_score == away_team_score, 1), else_=0)

    subquery_query = (
        sa.select(
            models.Map.id.label("map_id"),
            sa.func.count(models.Match.id).label("count"),
            sa.func.sum(home_team_win).label("win"),
            sa.func.sum(away_team_win).label("loss"),
            sa.func.sum(draw).label("draw"),
            (sa.func.sum(home_team_win) / sa.func.count(models.Match.id)).cast(sa.Numeric(10, 2)).label("winrate"),
        )
        .select_from(models.Match)
        .join(models.Map, models.Map.id == models.Match.map_id)
        .join(
            models.Team,
            sa.or_(
                models.Team.id == models.Match.home_team_id,
                models.Team.id == models.Match.away_team_id,
            ),
        )
        .join(models.Player, models.Player.team_id == models.Team.id)
        .where(sa.and_(models.Player.user_id == user_id))
        .group_by(models.Map.id)
    )

    if params.tournament_id or workspace_id:
        subquery_query = subquery_query.join(models.Encounter, models.Encounter.id == models.Match.encounter_id)

        if params.tournament_id:
            subquery_query = subquery_query.where(models.Encounter.tournament_id == params.tournament_id)

        if workspace_id:
            subquery_query = subquery_query.join(
                models.Tournament, models.Tournament.id == models.Encounter.tournament_id
            ).where(models.Tournament.workspace_id == workspace_id)

    if params.gamemode_id:
        subquery_query = subquery_query.where(sa.and_(models.Map.gamemode_id == params.gamemode_id))

    if params.query:
        fields = params.fields if params.fields else ["name"]
        subquery_query = pagination.apply_search(models.Map, subquery_query, params.query, fields)

    if params.min_count:
        subquery_query = subquery_query.having(sa.func.count(models.Match.id) >= params.min_count)

    subquery = subquery_query.subquery("user_map_stats")

    total_query = sa.select(sa.func.count()).select_from(subquery)

    query = (
        sa.select(
            models.Map,
            subquery.c.count,
            subquery.c.win,
            subquery.c.loss,
            subquery.c.draw,
            subquery.c.winrate,
        )
        .join(subquery, subquery.c.map_id == models.Map.id)
        .options(*map_entities(params.entities))
    )

    query = params.apply_sort(query)
    if params.sort == "winrate":
        query = query.order_by(subquery.c.count.desc())
    query = query.order_by(models.Map.id.asc())
    query = params.apply_pagination(query)

    result = await session.execute(query)
    result_total = await session.execute(total_query)
    return result.all(), result_total.scalar_one()  # type: ignore
