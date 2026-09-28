"""Gamemode domain: OverFast sync + CRUD reads.

Merges the former ``service.py`` (reads) and ``flows.py`` (OverFast sync
orchestration) into one class, per ``backend/ARCHITECTURE.md``'s "small
domains keep everything in one service.py" rule.
"""

from __future__ import annotations

import typing

from sqlalchemy.ext.asyncio import AsyncSession

from shared.repository import GamemodeRepository
from src import models, schemas
from src.clients.overfast import OverFastCatalogClient, overfast_catalog_client
from src.core import pagination
from src.services.catalog_images import CatalogImageMirror, catalog_image_mirror

__all__ = ("GamemodeService", "gamemode_service")


class GamemodeService:
    def __init__(
        self,
        *,
        repo: GamemodeRepository = GamemodeRepository(),
        overfast: OverFastCatalogClient = overfast_catalog_client,
        images: CatalogImageMirror = catalog_image_mirror,
    ) -> None:
        self.repo = repo
        self.overfast = overfast
        self.images = images

    async def get(self, session: AsyncSession, id: int) -> models.Gamemode | None:
        return await self.repo.get(session, id)

    async def get_by_slugs(self, session: AsyncSession, slugs: list[str]) -> dict[str, models.Gamemode]:
        """Gamemodes among ``slugs`` that already exist, keyed by slug, in one
        query (batch counterpart of the per-item probe used by ``initial_create``)."""
        return await self.repo.get_many_by(session, models.Gamemode.slug, slugs)

    async def get_by_slug(self, session: AsyncSession, slug: str) -> models.Gamemode | None:
        return await self.repo.get_by(session, slug=slug)

    async def get_all(
        self, session: AsyncSession, params: pagination.PaginationSortParams
    ) -> tuple[typing.Sequence[models.Gamemode], int]:
        return await self.repo.get_all(session, params)

    async def fetch_gamemodes(self) -> list[schemas.OverfastGamemode]:
        return await self.overfast.fetch_gamemodes()

    async def initial_create(self, session: AsyncSession) -> None:
        gamemodes = await self.fetch_gamemodes()

        # One existence query + one bulk insert instead of a get-then-create pair
        # per gamemode. Existing rows keep everything but `image_path`, which
        # moves onto our bucket if it is not there yet.
        existing = await self.get_by_slugs(session, [gamemode.key for gamemode in gamemodes])
        # Release the read transaction before the image round-trips;
        # expire_on_commit=False keeps the rows loaded and tracked.
        await session.commit()
        image_paths = await self.images.resolve_many(
            "gamemodes",
            {
                gamemode.key: (getattr(existing.get(gamemode.key), "image_path", None), gamemode.icon)
                for gamemode in gamemodes
            },
        )

        new_gamemodes: list[models.Gamemode] = []
        for gamemode in gamemodes:
            gamemode_db = existing.get(gamemode.key)
            if gamemode_db is None:
                gamemode_db = models.Gamemode(slug=gamemode.key, name=gamemode.name, description=gamemode.description)
                existing[gamemode.key] = gamemode_db
                new_gamemodes.append(gamemode_db)
            gamemode_db.image_path = image_paths[gamemode.key]

        if new_gamemodes:
            await self.repo.create_many(session, new_gamemodes)
        await session.commit()


gamemode_service = GamemodeService()
