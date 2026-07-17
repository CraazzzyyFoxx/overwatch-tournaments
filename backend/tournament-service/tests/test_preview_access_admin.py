"""DB-backed tests for the preview-access allowlist service (issue #115).

Real-DB skip pattern (see test_registration_self_register_gate.py). Covers
idempotent add, list, and remove. The workspace-admin gate itself is pure
``AuthUser.is_workspace_admin`` logic, unit-covered in
shared/tests/test_tournament_visibility.py.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _ensure_test_env() -> None:
    env = {
        "DEBUG": "true",
        "PROJECT_URL": "http://localhost",
        "RABBITMQ_URL": "amqp://guest:guest@localhost:5672",
        "REDIS_URL": "redis://localhost:6379/0",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "anak_dev",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)


_ensure_test_env()

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core import enums  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.services.division_grid_access import get_default_division_grid_version_id  # noqa: E402
from src.services.admin import preview_access as preview_access_service  # noqa: E402


@asynccontextmanager
async def _db_sessions():
    """Yield a fresh per-test session factory, or skip if the DB is unreachable.

    Pooled asyncpg connections are bound to the event loop that created them,
    so the module-global engine cannot be shared across ``asyncio.run()``
    calls: each test gets its own NullPool engine, created and disposed inside
    the test's single event loop. Probes with ``select current_database()``
    and hard-guards against ever running against a production database.
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


async def _seed(session):
    suffix = uuid.uuid4().hex[:12]
    grid_version_id = await get_default_division_grid_version_id(session)
    if grid_version_id is None:
        pytest.skip("no default division grid version configured in dev DB")
    ws = Workspace(
        slug=f"pa-test-{suffix}",
        name=f"Preview Access Test {suffix}",
        default_division_grid_version_id=grid_version_id,
    )
    session.add(ws)
    await session.flush()
    tournament = Tournament(
        workspace_id=ws.id,
        name=f"Preview Access Tournament {suffix}",
        status=enums.TournamentStatus.DRAFT,
        is_hidden=True,
    )
    session.add(tournament)
    await session.flush()
    auth_user = AuthUser(
        email=f"pa-{suffix}@example.com", username=f"pa_{suffix}", hashed_password="x"
    )
    session.add(auth_user)
    await session.flush()
    await session.commit()
    return ws.id, tournament.id, auth_user.id


async def _cleanup(session_maker, *, workspace_id: int) -> None:
    async with session_maker() as session:
        await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
        await session.commit()


def test_add_list_remove_idempotent() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                ws_id, tid, uid = await _seed(session)

            try:
                async with session_maker() as session:
                    first = await preview_access_service.add_preview_access(session, tid, uid)
                    again = await preview_access_service.add_preview_access(session, tid, uid)
                    listed = await preview_access_service.list_preview_access(session, tid)
                    await preview_access_service.remove_preview_access(session, tid, uid)
                    after = await preview_access_service.list_preview_access(session, tid)
                    return (
                        first.id,
                        again.id,
                        [entry.auth_user_id for entry in listed],
                        list(after),
                    )
            finally:
                await _cleanup(session_maker, workspace_id=ws_id)

    first_id, again_id, listed_user_ids, after = asyncio.run(_run())

    assert first_id == again_id  # idempotent add
    assert len(listed_user_ids) == 1
    assert listed_user_ids[0] is not None
    assert after == []  # removed
