from sqlalchemy.ext.asyncio import AsyncSession

from shared.division_grid import DivisionGrid
from shared.repository import HeroRepository

from src import models, schemas
from src.core import errors, pagination

from . import service

_hero_repo = HeroRepository()


async def get_hero_leaderboard(
    session: AsyncSession,
    hero_id: int,
    params: schemas.HeroLeaderboardParams,
    workspace_id: int | None = None,
    *,
    grid: DivisionGrid,
) -> pagination.Paginated[schemas.HeroLeaderboardEntry]:
    rows, total = await service.get_hero_leaderboard(
        session,
        hero_id=hero_id,
        tournament_id=params.tournament_id,
        stat=params.stat,
        params=pagination.PaginationParams(page=params.page, per_page=params.per_page),
        workspace_id=workspace_id,
        grid=grid,
    )
    return pagination.Paginated(
        page=params.page,
        per_page=params.per_page,
        total=total,
        results=[
            schemas.HeroLeaderboardEntry(
                rank=row.rank,
                user_id=row.user_id,
                username=row.username,
                player_name=row.player_name,
                role=row.role,
                div=row.div,
                games_played=int(row.games_played),
                playtime_seconds=float(row.playtime_seconds),
                per10_eliminations=float(row.per10_eliminations),
                per10_healing=float(row.per10_healing),
                per10_deaths=float(row.per10_deaths),
                per10_damage=float(row.per10_damage),
                per10_final_blows=float(row.per10_final_blows),
                per10_damage_blocked=float(row.per10_damage_blocked),
                per10_solo_kills=float(row.per10_solo_kills),
                per10_obj_kills=float(row.per10_obj_kills),
                per10_defensive_assists=float(row.per10_defensive_assists),
                per10_offensive_assists=float(row.per10_offensive_assists),
                per10_all_damage=float(row.per10_all_damage),
                per10_damage_taken=float(row.per10_damage_taken),
                per10_self_healing=float(row.per10_self_healing),
                per10_ultimates_used=float(row.per10_ultimates_used),
                per10_multikills=float(row.per10_multikills),
                per10_env_kills=float(row.per10_env_kills),
                per10_crit_hits=float(row.per10_crit_hits),
                avg_weapon_accuracy=float(row.avg_weapon_accuracy),
                avg_crit_accuracy=float(row.avg_crit_accuracy),
                kd=float(row.kd),
                kda=float(row.kda),
            )
            for row in rows
        ],
    )


async def to_pydantic(
    session: AsyncSession, hero: models.Hero, entities: list[str]
) -> schemas.HeroRead:
    """
    Converts a Hero model instance to a Pydantic schema (HeroRead).

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        hero (models.Hero): The Hero model instance to convert.
        entities (list[str]): A list of related entities to include (currently unused in this function).

    Returns:
        schemas.HeroRead: The Pydantic schema representing the hero.
    """
    return schemas.HeroRead.model_validate(hero, from_attributes=True)


async def get(session: AsyncSession, id: int) -> schemas.HeroRead:
    """Retrieve a hero by ID and convert to its Pydantic schema."""
    hero = await _hero_repo.get(session, id)
    if hero is None:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[errors.ApiExc(code="not_found", msg=f"Hero {id} not found")],
        )
    return await to_pydantic(session, hero, [])


async def get_by_name(session: AsyncSession, name: str) -> models.Hero:
    """Retrieve a hero by name (404 if missing)."""
    hero = await _hero_repo.get_by_name(session, name)
    if not hero:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(code="not_found", msg=f"Hero with name {name} not found"),
            ],
        )
    return hero


async def get_all(
    session: AsyncSession, params: pagination.PaginationSortSearchParams
) -> pagination.Paginated[schemas.HeroRead]:
    """Paginated heroes — delegates to `HeroRepository.all`."""
    heroes, total = await _hero_repo.all(session, params)
    return pagination.Paginated(
        page=params.page,
        per_page=params.per_page,
        total=total,
        results=[await to_pydantic(session, hero, []) for hero in heroes],
    )


async def get_playtime(
    session: AsyncSession, params: schemas.HeroPlaytimePaginationParams, workspace_id: int | None = None
) -> pagination.Paginated[schemas.HeroPlaytime]:
    """Hero playtime share — delegates to `HeroRepository.playtime`."""
    user_id: int | None = None if params.user_id == "all" else params.user_id
    heroes = await _hero_repo.playtime(
        session,
        user_id=user_id,
        tournament_id=params.tournament_id,
        workspace_id=workspace_id,
    )
    # Default sort: descending by playtime (was params.apply_sort with the same default).
    heroes = sorted(heroes, key=lambda row: float(row[1]), reverse=True)
    total = len(heroes)
    paginated = params.paginate_data(heroes)
    return pagination.Paginated(
        page=params.page,
        per_page=params.per_page,
        total=total,
        results=[
            schemas.HeroPlaytime(
                hero=await to_pydantic(session, hero, []),
                playtime=round(float(playtime), 4),
            )
            for hero, playtime in paginated
        ],
    )
