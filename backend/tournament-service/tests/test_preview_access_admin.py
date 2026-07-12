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
from pathlib import Path

import pytest
import sqlalchemy as sa


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


@pytest.fixture
def db_session():
    from src.core import db as db_module

    async def _probe_and_open():
        session = db_module.async_session_maker()
        dbname = (await session.execute(sa.text("select current_database()"))).scalar()
        return session, dbname

    try:
        session, dbname = asyncio.run(_probe_and_open())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
        return

    if dbname in {"anak_v5", "anak_prod"}:
        asyncio.run(session.close())
        pytest.skip("refusing to run integration tests against production")
        return

    try:
        yield session
    finally:
        asyncio.run(session.close())


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


async def _cleanup(session, *, workspace_id: int) -> None:
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.commit()


def test_add_list_remove_idempotent(db_session) -> None:
    async def _run():
        ws_id, tid, uid = await _seed(db_session)

        first = await preview_access_service.add_preview_access(db_session, tid, uid)
        again = await preview_access_service.add_preview_access(db_session, tid, uid)
        listed = await preview_access_service.list_preview_access(db_session, tid)
        await preview_access_service.remove_preview_access(db_session, tid, uid)
        after = await preview_access_service.list_preview_access(db_session, tid)
        return ws_id, first, again, listed, after

    try:
        ws_id, first, again, listed, after = asyncio.run(_run())
        assert first.id == again.id  # idempotent add
        assert len(listed) == 1
        assert listed[0].auth_user_id is not None
        assert after == []  # removed
    finally:
        asyncio.run(_cleanup(db_session, workspace_id=ws_id))
