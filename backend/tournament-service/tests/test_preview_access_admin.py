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

from shared.core import enums  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.services.division_grid.access import get_default_division_grid_version_id  # noqa: E402
from shared.testing import real_db_sessionmaker as _db_sessions  # noqa: E402
from src.services.admin import preview_access as preview_access_service  # noqa: E402


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
        # NOT NULL and globally unique; production writes go through
        # `generate_unique_tournament_slug`, which this factory bypasses.
        slug=f"pa-{suffix}",
        status=enums.TournamentStatus.DRAFT,
        is_hidden=True,
    )
    session.add(tournament)
    await session.flush()
    auth_user = AuthUser(email=f"pa-{suffix}@example.com", username=f"pa_{suffix}", hashed_password="x")
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
                    first = await preview_access_service.preview_access_service.add_preview_access(session, tid, uid)
                    again = await preview_access_service.preview_access_service.add_preview_access(session, tid, uid)
                    listed = await preview_access_service.preview_access_service.list_preview_access(session, tid)
                    await preview_access_service.preview_access_service.remove_preview_access(session, tid, uid)
                    after = await preview_access_service.preview_access_service.list_preview_access(session, tid)
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
