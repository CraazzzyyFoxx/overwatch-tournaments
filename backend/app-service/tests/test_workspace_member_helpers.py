"""``get_or_create_workspace_member`` idempotency + ``add_member`` player_id
resolution (real-DB integration; mirrors the identity-service DB-skip pattern
in ``backend/identity-service/tests/test_signup_provisions_player.py``).

Every workspace/player row created here is rolled back at the end of the test
(the session is opened, used, then rolled back — never committed) so the test
leaves no residue in the dev DB. Skips cleanly when the DB is unreachable /
is production.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa

from shared.models.user import User
from shared.models.workspace import Workspace, WorkspaceMember
from shared.repository import get_or_create_workspace_member
from shared.services.division_grid_access import get_default_division_grid_version_id
from src.services.workspace import service as workspace_service


@pytest.fixture
def db_session():
    """Yield a live AsyncSession, or skip the test if the DB is unreachable.

    Probes with ``select current_database()`` (mirrors the app-service ``rpc``
    fixture / identity-service's ``db_session`` fixture) and hard-guards
    against ever running against a production database. The session is never
    committed by these tests, so nothing written here persists.
    """
    from src.core import db as db_module

    async def _probe_and_open():
        session = db_module.async_session_maker()
        dbname = (await session.execute(sa.text("select current_database()"))).scalar()
        return session, dbname

    try:
        session, dbname = asyncio.run(_probe_and_open())
    except Exception as exc:  # noqa: BLE001 -- any connect failure => skip, not fail
        pytest.skip(f"database unreachable: {exc}")
        return

    if dbname in {"anak_v5", "anak_prod"}:
        asyncio.run(session.close())
        pytest.skip("refusing to run integration tests against production")
        return

    try:
        yield session
    finally:
        asyncio.run(session.rollback())
        asyncio.run(session.close())


async def _make_player(session, *, auth_user_id: int | None = None) -> User:
    suffix = uuid.uuid4().hex[:12]
    player = User(name=f"wsmember_{suffix}", auth_user_id=auth_user_id)
    session.add(player)
    await session.flush()
    return player


async def _make_workspace(session) -> Workspace:
    suffix = uuid.uuid4().hex[:12]
    grid_version_id = await get_default_division_grid_version_id(session)
    if grid_version_id is None:
        pytest.skip("no default division grid version configured in dev DB")
    workspace = Workspace(
        slug=f"wsmember-test-{suffix}",
        name=f"WS Member Test {suffix}",
        default_division_grid_version_id=grid_version_id,
    )
    session.add(workspace)
    await session.flush()
    return workspace


def test_get_or_create_workspace_member_is_idempotent(db_session) -> None:
    async def _run():
        workspace = await _make_workspace(db_session)
        player = await _make_player(db_session)

        first = await get_or_create_workspace_member(
            db_session, workspace_id=workspace.id, player_id=player.id
        )
        second = await get_or_create_workspace_member(
            db_session, workspace_id=workspace.id, player_id=player.id
        )
        return first, second

    first, second = asyncio.run(_run())

    assert first.id == second.id
    assert first.workspace_id == second.workspace_id == first.workspace_id
    assert first.player_id == second.player_id == first.player_id


def test_get_or_create_workspace_member_distinct_players_distinct_rows(db_session) -> None:
    async def _run():
        workspace = await _make_workspace(db_session)
        player_a = await _make_player(db_session)
        player_b = await _make_player(db_session)

        member_a = await get_or_create_workspace_member(
            db_session, workspace_id=workspace.id, player_id=player_a.id
        )
        member_b = await get_or_create_workspace_member(
            db_session, workspace_id=workspace.id, player_id=player_b.id
        )
        return member_a, member_b

    member_a, member_b = asyncio.run(_run())

    assert member_a.id != member_b.id
    assert member_a.player_id != member_b.player_id


def test_add_member_creates_row_anchored_on_player_id(db_session) -> None:
    async def _run():
        workspace = await _make_workspace(db_session)
        player = await _make_player(db_session, auth_user_id=None)
        # add_member resolves player_id from auth_user_id; give the player a
        # (fake, non-FK-checked-here) auth_user_id to resolve through.
        player.auth_user_id = 999_000_001
        await db_session.flush()

        member = await workspace_service.add_member(db_session, workspace.id, player.auth_user_id)
        row = await db_session.execute(
            sa.select(WorkspaceMember).where(WorkspaceMember.id == member.id)
        )
        return member, row.scalar_one()

    member, row = asyncio.run(_run())

    assert row.player_id == member.player_id
    assert not hasattr(WorkspaceMember, "auth_user_id")
    assert not hasattr(WorkspaceMember, "role")
