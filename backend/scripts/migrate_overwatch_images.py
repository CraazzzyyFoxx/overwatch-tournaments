"""Migrate Overwatch hero and map images from external CDNs (like CloudFront) to S3/MinIO.

Downloads images, uploads them to your configured S3 bucket under assets/overwatch/,
and updates the image_path column in overwatch.hero and overwatch.map tables.

Usage:
    cd backend/
    python -m scripts.migrate_overwatch_images
    python -m scripts.migrate_overwatch_images --dry-run
"""

import asyncio
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

import click
import httpx
import sqlalchemy as sa
from loguru import logger
from pydantic_settings import SettingsConfigDict
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared.clients.s3 import S3Client
from shared.core.config import BaseServiceSettings

_env_dir = Path(__file__).resolve().parent.parent / "env"


class _ScriptSettings(BaseServiceSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_env_dir / "common.env"), ".env", ".env.prod"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = _ScriptSettings()


def _slugify_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "map"


async def migrate(dry_run: bool = False) -> None:
    # Initialize S3 Client
    s3 = S3Client(
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        endpoint_url=settings.s3_endpoint_url,
        bucket_name=settings.s3_bucket_name,
        public_url=settings.s3_public_url,
    )
    await s3.start()

    # Determine internal hosts to avoid self-migration
    s3_hosts = []
    if settings.s3_endpoint_url:
        try:
            s3_hosts.append(urlparse(settings.s3_endpoint_url).netloc)
        except Exception:
            pass
    if settings.s3_public_url:
        try:
            s3_hosts.append(urlparse(settings.s3_public_url).netloc)
        except Exception:
            pass
    # fallback
    s3_hosts.append("minio.craazzzyyfoxx.me")
    s3_hosts = list(set(filter(None, s3_hosts)))

    logger.info(f"S3/MinIO bucket: '{settings.s3_bucket_name}'")
    logger.info(f"S3 internal/public hosts to exclude: {s3_hosts}")

    # Set up DB connection
    engine = create_async_engine(settings.db_url_asyncpg)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    # Configure proxy for httpx if configured
    proxy_url = settings.proxy_url
    client_kwargs = {
        "follow_redirects": True,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
        "timeout": 30.0,
    }
    if proxy_url:
        logger.info(f"Using HTTPX proxy settings: {proxy_url}")
        client_kwargs["proxy"] = proxy_url

    async with httpx.AsyncClient(**client_kwargs) as http_client, session_maker() as session:
        # --- MIGRATE HEROES ---
        logger.info("Checking overwatch.hero images...")
        hero_rows = await session.execute(sa.text("SELECT id, slug, name, image_path FROM overwatch.hero ORDER BY id"))
        heroes = hero_rows.all()

        hero_migrated = 0
        for h_id, h_slug, h_name, h_img in heroes:
            if not h_img:
                logger.warning(f"Hero '{h_name}' (ID: {h_id}) has empty image_path.")
                continue

            # Check if it is external
            is_external = h_img.startswith("http") and not any(host in h_img for host in s3_hosts)
            if not is_external:
                logger.debug(f"Skipping hero '{h_name}' — image is already internal or local: {h_img}")
                continue

            # Construct key
            ext = "png"
            parsed = urlparse(h_img.split("?")[0])
            if "." in parsed.path.split("/")[-1]:
                ext = parsed.path.split(".")[-1].lower()
            key = f"assets/overwatch/heroes/{h_slug}.{ext}"

            logger.info(f"Migrating hero '{h_name}': {h_img} -> {key}")

            if dry_run:
                logger.info(f"[DRY-RUN] Would download {h_img} and upload to key '{key}'")
                hero_migrated += 1
                continue

            # Download
            try:
                resp = await http_client.get(h_img)
                resp.raise_for_status()
                data = resp.content
            except Exception as e:
                logger.error(f"Failed to download image for hero '{h_name}' from {h_img}: {e}")
                continue

            # Content type guessing
            content_type = resp.headers.get("content-type") or mimetypes.guess_type(h_img)[0] or f"image/{ext}"

            # Upload
            ok = await s3.put_object(key, data, content_type, public=True)
            if not ok:
                logger.error(f"Failed to upload hero image to S3: {key}")
                continue

            # Update DB
            new_url = s3.get_public_url(key)
            await session.execute(
                sa.text("UPDATE overwatch.hero SET image_path = :url WHERE id = :id"),
                {"url": new_url, "id": h_id},
            )
            logger.info(f"Updated hero '{h_name}' image path in DB to {new_url}")
            hero_migrated += 1

        # --- MIGRATE MAPS ---
        logger.info("Checking overwatch.map images...")
        map_rows = await session.execute(sa.text("SELECT id, name, image_path FROM overwatch.map ORDER BY id"))
        maps = map_rows.all()

        map_migrated = 0
        for m_id, m_name, m_img in maps:
            if not m_img:
                logger.warning(f"Map '{m_name}' (ID: {m_id}) has empty image_path.")
                continue

            # Check if it is external
            is_external = m_img.startswith("http") and not any(host in m_img for host in s3_hosts)
            if not is_external:
                logger.debug(f"Skipping map '{m_name}' — image is already internal or local: {m_img}")
                continue

            # Construct key
            ext = "png"
            parsed = urlparse(m_img.split("?")[0])
            if "." in parsed.path.split("/")[-1]:
                ext = parsed.path.split(".")[-1].lower()
            m_slug = _slugify_name(m_name)
            key = f"assets/overwatch/maps/{m_slug}.{ext}"

            logger.info(f"Migrating map '{m_name}': {m_img} -> {key}")

            if dry_run:
                logger.info(f"[DRY-RUN] Would download {m_img} and upload to key '{key}'")
                map_migrated += 1
                continue

            # Download
            try:
                resp = await http_client.get(m_img)
                resp.raise_for_status()
                data = resp.content
            except Exception as e:
                logger.error(f"Failed to download image for map '{m_name}' from {m_img}: {e}")
                continue

            # Content type guessing
            content_type = resp.headers.get("content-type") or mimetypes.guess_type(m_img)[0] or f"image/{ext}"

            # Upload
            ok = await s3.put_object(key, data, content_type, public=True)
            if not ok:
                logger.error(f"Failed to upload map image to S3: {key}")
                continue

            # Update DB
            new_url = s3.get_public_url(key)
            await session.execute(
                sa.text("UPDATE overwatch.map SET image_path = :url WHERE id = :id"),
                {"url": new_url, "id": m_id},
            )
            logger.info(f"Updated map '{m_name}' image path in DB to {new_url}")
            map_migrated += 1

        # Commit everything
        if not dry_run:
            await session.commit()
            logger.info("Database changes committed successfully!")
        else:
            logger.info("[DRY-RUN] No changes committed to the database.")

    await s3.close()
    await engine.dispose()
    logger.info(f"Migration completed. Heroes migrated: {hero_migrated}, Maps migrated: {map_migrated}")


@click.command()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be done without uploading or updating DB",
)
def main(dry_run: bool) -> None:
    asyncio.run(migrate(dry_run))


if __name__ == "__main__":
    main()
