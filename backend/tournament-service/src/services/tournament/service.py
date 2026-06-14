import re
import typing
from collections import defaultdict
from itertools import combinations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from src import models, schemas
from src.core import enums, utils

OWAL_SEASON_PATTERN = re.compile(r"^OWAL Season (\d+)$")


def _parse_owal_season_name(tournament_name: str) -> tuple[int, str] | None:
    season_name = tournament_name.split(" | ", 1)[0].strip()
    match = OWAL_SEASON_PATTERN.match(season_name)
    if not match:
        return None
    return int(match.group(1)), season_name


def tournament_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """
    Constructs a list of SQLAlchemy load options for querying related entities of a `Tournament` model.

    Args:
        in_entities: A list of strings representing the names of related entities to load.
        child: An optional SQLAlchemy relationship or join entity to chain the load options.

    Returns:
        A list of SQLAlchemy load options (`_AbstractLoad`) for the specified entities.
    """
    entities = []
    if "groups" in in_entities:
        entities.append(utils.join_entity(child, models.Tournament.groups))
    if "stages" in in_entities:
        stage_entity = child.selectinload(models.Tournament.stages) if child else selectinload(models.Tournament.stages)
        entities.append(stage_entity)
    if "division_grid_version" in in_entities:
        entities.append(utils.join_entity(child, models.Tournament.division_grid_version))
    return entities


async def get(session: AsyncSession, id: int, entities: list[str]) -> models.Tournament | None:
    """
    Retrieves a `Tournament` model instance by its ID, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        id: The ID of the tournament to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `Tournament` model instance if found, otherwise `None`.
    """
    query = (
        sa.select(models.Tournament).where(sa.and_(models.Tournament.id == id)).options(*tournament_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_group(session: AsyncSession, id: int, entities: list[str]) -> models.TournamentGroup | None:
    """
    Retrieves a `TournamentGroup` model instance by its ID.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        id: The ID of the tournament group to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `TournamentGroup` model instance if found, otherwise `None`.
    """
    query = sa.select(models.TournamentGroup).where(sa.and_(models.TournamentGroup.id == id))
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_by_number_and_league(
    session: AsyncSession, number: int, is_league: bool, entities: list[str]
) -> models.Tournament | None:
    """
    Retrieves a `Tournament` model instance by its number and league status, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        number: The number of the tournament to retrieve.
        is_league: Whether the tournament is a league.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `Tournament` model instance if found, otherwise `None`.
    """
    query = (
        sa.select(models.Tournament)
        .where(
            sa.and_(
                models.Tournament.number == number,
                models.Tournament.is_league == is_league,
            )
        )
        .options(*tournament_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_all(
    session: AsyncSession, params: schemas.TournamentPaginationSortSearchParams
) -> tuple[typing.Sequence[models.Tournament], int]:
    """
    Retrieves a paginated list of `Tournament` model instances based on filtering and sorting parameters.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        params: An instance of `SearchPaginationParams` containing pagination, sorting, and filtering parameters.

    Returns:
        A tuple containing:
        1. A sequence of `Tournament` model instances.
        2. The total count of tournaments matching the filtering criteria.
    """
    query = sa.select(models.Tournament).options(*tournament_entities(params.entities))
    total_query = sa.select(sa.func.count(models.Tournament.id))
    query = params.apply_pagination_sort(query, models.Tournament)
    query = params.apply_search(query, models.Tournament)
    total_query = params.apply_search(total_query, models.Tournament)

    if params.is_league is not None:
        query = query.where(models.Tournament.is_league.is_(params.is_league))
        total_query = total_query.where(models.Tournament.is_league.is_(params.is_league))

    if params.workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == params.workspace_id)
        total_query = total_query.where(models.Tournament.workspace_id == params.workspace_id)

    result = await session.execute(query)
    total_result = await session.execute(total_query)
    return result.unique().scalars().all(), total_result.scalar_one()


async def get_history_tournaments(
    session: AsyncSession,
    workspace_id: int | None = None,
) -> typing.Sequence[tuple[models.Tournament, int, float, float]]:
    """
    Retrieves historical statistics for tournaments, including player count, average SR, and average closeness.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.

    Returns:
        A sequence of tuples containing:
        1. A `Tournament` model instance.
        2. The number of players in the tournament.
        3. The average SR of teams in the tournament.
        4. The average closeness of encounters in the tournament.
    """
    players_count = (
        (
            sa.select(sa.func.count(models.Player.user_id)).where(
                models.Player.tournament_id == models.Tournament.id,
                models.Tournament.number.isnot(None),
            )
        )
        .scalar_subquery()
        .correlate(models.Tournament)
    )

    avg_sr = (
        (
            sa.select(sa.func.avg(models.Team.avg_sr)).where(
                models.Team.tournament_id == models.Tournament.id,
                models.Tournament.number.isnot(None),
            )
        )
        .scalar_subquery()
        .correlate(models.Tournament)
    )

    avg_closeness = (
        (
            sa.select(sa.func.avg(models.Encounter.closeness)).where(
                models.Encounter.tournament_id == models.Tournament.id,
                models.Tournament.number.isnot(None),
            )
        )
        .scalar_subquery()
        .correlate(models.Tournament)
    )

    query = (
        sa.select(models.Tournament, players_count, avg_sr, avg_closeness)
        .where(models.Tournament.number.isnot(None))
        .group_by(models.Tournament.id)
        .order_by(models.Tournament.number)
    )
    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)
    result = await session.execute(query)
    return result.all()  # type: ignore


async def get_avg_div_tournaments(
    session: AsyncSession,
    workspace_id: int | None = None,
) -> typing.Sequence[tuple[models.Tournament, enums.HeroClass, int]]:
    """
    Retrieves raw player rank data for computing per-tournament division averages.

    Returns (tournament, role, rank) rows. Division computation and normalization
    to the target grid is done in the flow layer using DivisionGridNormalizer so
    that each tournament's own division_grid_version is respected.

    Returns:
        A sequence of tuples containing:
        1. A `Tournament` model instance (with division_grid_version_id available).
        2. The role (e.g., tank, damage, support).
        3. The player's raw rank.
    """
    query = (
        sa.select(models.Tournament, models.Player.role, models.Player.rank)
        .where(
            models.Player.tournament_id == models.Tournament.id,
            models.Tournament.number.isnot(None),
        )
        .order_by(models.Tournament.number)
    )
    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)
    result = await session.execute(query)
    return result.all()  # type: ignore


async def get_tournaments_overall(session: AsyncSession, workspace_id: int | None = None) -> tuple[int, int, int, int]:
    """
    Retrieves overall statistics for tournaments, including counts of tournaments, teams, players, and champions.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.

    Returns:
        A tuple containing:
        1. The total number of tournaments.
        2. The total number of teams.
        3. The total number of players.
        4. The total number of champions.
    """
    ws_filters = []
    if workspace_id is not None:
        ws_filters.append(models.Tournament.workspace_id == workspace_id)

    tournaments_count_query = sa.select(sa.func.count(models.Tournament.id)).where(
        models.Tournament.is_league.is_(False), *ws_filters
    )

    teams_count_query = (
        sa.select(sa.func.count(models.Team.id))
        .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
        .where(models.Tournament.is_league.is_(False), *ws_filters)
    )

    players_count_query = (
        sa.select(sa.func.count(sa.distinct(models.Player.user_id)))
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(models.Tournament.is_league.is_(False), *ws_filters)
    )

    champions_count_query = (
        sa.select(sa.func.count(models.Player.user_id.distinct()))
        .select_from(models.Player)
        .join(models.Standing, models.Standing.team_id == models.Player.team_id)
        .join(
            models.TournamentGroup,
            models.TournamentGroup.id == models.Standing.group_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            sa.and_(
                models.Standing.overall_position == 1,
                models.TournamentGroup.is_groups.is_(False),
                models.Player.is_substitution.is_(False),
                models.Tournament.is_league.is_(False),
                *ws_filters,
            )
        )
    )
    tournaments_count_result = await session.execute(tournaments_count_query)
    teams_count_result = await session.execute(teams_count_query)
    players_count_result = await session.execute(players_count_query)
    champions_count_result = await session.execute(champions_count_query)
    return (
        tournaments_count_result.scalar_one(),
        teams_count_result.scalar_one(),
        players_count_result.scalar_one(),
        champions_count_result.scalar_one(),
    )


async def get_owal_standings(
    session: AsyncSession,
    season: str,
    workspace_id: int | None = None,
) -> typing.Sequence[tuple[models.User, models.Team, models.Tournament, models.Player]]:
    """
    Retrieves OWAL (Overwatch Anak League) standings.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.

    Returns:
        A sequence of tuples containing:
        1. A `User` model instance.
        2. A `Team` model instance.
        3. A `Tournament` model instance.
        4. A `Player` model instance.
    """
    query = (
        sa.select(models.User, models.Team, models.Tournament, models.Player)
        .options(
            sa.orm.joinedload(models.Team.standings),
        )
        .select_from(models.Player)
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(models.User, models.User.id == models.Player.user_id)
        .where(
            sa.and_(
                models.Tournament.is_league.is_(True),
                models.Tournament.name.startswith(season),
                models.Player.is_substitution.is_(False),
                models.Tournament.is_finished.is_(True),
            )
        )
    )
    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)
    result = await session.execute(query)
    return result.unique().all()


async def get_owal_days(
    session: AsyncSession, season: str, workspace_id: int | None = None
) -> typing.Sequence[models.Tournament]:
    """
    Retrieves OWAL (Overwatch Anak League) days.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.

    Returns:
        A sequence of `Tournament` model instances representing OWAL days.
    """
    query = (
        sa.select(models.Tournament)
        .where(
            sa.and_(
                models.Tournament.is_league.is_(True),
                models.Tournament.name.startswith(season),
            )
        )
        .order_by(models.Tournament.start_date)
    )
    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_owal_seasons(session: AsyncSession, workspace_id: int | None = None) -> list[str]:
    ws_filters = []
    if workspace_id is not None:
        ws_filters.append(models.Tournament.workspace_id == workspace_id)
    query = sa.select(models.Tournament.name).where(
        sa.and_(
            models.Tournament.is_league.is_(True),
            models.Tournament.name.startswith("OWAL Season "),
            *ws_filters,
        )
    )
    result = await session.execute(query)

    unique_seasons: dict[int, str] = {}
    for tournament_name in result.scalars().all():
        parsed = _parse_owal_season_name(tournament_name)
        if parsed is None:
            continue
        season_number, season_name = parsed
        unique_seasons[season_number] = season_name

    return [unique_seasons[season_number] for season_number in sorted(unique_seasons.keys(), reverse=True)]


async def get_bulk_tournament(
    session: AsyncSession, tournaments_ids: list[int], entities: list[str]
) -> typing.Sequence[models.Tournament]:
    """
    Retrieves a list of `Tournament` model instances by their IDs.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        tournaments_ids: A list of tournament IDs to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A sequence of `Tournament` model instances.
    """
    query = (
        sa.select(models.Tournament)
        .options(*tournament_entities(entities))
        .where(models.Tournament.id.in_(tournaments_ids))
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_league_player_stacks(
    session: AsyncSession,
    season: str,
    workspace_id: int | None = None,
) -> tuple[
    defaultdict[tuple[int, int], list[models.Player]],
    defaultdict[tuple[int, int], list[models.Player]],
    dict[tuple[int, int], models.Standing],
]:
    players = (
        (
            await session.execute(
                sa.select(models.Player)
                .join(models.Team)
                .join(models.Tournament)
                .where(
                    sa.and_(
                        models.Tournament.is_league.is_(True),
                        models.Tournament.is_finished.is_(True),
                        models.Tournament.name.startswith(season),
                        models.Player.is_substitution.is_(False),
                        *([models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []),
                    )
                )
                .options(
                    sa.orm.joinedload(models.Player.user),
                    sa.orm.joinedload(models.Player.team),
                    sa.orm.joinedload(models.Player.tournament),
                )
            )
        )
        .scalars()
        .all()
    )

    team_tournament_players = defaultdict(list)
    for player in players:
        key = (player.team_id, player.tournament_id)
        team_tournament_players[key].append(player)

    stacks = defaultdict(list)
    for (team_id, tournament_id), team_players in team_tournament_players.items():
        for player1, player2 in combinations(team_players, 2):
            stack_key = tuple(sorted([player1.user_id, player2.user_id]))
            stacks[stack_key].append((team_id, tournament_id))

    team_tournament_ids = {(team_id, tournament_id) for stack in stacks.values() for team_id, tournament_id in stack}

    if not team_tournament_ids:
        return stacks, team_tournament_players, {}

    standings = (
        (
            await session.execute(
                sa.select(models.Standing)
                .where(sa.tuple_(models.Standing.team_id, models.Standing.tournament_id).in_(team_tournament_ids))
                .options(
                    sa.orm.joinedload(models.Standing.team),
                    sa.orm.joinedload(models.Standing.tournament),
                )
            )
        )
        .scalars()
        .all()
    )

    standings_dict = {(s.team_id, s.tournament_id): s for s in standings}
    return stacks, team_tournament_players, standings_dict
