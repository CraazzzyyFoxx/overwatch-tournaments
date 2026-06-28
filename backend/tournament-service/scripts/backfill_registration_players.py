"""One-time backfill of player identity for existing registrations.

For every non-deleted registration in an active (not completed/archived)
tournament, ensures a ``players.user`` + battlenet ``social_account`` exists for
its battle tags and links ``registration.user_id`` — the same provisioning that
now runs on new submissions. This lets already-registered players (who weren't yet
in the analytics system) be picked up by rank collection / the open-profile gate.

Idempotent (dedups by normalized battlenet handle), so safe to re-run.

Run once from the ``backend/`` directory so the service ``.env`` is picked up::

    cd backend
    PYTHONPATH=tournament-service uv run python tournament-service/scripts/backfill_registration_players.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "tournament-service"))

import sqlalchemy as sa  # noqa: E402
from shared.core import enums  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src import models  # noqa: E402
from src.core import config  # noqa: E402
from src.services.registration.service import ensure_player_identity  # noqa: E402

_INACTIVE = (
    enums.TournamentStatus.COMPLETED.value,
    enums.TournamentStatus.ARCHIVED.value,
)


async def main() -> None:
    # Dedicated pgBouncer-safe engine: no statement_timeout startup parameter
    # (rejected by pgBouncer) and statement_cache_size=0 (safe under transaction
    # pooling, where asyncpg's prepared-statement cache otherwise breaks).
    engine = create_async_engine(
        config.settings.db_url_asyncpg,
        connect_args={"statement_cache_size": 0, "server_settings": {}},
        pool_pre_ping=True,
    )
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_maker() as session:
            registrations = (
                (
                    await session.execute(
                        sa.select(models.BalancerRegistration)
                        .join(
                            models.Tournament,
                            models.Tournament.id == models.BalancerRegistration.tournament_id,
                        )
                        .where(
                            models.BalancerRegistration.deleted_at.is_(None),
                            models.BalancerRegistration.battle_tag.isnot(None),
                            models.Tournament.status.notin_(_INACTIVE),
                        )
                    )
                )
                .scalars()
                .all()
            )

            for registration in registrations:
                await ensure_player_identity(session, registration)
            await session.commit()
            print(f"Backfilled player identity for {len(registrations)} registrations.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
