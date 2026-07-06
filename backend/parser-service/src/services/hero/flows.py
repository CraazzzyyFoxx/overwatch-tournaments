import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config, enums, errors

from . import service


async def fetch_heroes(role: str) -> list[schemas.OverfastHero]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{config.settings.overfast_base_url}/heroes?role={role}&locale=en-us")
        response.raise_for_status()

    return [schemas.OverfastHero.model_validate(gamemode) for gamemode in response.json()]


async def initial_create(session: AsyncSession) -> None:
    heroes: list[schemas.OverfastHero] = []
    for hero_class in enums.HeroClass.__members__.keys():
        heroes.extend(await fetch_heroes(hero_class))

    # One existence query + one bulk insert instead of a get-then-create pair
    # per hero.
    existing_slugs = await service.get_existing_slugs(session, [hero.key for hero in heroes])
    new_heroes: list[models.Hero] = []
    for hero in heroes:
        if hero.key in existing_slugs:
            continue
        existing_slugs.add(hero.key)
        new_heroes.append(
            models.Hero(
                slug=hero.key,
                name=hero.name,
                type=hero.role,  # type: ignore
                image_path=hero.portrait,
            )
        )

    if new_heroes:
        session.add_all(new_heroes)
        await session.commit()


async def get_by_name(session: AsyncSession, name: str) -> models.Hero:
    hero = await service.get_by_name(session, name)
    if not hero:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(code="not_found", msg=f"Hero with name {name} not found"),
            ],
        )
    return hero


async def get_by_slug(session: AsyncSession, slug: str) -> models.Hero:
    hero = await service.get_by_slug(session, slug)
    if not hero:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(code="not_found", msg=f"Hero with slug {slug} not found"),
            ],
        )
    return hero
