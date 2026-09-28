"""Copies OverFast catalog images (hero portraits, map screenshots, gamemode
icons) into our S3 bucket, so the site never renders them from OverFast.

The OverFast instance runs on a host that Moscow, and a large share of the site's
visitors, cannot reach; a row pointing at it is a broken image. Every sync
therefore stores an S3 URL. A row already on the bucket is left alone: the
upload is skipped, and an image an admin replaced by hand survives the sync.
Rows still on an external host are mirrored by the next sync, so the sync is
also the migration.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import urlparse

from shared.clients import S3Client
from src.clients.overfast import OverFastCatalogClient, overfast_catalog_client
from src.core.clients import s3_client

__all__ = ("CatalogImageMirror", "catalog_image_mirror", "map_slug")

ImageKind = Literal["heroes", "maps", "gamemodes"]

# Same shape as the hero locale fan-out: a first sync mirrors ~60 map
# screenshots (~0.5 MB each) through the proxy, well inside the 120 s RPC budget.
_IMAGE_FETCH_CONCURRENCY = 4


def map_slug(name: str) -> str:
    """Maps carry no slug; their S3 key is derived from the name."""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "map"


class CatalogImageMirror:
    def __init__(
        self,
        *,
        s3: S3Client = s3_client,
        overfast: OverFastCatalogClient = overfast_catalog_client,
    ) -> None:
        self.s3 = s3
        self.overfast = overfast

    def is_mirrored(self, url: str | None) -> bool:
        return bool(url) and url.startswith(self.s3.get_public_url(""))

    async def mirror(self, kind: ImageKind, slug: str, source_url: str) -> str:
        """Upload ``source_url`` to ``assets/overwatch/{kind}/{slug}{ext}``; return its public URL."""
        data, content_type = await self.overfast.fetch_image(source_url)
        key = f"assets/overwatch/{kind}/{slug}{PurePosixPath(urlparse(source_url).path).suffix.lower()}"
        if not await self.s3.put_object(key, data, content_type, public=True):
            raise RuntimeError(f"S3 upload failed for {key}")
        return self.s3.get_public_url(key)

    async def resolve_many(self, kind: ImageKind, images: dict[str, tuple[str | None, str]]) -> dict[str, str]:
        """``{slug: (current, source)}`` -> ``{slug: url to store}``.

        ``current`` is kept when it is already on the bucket; otherwise
        ``source`` is mirrored. Any failure raises and fails the sync: a
        half-mirrored catalogue is still a catalogue of broken images.
        """
        semaphore = asyncio.Semaphore(_IMAGE_FETCH_CONCURRENCY)

        async def _resolve(slug: str, current: str | None, source: str) -> str:
            if current and self.is_mirrored(current):
                return current
            async with semaphore:
                return await self.mirror(kind, slug, source)

        slugs = list(images)
        urls = await asyncio.gather(*(_resolve(slug, *images[slug]) for slug in slugs))
        return dict(zip(slugs, urls, strict=True))


catalog_image_mirror = CatalogImageMirror()
