"""Tests for the realtime-event retention job (`serve.purge_stale_realtime_events`).

Real-DB integration test (mirroring the skip pattern of
`test_auto_transitions.py`): the DB is probed once and any connection failure
skips cleanly; the test refuses to run against a production database. Proves
the scope boundary (design: docs/plans/2026-08-24-realtime-shared-library.md
§4.2/D2/D10) — only stale BRACKET- and INVALIDATION-topic rows are deleted,
never pregame/draft rows (no upper bound on session duration) or recent rows of
either family.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _ensure_test_env() -> None:
    env = {
        "DEBUG": "true",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)


_ensure_test_env()

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

import importlib  # noqa: E402

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from shared.models.platform.realtime import WorkspaceEvent  # noqa: E402


@asynccontextmanager
async def _db_sessions():
    """Yield a fresh per-test session factory, or skip if the DB is unreachable.

    Pooled asyncpg connections are bound to the event loop that created them,
    so a fresh NullPool engine per test avoids reusing a connection across
    `asyncio.run()` calls. Probes with `select current_database()` and hard-
    guards against ever running against a production database.
    """
    from src.core import config

    engine = create_async_engine(config.settings.db_url_asyncpg, poolclass=NullPool)
    try:
        try:
            async with engine.connect() as conn:
                dbname = (await conn.execute(sa.text("select current_database()"))).scalar()
        except Exception as exc:  # noqa: BLE001 -- any connect failure => skip, not fail
            pytest.skip(f"database unreachable: {exc}")
        if dbname in {"anak_v5", "anak_prod"}:
            pytest.skip("refusing to run integration tests against production")
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def _bracket_topic(tournament_id: int) -> str:
    return f"tournament:{tournament_id}:bracket"


async def _seed(session_maker, *, tournament_id: int, encounter_id: int) -> dict[str, int]:
    now = datetime.now(UTC)
    old = now - timedelta(days=10)
    recent = now - timedelta(days=1)

    rows = {
        "old_bracket": WorkspaceEvent(
            topic=_bracket_topic(tournament_id),
            event_type="tournament.updated",
            tournament_id=tournament_id,
            schema_version=1,
            payload={"tournament_id": tournament_id, "reason": "bracket_changed"},
            occurred_at=old,
        ),
        "recent_bracket": WorkspaceEvent(
            topic=_bracket_topic(tournament_id),
            event_type="tournament.updated",
            tournament_id=tournament_id,
            schema_version=1,
            payload={"tournament_id": tournament_id, "reason": "bracket_changed"},
            occurred_at=recent,
        ),
        "old_invalidation": WorkspaceEvent(
            topic=f"tournament:{tournament_id}:invalidation",
            event_type="cache.invalidated",
            tournament_id=tournament_id,
            schema_version=1,
            payload={"resources": ["tournament.encounters"]},
            occurred_at=old,
        ),
        "recent_invalidation": WorkspaceEvent(
            topic=f"tournament:{tournament_id}:invalidation",
            event_type="cache.invalidated",
            tournament_id=tournament_id,
            schema_version=1,
            payload={"resources": ["tournament.encounters"]},
            occurred_at=recent,
        ),
        "old_draft": WorkspaceEvent(
            topic=f"tournament:{tournament_id}:draft",
            event_type="draft.updated",
            tournament_id=tournament_id,
            schema_version=1,
            payload={"tournament_id": tournament_id},
            occurred_at=old,
        ),
        "old_map_veto": WorkspaceEvent(
            topic=f"encounter:{encounter_id}:map-veto",
            event_type="map_veto.updated",
            schema_version=1,
            payload={"encounter_id": encounter_id},
            occurred_at=old,
        ),
    }

    async with session_maker() as session:
        session.add_all(rows.values())
        await session.flush()
        ids = {name: row.id for name, row in rows.items()}
        await session.commit()
    return ids


async def _surviving_ids(session_maker, ids: dict[str, int]) -> set[int]:
    async with session_maker() as session:
        result = await session.execute(sa.select(WorkspaceEvent.id).where(WorkspaceEvent.id.in_(ids.values())))
        return set(result.scalars().all())


async def _cleanup(session_maker, ids: dict[str, int]) -> None:
    async with session_maker() as session:
        await session.execute(sa.delete(WorkspaceEvent).where(WorkspaceEvent.id.in_(ids.values())))
        await session.commit()


def test_purge_deletes_only_stale_bracket_and_invalidation_rows() -> None:
    async def _run():
        worker = importlib.import_module("serve")

        async with _db_sessions() as session_maker:
            suffix = uuid.uuid4().int % 1_000_000
            ids = await _seed(session_maker, tournament_id=900_000 + suffix, encounter_id=900_000 + suffix)

            try:
                await worker.purge_stale_realtime_events(session_maker)
                return await _surviving_ids(session_maker, ids), ids
            finally:
                await _cleanup(session_maker, ids)

    surviving, ids = asyncio.run(_run())

    assert ids["old_bracket"] not in surviving
    assert ids["recent_bracket"] in surviving
    assert ids["old_invalidation"] not in surviving
    assert ids["recent_invalidation"] in surviving
    assert ids["old_draft"] in surviving
    assert ids["old_map_veto"] in surviving
