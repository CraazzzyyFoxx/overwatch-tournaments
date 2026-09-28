"""OverFast API client for catalog sync (heroes/maps/gamemodes).

Sibling of ``services/overwatch_rank/client.py``'s ``OverFastRankClient`` —
same OverFast API, disjoint endpoints (player summaries vs. static game
content) and disjoint failure handling (rank fetches classify 404/429/5xx
into typed outcomes; catalog syncs run rarely, admin-triggered, and can
afford to just raise). Kept as its own class rather than folded into
``OverFastRankClient`` to avoid coupling catalog sync to the rank client's
rate-limit/retry-classification concerns it doesn't need.

Built on the same ``ResilientHttpClient`` (connection pooling + retries) the
rank client uses, replacing the three near-identical raw
``httpx.AsyncClient(timeout=30)`` blocks hero/map/gamemode sync each had
their own copy of.
"""

from __future__ import annotations

from shared.clients.http_client import ResilientHttpClient
from src import schemas
from src.core.config import settings


class OverFastCatalogClient:
    def __init__(self, *, base_url: str | None = None, timeout: float = 15.0, max_retries: int = 3) -> None:
        self._http = ResilientHttpClient(
            base_url=base_url or settings.overfast_base_url,
            timeout=timeout,
            max_retries=max_retries,
            proxy=settings.overfast_proxy_url,
        )

    async def start(self) -> None:
        await self._http.start()

    async def close(self) -> None:
        await self._http.close()

    async def fetch_heroes(self, locale: str) -> list[schemas.OverfastHero]:
        # `role` comes back in the payload whatever the filter, so no ?role= is
        # needed: one request per locale instead of one per role.
        response = await self._http.get(f"/heroes?locale={locale}")
        response.raise_for_status()
        return [schemas.OverfastHero.model_validate(hero) for hero in response.json()]

    async def fetch_maps(self, gamemode_slug: str) -> list[schemas.OverfastMap]:
        response = await self._http.get(f"/maps?gamemode={gamemode_slug}")
        response.raise_for_status()
        return [schemas.OverfastMap.model_validate(map_) for map_ in response.json()]

    async def fetch_gamemodes(self) -> list[schemas.OverfastGamemode]:
        response = await self._http.get("/gamemodes")
        response.raise_for_status()
        return [schemas.OverfastGamemode.model_validate(gamemode) for gamemode in response.json()]


overfast_catalog_client = OverFastCatalogClient()
