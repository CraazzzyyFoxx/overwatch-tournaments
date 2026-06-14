"""Migrate achievement images from frontend/public/achievements/ to S3.

Uploads images per workspace: assets/achievements/{workspace_slug}/{slug}.{ext}
Each workspace gets its own copy so images can be customized independently.

Updates image_url in:
  - achievements.achievement (legacy)
  - achievements.rule (new engine, per workspace)

Usage:
    cd backend/
    python -m scripts.migrate_achievement_images
    python -m scripts.migrate_achievement_images --dry-run
"""

import asyncio
import mimetypes
from pathlib import Path

import click
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


async def migrate(frontend_dir: Path, dry_run: bool = False) -> None:
    if not frontend_dir.is_dir():
        logger.error(f"Directory not found: {frontend_dir}")
        return

    s3 = S3Client(
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        endpoint_url=settings.s3_endpoint_url,
        bucket_name=settings.s3_bucket_name,
        public_url=settings.s3_public_url,
    )
    await s3.start()

    engine = create_async_engine(settings.db_url_asyncpg)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    image_files = sorted(
        p for p in frontend_dir.iterdir()
        if p.suffix in (".webp", ".png", ".jpg", ".jpeg", ".gif")
    )
    logger.info(f"Found {len(image_files)} image files in {frontend_dir}")

    async with session_maker() as session:
        # Load workspaces
        ws_rows = await session.execute(sa.text("SELECT id, slug, name FROM workspace ORDER BY id"))
        workspaces = ws_rows.all()
        if not workspaces:
            logger.error("No workspaces found")
            return

        logger.info(f"Found {len(workspaces)} workspace(s): {', '.join(f'{w[1]} (id={w[0]})' for w in workspaces)}")

        # Report before
        for ws_id, ws_slug, _ in workspaces:
            null_count = await session.scalar(
                sa.text("SELECT COUNT(*) FROM achievements.rule WHERE workspace_id = :ws_id AND image_url IS NULL"),
                {"ws_id": ws_id},
            )
            total_count = await session.scalar(
                sa.text("SELECT COUNT(*) FROM achievements.rule WHERE workspace_id = :ws_id"),
                {"ws_id": ws_id},
            )
            logger.info(f"  [{ws_slug}] Before: {null_count}/{total_count} rules with NULL image_url")

        total_uploaded = 0
        total_db_updated = 0

        for ws_id, ws_slug, ws_name in workspaces:
            ws_uploaded = 0
            ws_db_updated = 0

            for image_path in image_files:
                slug = image_path.stem
                ext = image_path.suffix.lstrip(".")
                key = f"assets/achievements/{ws_slug}/{slug}.{ext}"
                content_type = mimetypes.guess_type(str(image_path))[0] or "image/webp"

                if dry_run:
                    public_url = f"{settings.s3_public_url}/{key}"
                    logger.debug(f"[DRY RUN] [{ws_slug}] {slug} -> {key}")
                    ws_uploaded += 1
                    continue

                data = image_path.read_bytes()
                ok = await s3.put_object(key, data, content_type, public=True)
                if not ok:
                    logger.error(f"[{ws_slug}] Failed to upload: {key}")
                    continue

                public_url = s3.get_public_url(key)
                ws_uploaded += 1

                # Update rule for this workspace only
                result = await session.execute(
                    sa.text("""
                        UPDATE achievements.rule
                        SET image_url = :url
                        WHERE workspace_id = :ws_id AND slug = :slug
                          AND (image_url IS NULL OR image_url != :url)
                    """),
                    {"url": public_url, "slug": slug, "ws_id": ws_id},
                )
                ws_db_updated += result.rowcount

            logger.info(f"  [{ws_slug}] Uploaded: {ws_uploaded}, DB updated: {ws_db_updated}")
            total_uploaded += ws_uploaded
            total_db_updated += ws_db_updated

        if not dry_run:
            await session.commit()

            # Report after
            for ws_id, ws_slug, _ in workspaces:
                has_image = await session.scalar(
                    sa.text("SELECT COUNT(*) FROM achievements.rule WHERE workspace_id = :ws_id AND image_url IS NOT NULL"),
                    {"ws_id": ws_id},
                )
                still_null = await session.scalar(
                    sa.text("SELECT COUNT(*) FROM achievements.rule WHERE workspace_id = :ws_id AND image_url IS NULL"),
                    {"ws_id": ws_id},
                )
                logger.info(f"  [{ws_slug}] After: {has_image} with image, {still_null} still NULL")

    await s3.close()
    await engine.dispose()

    logger.info(
        f"Done: {total_uploaded} uploaded to S3, "
        f"{total_db_updated} rule rows updated"
    )


@click.command()
@click.option(
    "--frontend-dir",
    type=click.Path(path_type=Path),
    default=Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "achievements",
    help="Path to frontend/public/achievements/ directory",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be done without uploading or updating DB",
)
def main(frontend_dir: Path, dry_run: bool) -> None:
    asyncio.run(migrate(frontend_dir, dry_run))


if __name__ == "__main__":
    main()
