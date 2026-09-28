"""Map domain: name/alias resolution + OverFast sync + CRUD reads.

Merges the former ``service.py`` (reads) and ``flows.py`` (OverFast sync +
alias-miss resolution) into one class, per ``backend/ARCHITECTURE.md``'s
"small domains keep everything in one service.py" rule.
"""

from __future__ import annotations

import typing

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared.repository import MapRepository
from src import models, schemas
from src.clients.overfast import OverFastCatalogClient, overfast_catalog_client
from src.core import enums, errors, pagination, utils
from src.services import catalog_aliases
from src.services.catalog_images import CatalogImageMirror, catalog_image_mirror, map_slug
from src.services.gamemode.service import gamemode_service

__all__ = ("MapService", "map_service", "map_entities", "to_pydantic")


def map_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    entities = []
    if "gamemode" in in_entities:
        entities.append(utils.join_entity(child, models.Map.gamemode))

    return entities


def to_pydantic(map: models.Map, entities: list[str]) -> schemas.MapRead:
    gamemode: schemas.GamemodeRead | None = None
    if "gamemode" in entities:
        gamemode = schemas.GamemodeRead(**map.gamemode.to_dict())
    return schemas.MapRead(
        id=map.id,
        name=map.name,
        image_path=map.image_path,
        gamemode=gamemode,
    )


class MapService:
    def __init__(
        self,
        *,
        repo: MapRepository = MapRepository(),
        overfast: OverFastCatalogClient = overfast_catalog_client,
        images: CatalogImageMirror = catalog_image_mirror,
    ) -> None:
        self.repo = repo
        self.overfast = overfast
        self.images = images

    async def get_by_names(self, session: AsyncSession, names: list[str]) -> dict[str, models.Map]:
        """All maps whose name is in ``names``, indexed by name, in one query
        (batch counterpart of the per-item probe in ``initial_create``)."""
        return await self.repo.get_many_by(session, models.Map.name, names)

    async def get_by_name_or_alias_and_gamemode(
        self, session: AsyncSession, name: str, gamemode: str
    ) -> models.Map | None:
        """Thin wrapper over the repository — it owns the predicate so the SQL
        stays assertable without a database."""
        return await self.repo.get_by_name_or_alias_and_gamemode(session, name=name, gamemode=gamemode)

    async def resolve_by_name_or_alias_and_gamemode(
        self, session: AsyncSession, name: str, gamemode: str, *, log_record_id: int | None = None
    ) -> models.Map:
        """Resolve a log's raw map + gamemode names through `name` or `aliases`."""
        map = await self.get_by_name_or_alias_and_gamemode(session, name, gamemode)
        if not map:
            # Recorded BEFORE the raise and in its own transaction: the 404 rolls
            # the log-processing session back. Both names go in — a failed join
            # cannot tell which of the two was the unknown one.
            await catalog_aliases.record_misses(enums.CatalogEntityType.map, [name], log_record_id=log_record_id)
            await catalog_aliases.record_misses(
                enums.CatalogEntityType.gamemode, [gamemode], log_record_id=log_record_id
            )
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[
                    errors.ApiExc(
                        code="not_found",
                        msg=f"Map with name {name} and gamemode {gamemode} not found",
                    ),
                ],
            )
        return map

    async def fetch_maps(self, gamemode: models.Gamemode) -> list[schemas.OverfastMap]:
        return await self.overfast.fetch_maps(gamemode.slug)

    async def initial_create(self, session: AsyncSession) -> None:
        gamemodes, total = await gamemode_service.get_all(
            session,
            params=pagination.PaginationSortParams(per_page=-1, page=1),
        )
        # Release the transaction opened by the reads above before the OverFast
        # round-trips; expire_on_commit=False keeps the gamemodes usable.
        await session.commit()

        # ponytail: sequential — 2-3 gamemodes, lower priority than the 13-way
        # hero locale fan-out; parallelize with the same semaphore+gather shape
        # if the gamemode count grows enough to matter.
        fetched: list[tuple[models.Gamemode, list[schemas.OverfastMap]]] = []
        for gamemode in gamemodes:
            fetched.append((gamemode, await self.fetch_maps(gamemode)))

        # One existence query + one bulk write instead of a get-then-create/update
        # pair per map. A map created for an earlier gamemode is found in the
        # index and updated (name/image only), exactly like the old per-item
        # re-SELECT.
        maps_by_name = await self.get_by_names(session, [map.name for _, maps in fetched for map in maps])
        # Release the read transaction before the image round-trips;
        # expire_on_commit=False keeps the rows loaded and tracked.
        await session.commit()
        image_paths = await self.images.resolve_many(
            "maps",
            {
                map_slug(map.name): (getattr(maps_by_name.get(map.name), "image_path", None), map.screenshot)
                for _, maps in fetched
                for map in maps
            },
        )

        new_maps: list[models.Map] = []
        for gamemode, maps in fetched:
            for map in maps:
                map_db = maps_by_name.get(map.name)
                if not map_db:
                    map_db = models.Map(gamemode_id=gamemode.id, name=map.name)
                    maps_by_name[map.name] = map_db
                    new_maps.append(map_db)
                else:
                    map_db.name = map.name
                map_db.image_path = image_paths[map_slug(map.name)]

        if new_maps:
            await self.repo.create_many(session, new_maps)
        await session.commit()


map_service = MapService()
