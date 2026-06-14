import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import enums, pagination

home_score_case = sa.case(
    (models.Encounter.home_team_id == models.Team.id, models.Encounter.home_score),
    else_=models.Encounter.away_score,
).label("home_score_case")
away_score_case = sa.case(
    (models.Encounter.home_team_id == models.Team.id, models.Encounter.away_score),
    else_=models.Encounter.home_score,
).label("away_score_case")


encounter_query = (
    sa.select(
        models.Player.id,
        home_score_case.label("home_score"),
        away_score_case.label("away_score"),
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
).subquery("encounters")


async def get_top_champions(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
) -> tuple[typing.Sequence[tuple[models.Player, int]], int]:
    """
    Retrieves a paginated list of players with the most championship wins.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (pagination.PaginationSortParams): Pagination and sorting parameters.

    Returns:
        tuple[typing.Sequence[tuple[models.Player, int]], int]: A tuple containing:
            - A sequence of tuples, each containing a Player object and their championship count.
            - The total count of players.
    """
    total_query = sa.select(sa.func.count(models.User.id))

    query = (
        sa.select(models.User, sa.func.count("*").label("value"))
        .select_from(models.Player)
        .join(models.User, models.User.id == models.Player.user_id)
        .join(models.Team, models.Team.id == models.Player.team_id)
        .join(models.Standing, models.Standing.team_id == models.Team.id)
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
                *([models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []),
            )
        )
        .group_by(models.User.id)
    )
    query = params.apply_pagination_sort(query)
    result = await session.execute(query)
    total = await session.execute(total_query)
    return result.all(), total.scalar()  # type: ignore


async def get_top_winrate_players(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
) -> tuple[typing.Sequence[tuple[models.Player, float]], int]:
    """
    Retrieves a paginated list of players with the highest win rates.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (pagination.PaginationSortParams): Pagination and sorting parameters.

    Returns:
        tuple[typing.Sequence[tuple[models.Player, float]], int]: A tuple containing:
            - A sequence of tuples, each containing a Player object and their win rate.
            - The total count of players.
    """
    total_query = sa.select(sa.func.count(models.User.id))

    query = (
        sa.select(
            models.User,
            (
                sa.func.sum(encounter_query.c.home_score)
                / (sa.func.sum(encounter_query.c.home_score) + sa.func.sum(encounter_query.c.away_score))
            ).label("value"),
        )
        .select_from(models.Player)
        .join(models.User, models.User.id == models.Player.user_id)
        .join(encounter_query, encounter_query.c.id == models.Player.id)
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Player.is_substitution.is_(False),
            models.Tournament.is_league.is_(False),
            *([models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []),
        )
        .group_by(models.User.id)
        .having(sa.func.count(models.Tournament.id.distinct()) > 3)
    )
    query = params.apply_pagination_sort(query)
    result = await session.execute(query)
    total = await session.execute(total_query)
    return result.all(), total.scalar()  # type: ignore


async def get_top_won_players(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
) -> tuple[typing.Sequence[tuple[models.Player, int]], int]:
    """
    Retrieves a paginated list of players with the most wins.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (pagination.PaginationSortParams): Pagination and sorting parameters.

    Returns:
        tuple[typing.Sequence[tuple[models.Player, int]], int]: A tuple containing:
            - A sequence of tuples, each containing a Player object and their win count.
            - The total count of players.
    """
    total_query = sa.select(sa.func.count(models.User.id))

    query = (
        sa.select(models.User, sa.func.sum(encounter_query.c.home_score).label("value"))
        .select_from(models.Player)
        .join(models.User, models.User.id == models.Player.user_id)
        .join(encounter_query, encounter_query.c.id == models.Player.id)
        .where(
            models.Player.is_substitution.is_(False),
            *([models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []),
        )
        .group_by(models.User.id)
        .having(sa.func.count(models.Tournament.id.distinct()) > 3)
    )
    query = params.apply_pagination_sort(query)
    result = await session.execute(query)
    total = await session.execute(total_query)
    return result.all(), total.scalar()  # type: ignore


async def get_tournament_avg_match_stat_for_user(
    session: AsyncSession,
    tournament: models.Tournament,
    user_id: int,
    stat_name: enums.LogStatsName,
    order: bool = False,
) -> tuple[tuple[int, float, int], int]:
    """
    Retrieves the average match statistic for a specific user in a tournament, along with their rank.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        tournament (models.Tournament): The Tournament model instance.
        user_id (int): The ID of the user.
        stat_name (enums.LogStatsName): The name of the statistic to retrieve.
        order (bool): If True, orders the results in ascending order; otherwise, descending.

    Returns:
        tuple[tuple[int, float, int], int]: A tuple containing:
            - A tuple with the user ID, average value, and rank.
            - The total count of users.
    """
    if not order:
        order_by = sa.desc(sa.func.avg(models.MatchStatistics.value))
    else:
        order_by = sa.asc(sa.func.avg(models.MatchStatistics.value))

    stats_query = (
        sa.select(
            models.MatchStatistics.user_id,
            sa.func.avg(models.MatchStatistics.value).cast(sa.Numeric(10, 2)).label("value"),
            sa.func.dense_rank().over(order_by=order_by).label("rank"),
        )
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .where(
            sa.and_(
                models.MatchStatistics.name == stat_name,
                models.Encounter.tournament_id == tournament.id,
                models.MatchStatistics.round == 0,
            )
        )
        .group_by(models.MatchStatistics.user_id)
    ).cte("stats_query")

    query = sa.select(stats_query, sa.select(sa.func.count(stats_query.c.user_id)).scalar_subquery()).where(
        stats_query.c.user_id == user_id
    )

    result = await session.execute(query)

    return result.first()  # type: ignore


async def get_tournament_avg_match_stat_for_user_bulk(
    session: AsyncSession,
    tournament: models.Tournament,
    user_id: int,
    stats_names: list[enums.LogStatsName],
) -> typing.Sequence[tuple[enums.LogStatsName, int, float, int, int, int]]:
    """
    Retrieves the average match statistics for a specific user in a tournament across multiple stats, along with their ranks.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        tournament (models.Tournament): The Tournament model instance.
        user_id (int): The ID of the user.
        stats_names (list[enums.LogStatsName]): A list of statistic names to retrieve.

    Returns:
        typing.Sequence[tuple[enums.LogStatsName, int, float, int, int]]: A sequence of tuples, each containing:
            - The statistic name.
            - The user ID.
            - The average value.
            - The rank.
            - The total count of users.
    """
    stats_query = (
        sa.select(
            models.MatchStatistics.name,
            models.MatchStatistics.user_id,
            sa.func.avg(models.MatchStatistics.value).cast(sa.Numeric(10, 2)).label("value"),
            sa.func.dense_rank()
            .over(
                order_by=sa.desc(sa.func.avg(models.MatchStatistics.value)),
                partition_by=models.MatchStatistics.name,
            )
            .label("rank"),
            sa.func.dense_rank()
            .over(
                order_by=sa.asc(sa.func.avg(models.MatchStatistics.value)),
                partition_by=models.MatchStatistics.name,
            )
            .label("rank_asc"),
        )
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .where(
            sa.and_(
                models.MatchStatistics.name.in_(stats_names),
                models.Encounter.tournament_id == tournament.id,
                models.MatchStatistics.round == 0,
                models.MatchStatistics.hero_id.is_(None),
            )
        )
        .group_by(models.MatchStatistics.user_id, models.MatchStatistics.name)
    ).cte("stats_query")

    query = sa.select(
        stats_query,
        sa.select(sa.func.count(stats_query.c.user_id) / len(stats_names)).scalar_subquery(),
    ).where(stats_query.c.user_id == user_id)

    result = await session.execute(query)
    return result.all()  # type: ignore


async def get_tournament_winrate(
    session: AsyncSession, tournament: models.Tournament, user_id: int
) -> tuple[int, float, int, int] | None:
    """
    Retrieves the win rate for a specific user in a tournament, along with their rank.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        tournament (models.Tournament): The Tournament model instance.
        user_id (int): The ID of the user.

    Returns:
        tuple[int, float, int, int] | None: A tuple containing:
            - The user ID.
            - The win rate.
            - The rank.
            - The total count of users.
            Returns None if no data is found.
    """
    winrate = (sa.func.sum(home_score_case) / (sa.func.sum(home_score_case) + sa.func.sum(away_score_case))).label(
        "winrate"
    )

    stats_query = (
        sa.select(
            models.Player.user_id,
            winrate.cast(sa.Numeric(10, 2)).label("winrate"),
            sa.func.dense_rank().over(order_by=(sa.desc(winrate))).label("rank"),
        )
        .select_from(models.Encounter)
        .join(
            models.Team,
            sa.or_(
                models.Encounter.home_team_id == models.Team.id,
                models.Encounter.away_team_id == models.Team.id,
            ),
        )
        .join(models.Player, models.Player.team_id == models.Team.id)
        .where(sa.and_(models.Encounter.tournament_id == tournament.id))
        .group_by(models.Player.user_id)
    ).subquery()

    query = sa.select(stats_query, sa.select(sa.func.max(stats_query.c.rank)).scalar_subquery()).where(
        stats_query.c.user_id == user_id
    )

    result = await session.execute(query)
    return result.first()
