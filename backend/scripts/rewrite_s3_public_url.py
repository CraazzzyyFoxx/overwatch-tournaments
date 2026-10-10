"""Rewrite stored image URLs from an old S3 public base to a new one (e.g. a CDN).

Image columns hold absolute URLs built from ``S3_PUBLIC_URL`` at upload time,
so changing that setting leaves existing rows on the old host. Old URLs keep
loading, but code that maps a URL back to its S3 key (catalog mirror, division
grid / achievement import) only recognises the current base.

History (audit/outbox/discord JSON) is deliberately left alone.

Usage:
    cd backend/
    python -m scripts.rewrite_s3_public_url --old https://s3.twcstorage.ru/<bucket> --dry-run
    python -m scripts.rewrite_s3_public_url --old https://s3.twcstorage.ru/<bucket>
    # --new defaults to S3_PUBLIC_URL
"""

import asyncio
from pathlib import Path

import click
import sqlalchemy as sa
from loguru import logger
from pydantic_settings import SettingsConfigDict
from sqlalchemy.ext.asyncio import create_async_engine

from shared.core.config import BaseServiceSettings

_env_dir = Path(__file__).resolve().parent.parent / "env"

COLUMNS = (
    ("public", "workspace", "icon_url"),
    ("public", "division_grid_tier", "icon_url"),
    ("auth", "user", "avatar_url"),
    ("players", "user", "avatar_url"),
    ("tournament", "tournament", "logo_url"),
    ("tournament", "tournament", "cover_image_url"),
    ("tournament", "team", "image_url"),
    ("balancer", "registration_team", "image_url"),
    ("achievements", "rule", "image_url"),
    ("overwatch", "hero", "image_path"),
    ("overwatch", "map", "image_path"),
    ("overwatch", "gamemode", "image_path"),
)


class _ScriptSettings(BaseServiceSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_env_dir / "common.env"), ".env", ".env.prod"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


async def rewrite(old: str, new: str, dry_run: bool) -> None:
    settings = _ScriptSettings()
    old, new = old.rstrip("/") + "/", new.rstrip("/") + "/"
    engine = create_async_engine(settings.db_url_asyncpg)
    total = 0
    async with engine.begin() as conn:
        for schema, table, column in COLUMNS:
            target = f'"{schema}"."{table}"'
            col = f'"{column}"'
            where = f"starts_with({col}, :old)"
            if dry_run:
                stmt = sa.text(f"SELECT count(*) FROM {target} WHERE {where}")
                count = (await conn.execute(stmt, {"old": old})).scalar_one()
            else:
                stmt = sa.text(f"UPDATE {target} SET {col} = :new || substr({col}, :cut) WHERE {where}")
                count = (await conn.execute(stmt, {"old": old, "new": new, "cut": len(old) + 1})).rowcount
            logger.info(f"{schema}.{table}.{column}: {count}")
            total += count
    await engine.dispose()
    logger.info(f"{'Would rewrite' if dry_run else 'Rewrote'} {total} rows: {old} -> {new}")


@click.command()
@click.option("--old", required=True, help="Previous public base, e.g. https://s3.twcstorage.ru/<bucket>")
@click.option("--new", default=None, help="New public base; defaults to S3_PUBLIC_URL")
@click.option("--dry-run", is_flag=True, help="Only count matching rows")
def main(old: str, new: str | None, dry_run: bool) -> None:
    new = new or _ScriptSettings().s3_public_url
    if not new:
        raise click.UsageError("--new not given and S3_PUBLIC_URL is unset")
    asyncio.run(rewrite(old, new, dry_run))


if __name__ == "__main__":
    main()
