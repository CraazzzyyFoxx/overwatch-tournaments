from sqlalchemy.ext.asyncio import AsyncSession

from src import schemas
from src.core import pagination

from . import service


async def get_most_champions(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
) -> pagination.Paginated[schemas.PlayerStatistics]:
    """
    Retrieves a paginated list of players with the most championship wins.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (pagination.PaginationSortParams): Pagination and sorting parameters.

    Returns:
        pagination.Paginated[schemas.PlayerStatistics]: A paginated list of Pydantic schemas representing players and their championship counts.
    """
    champions, total = await service.get_top_champions(session, params, workspace_id=workspace_id)
    return pagination.Paginated(
        page=params.page,
        per_page=params.per_page,
        total=total,
        results=[
            schemas.PlayerStatistics(
                id=champion.id,
                name=champion.name,
                value=count,
            )
            for champion, count in champions
        ],
    )


async def get_to_winrate_players(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
) -> pagination.Paginated[schemas.PlayerStatistics]:
    """
    Retrieves a paginated list of players with the highest win rates.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (pagination.PaginationSortParams): Pagination and sorting parameters.

    Returns:
        pagination.Paginated[schemas.PlayerStatistics]: A paginated list of Pydantic schemas representing players and their win rates.
    """
    rows, total = await service.get_top_winrate_players(session, params, workspace_id=workspace_id)
    return pagination.Paginated(
        page=params.page,
        per_page=params.per_page,
        total=total,
        results=[
            schemas.PlayerStatistics(
                id=player.id,
                name=player.name,
                value=round(winrate, 2),
            )
            for player, winrate in rows
        ],
    )


async def get_to_won_players(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
) -> pagination.Paginated[schemas.PlayerStatistics]:
    """
    Retrieves a paginated list of players with the most wins.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (pagination.PaginationSortParams): Pagination and sorting parameters.

    Returns:
        pagination.Paginated[schemas.PlayerStatistics]: A paginated list of Pydantic schemas representing players and their win counts.
    """
    rows, total = await service.get_top_won_players(session, params, workspace_id=workspace_id)
    return pagination.Paginated(
        page=params.page,
        per_page=params.per_page,
        total=total,
        results=[
            schemas.PlayerStatistics(
                id=player.id,
                name=player.name,
                value=value,
            )
            for player, value in rows
        ],
    )
