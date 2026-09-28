"""Hero domain: OverFast locale sync + CRUD reads.

Merges the former ``service.py`` (reads) and ``flows.py`` (OverFast sync
orchestration) into one class, per ``backend/ARCHITECTURE.md``'s "small
domains keep everything in one service.py" rule.
"""

from __future__ import annotations

import asyncio
import typing

from sqlalchemy.ext.asyncio import AsyncSession

from shared.repository import HeroRepository
from src import models, schemas
from src.clients.overfast import OverFastCatalogClient, overfast_catalog_client
from src.core import errors, pagination
from src.domain.hero_aliases import merge_aliases
from src.services.catalog_images import CatalogImageMirror, catalog_image_mirror

__all__ = ("HeroService", "hero_service", "get_all", "CANONICAL_LOCALE", "ALIAS_LOCALES")

# Every Blizzard locale OverFast serves (`GET /heroes?locale=`). Match logs are
# written in the reporting client's locale, so all thirteen are pulled: twelve
# extra requests once per sync against silently dropped statistics.
CANONICAL_LOCALE = "en-us"
ALIAS_LOCALES = (
    "de-de",
    "en-gb",
    "es-es",
    "es-mx",
    "fr-fr",
    "it-it",
    "ja-jp",
    "ko-kr",
    "pl-pl",
    "pt-br",
    "ru-ru",
    "zh-tw",
)

# Mirrors `team/flows.py`'s `_CHALLONGE_FETCH_CONCURRENCY` pattern for the same
# shape of problem: N independent locale round-trips, capped concurrency.
_LOCALE_FETCH_CONCURRENCY = 4


class HeroService:
    def __init__(
        self,
        *,
        repo: HeroRepository = HeroRepository(),
        overfast: OverFastCatalogClient = overfast_catalog_client,
        images: CatalogImageMirror = catalog_image_mirror,
    ) -> None:
        self.repo = repo
        self.overfast = overfast
        self.images = images

    async def get_by_slugs(self, session: AsyncSession, slugs: list[str]) -> dict[str, models.Hero]:
        """Heroes among ``slugs`` that already exist, keyed by slug, in one query
        (batch counterpart of the per-item probe used by ``initial_create``).
        Returns the rows rather than just the slugs because the locale sync has
        to refresh ``aliases`` on the heroes it does not create."""
        return await self.repo.get_many_by(session, models.Hero.slug, slugs)

    async def get_by_slug(self, session: AsyncSession, slug: str) -> models.Hero:
        hero = await self.repo.get_by(session, slug=slug)
        if not hero:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Hero with slug {slug} not found")],
            )
        return hero

    async def get_by_name(self, session: AsyncSession, name: str) -> models.Hero:
        hero = await self.repo.get_by_name(session, name)
        if not hero:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Hero with name {name} not found")],
            )
        return hero

    async def get_all(
        self, session: AsyncSession, params: pagination.PaginationSortParams
    ) -> tuple[typing.Sequence[models.Hero], int]:
        return await self.repo.get_all(session, params)

    async def fetch_heroes(self, locale: str = CANONICAL_LOCALE) -> list[schemas.OverfastHero]:
        return await self.overfast.fetch_heroes(locale)

    async def initial_create(self, session: AsyncSession) -> None:
        # Canonical pass first, then every alias locale concurrently (capped).
        # All the OverFast round-trips happen before the first DB read, so no
        # transaction is held open across them.
        canonical_heroes = await self.fetch_heroes(CANONICAL_LOCALE)
        localized: dict[str, set[str]] = {hero.key: {hero.name} for hero in canonical_heroes}

        semaphore = asyncio.Semaphore(_LOCALE_FETCH_CONCURRENCY)

        async def _fetch_locale(locale: str) -> list[schemas.OverfastHero]:
            async with semaphore:
                return await self.fetch_heroes(locale)

        for heroes in await asyncio.gather(*(_fetch_locale(locale) for locale in ALIAS_LOCALES)):
            for hero in heroes:
                localized.setdefault(hero.key, set()).add(hero.name)

        # One existence query + one bulk insert instead of a get-then-create pair
        # per hero. Pre-existing rows keep their name/type; `aliases` is refreshed
        # by reassignment (JSONB does not track in-place mutation) and
        # `image_path` moves onto our bucket if it is not there yet.
        existing_heroes = await self.get_by_slugs(session, [hero.key for hero in canonical_heroes])
        # Release the read transaction before the image round-trips;
        # expire_on_commit=False keeps the rows loaded and tracked.
        await session.commit()
        image_paths = await self.images.resolve_many(
            "heroes",
            {
                hero.key: (getattr(existing_heroes.get(hero.key), "image_path", None), hero.portrait)
                for hero in canonical_heroes
            },
        )

        new_heroes: list[models.Hero] = []
        for hero in canonical_heroes:
            hero_db = existing_heroes.get(hero.key)
            if hero_db is None:
                hero_db = models.Hero(
                    slug=hero.key,
                    name=hero.name,
                    type=hero.role,  # type: ignore
                )
                existing_heroes[hero.key] = hero_db
                new_heroes.append(hero_db)
            hero_db.image_path = image_paths[hero.key]
            hero_db.aliases = merge_aliases(
                existing=hero_db.aliases or [],
                localized=localized[hero.key],
                canonical=hero_db.name,
            )

        if new_heroes:
            await self.repo.create_many(session, new_heroes)
        await session.commit()


hero_service = HeroService()

# `services/match_logs/flows.py` (a different work package's file set) imports
# this module and calls `hero_service.get_all(...)` directly — kept resolvable
# as a module-level attribute rather than only on the class, per the
# compat-binding rule in
# `docs/plans/2026-08-21-parser-service-oop-repositories.md`.
get_all = hero_service.get_all
