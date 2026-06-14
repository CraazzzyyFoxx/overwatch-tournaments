import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config, enums, errors

from . import service


async def fetch_heroes(role: str) -> list[schemas.OverfastHero]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{config.settings.overfast_base_url}/heroes?role={role}&locale=en-us"
        )
        response.raise_for_status()

    return [schemas.OverfastHero.model_validate(gamemode) for gamemode in response.json()]


async def initial_create(session: AsyncSession) -> None:
    for hero_class in enums.HeroClass.__members__.keys():
        heroes = await fetch_heroes(hero_class)
        for hero in heroes:
            if not await service.get_by_slug(session, hero.key):
                await service.create(
                    session,
                    slug=hero.key,
                    name=hero.name,
                    type=hero.role,  # type: ignore
                    image_path=hero.portrait,
                )


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
