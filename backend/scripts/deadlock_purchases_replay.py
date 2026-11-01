"""Replay every stored Deadlock match so it gains the ``purchase`` events the decoder now reads.

Each ``done`` deadlock-api job that is still its game's current provenance is published to
``stats.ingest.deadlock.replay`` with the revision seen here -- the queue the tournament-wide reprocess uses. The stats
worker redecodes the stored raw metadata (no deadlock-api request) and replaces the observation; a job superseded in
the meantime is refused as stale, never applied. Run after the decoder is deployed, with a deadlock stats worker up.

Safe to re-run: a replay rewrites the observation from the same raw bytes.

Usage:
    cd backend/
    python -m scripts.deadlock_purchases_replay --dry-run
    python -m scripts.deadlock_purchases_replay
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
import sqlalchemy as sa
from loguru import logger
from pydantic_settings import SettingsConfigDict
from sqlalchemy.ext.asyncio import create_async_engine

from shared.core.config import BaseServiceSettings
from shared.messaging.config import ingest_replay_queue
from shared.messaging.topology import declare_replay_queues, publish_required
from shared.models.stats import IngestJob, IngestJobStatus, StatsMatch
from shared.observability.broker import make_rabbit_broker
from shared.schemas.events import ProcessIngestJobEvent

_env_dir = Path(__file__).resolve().parent.parent / "env"
DISCIPLINE = "deadlock"


class _ScriptSettings(BaseServiceSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_env_dir / "common.env"), ".env", ".env.prod"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
    rabbitmq_url: str


async def replay(dry_run: bool) -> int:
    """Publish one replay request per current deadlock-api observation. Returns how many were (or would be) sent."""
    settings = _ScriptSettings()
    engine = create_async_engine(settings.db_url_asyncpg)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    sa.select(IngestJob.id, StatsMatch.revision)
                    .join(StatsMatch, StatsMatch.ingest_job_id == IngestJob.id)
                    .where(IngestJob.discipline == DISCIPLINE, IngestJob.status == IngestJobStatus.DONE)
                    .order_by(IngestJob.id)
                )
            ).all()
    finally:
        await engine.dispose()
    logger.info(f"{len(rows)} deadlock observations to replay")
    if dry_run or not rows:
        return len(rows)
    broker = make_rabbit_broker(settings.rabbitmq_url, logger=logger)
    await broker.connect()
    try:
        await declare_replay_queues(broker, DISCIPLINE)
        for job_id, revision in rows:
            await publish_required(
                broker,
                ingest_replay_queue(DISCIPLINE),
                ProcessIngestJobEvent(ingest_job_id=job_id, reparse_expected_revision=revision).model_dump_json(),
            )
    finally:
        await broker.stop()
    logger.info(f"{len(rows)} replays requested")
    return len(rows)


@click.command()
@click.option("--dry-run", is_flag=True, help="Count the observations and publish nothing.")
def main(dry_run: bool) -> None:
    asyncio.run(replay(dry_run))


if __name__ == "__main__":
    main()
