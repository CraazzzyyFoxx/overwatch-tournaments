"""Map stats queries specific to app-service.

Generic CRUD-style operations (`get`, `get_by_name`, `get_by_name_and_gamemode`,
`all`) live on `shared.repository.MapRepository`. The aggregate `get_top_maps`
below is user-stats domain and stays here.
"""

import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models, schemas
from src.core import pagination


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
    # Pre-resolve the user's team_id for each match via a CTE — this avoids
    # fan-out from the Player table when a user has multiple Player records
    # for the same team (e.g. starter + substitution role for different periods).
    user_match_teams = (
        sa.select(
            models.Match.id.label("match_id"),
            models.Match.map_id.label("map_id"),
            models.Match.encounter_id.label("encounter_id"),
            models.Match.home_team_id.label("home_team_id"),
            models.Match.home_score.label("home_score"),
            models.Match.away_score.label("away_score"),
            models.Team.id.label("user_team_id"),
        )
        .select_from(models.Match)
        .join(
            models.Team,
            sa.or_(
                models.Team.id == models.Match.home_team_id,
                models.Team.id == models.Match.away_team_id,
            ),
        )
        .join(models.Player, models.Player.team_id == models.Team.id)
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
        .where(
            sa.and_(
                models.WorkspaceMember.player_id == user_id,
                models.Player.is_substitution.is_(False),
            )
        )
        .distinct()
        .cte("user_match_teams")
    )

    user_home_score = sa.case(
        (user_match_teams.c.home_team_id == user_match_teams.c.user_team_id, user_match_teams.c.home_score),
        else_=user_match_teams.c.away_score,
    )
    user_away_score = sa.case(
        (user_match_teams.c.home_team_id == user_match_teams.c.user_team_id, user_match_teams.c.away_score),
        else_=user_match_teams.c.home_score,
    )
    user_win = sa.case((user_home_score > user_away_score, 1), else_=0)
    user_loss = sa.case((user_home_score < user_away_score, 1), else_=0)
    user_draw = sa.case((user_home_score == user_away_score, 1), else_=0)

    subquery_query = (
        sa.select(
            models.Map.id.label("map_id"),
            sa.func.count(user_match_teams.c.match_id).label("count"),
            sa.func.sum(user_win).label("win"),
            sa.func.sum(user_loss).label("loss"),
            sa.func.sum(user_draw).label("draw"),
            (sa.func.sum(user_win) / sa.func.count(user_match_teams.c.match_id))
            .cast(sa.Numeric(10, 2))
            .label("winrate"),
        )
        .select_from(user_match_teams)
        .join(models.Map, models.Map.id == user_match_teams.c.map_id)
        .group_by(models.Map.id)
    )

    if params.tournament_id or workspace_id:
        subquery_query = subquery_query.join(models.Encounter, models.Encounter.id == user_match_teams.c.encounter_id)

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
        subquery_query = subquery_query.having(sa.func.count(user_match_teams.c.match_id) >= params.min_count)

    subquery = subquery_query.subquery("user_map_stats")

    total_query = sa.select(sa.func.count()).select_from(subquery)

    query = sa.select(
        models.Map,
        subquery.c.count,
        subquery.c.win,
        subquery.c.loss,
        subquery.c.draw,
        subquery.c.winrate,
    ).join(subquery, subquery.c.map_id == models.Map.id)
    if "gamemode" in params.entities:
        query = query.options(selectinload(models.Map.gamemode))

    query = params.apply_sort(query)
    if params.sort == "winrate":
        query = query.order_by(subquery.c.count.desc())
    query = query.order_by(models.Map.id.asc())
    query = params.apply_pagination(query)

    result = await session.execute(query)
    result_total = await session.execute(total_query)
    return result.all(), result_total.scalar_one()  # type: ignore
