"""Token payload workspace membership: joins through ``players.user`` and
derives ``WorkspaceMembership.role`` from RBAC now that ``workspace_member``
no longer stores ``auth_user_id``/``role`` (real-DB integration; mirrors the
DB-skip pattern in ``test_signup_provisions_player.py``).

Redis is never initialised in this test process, so the RBAC cache
read/write in ``_build_access_token_payload`` degrades gracefully to a
DB-only path (see ``session_cache.get_rbac``/``set_rbac`` catching the
``RuntimeError`` from an uninitialised client) — no live Redis required.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path


def _ensure_test_env() -> None:
    env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "anak_dev",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
        "JWT_SECRET_KEY": "test-secret",
        "DISCORD_CLIENT_ID": "discord-client",
        "DISCORD_CLIENT_SECRET": "discord-secret",
        "TWITCH_CLIENT_ID": "twitch-client",
        "TWITCH_CLIENT_SECRET": "twitch-secret",
        "BATTLENET_CLIENT_ID": "battlenet-client",
        "BATTLENET_CLIENT_SECRET": "battlenet-secret",
        "OAUTH_REDIRECT": "http://localhost:3000/auth/callback",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)


_ensure_test_env()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402

from shared.rbac import assign_workspace_system_role, ensure_workspace_system_roles  # noqa: E402
from shared.repository import get_or_create_workspace_member  # noqa: E402
from shared.services.division_grid_access import get_default_division_grid_version_id  # noqa: E402
from src import models, schemas  # noqa: E402
from src.services import auth_flows  # noqa: E402
from src.services.auth_token_helpers import _build_access_token_payload  # noqa: E402


@pytest.fixture
def db_session():
    """Yield a live AsyncSession, or skip the test if the DB is unreachable.

    Mirrors ``test_signup_provisions_player.py``'s ``db_session`` fixture.
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
        asyncio.run(session.close())


def test_token_payload_includes_workspace_membership_with_rbac_derived_role(db_session) -> None:
    """A user who is a member of workspace W (via player_id) gets a
    WorkspaceMembership for W with a non-empty ``role`` derived from RBAC,
    even though ``workspace_member.role`` no longer exists.
    """
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        # 1. Register a real auth user -> provisions a linked players.user row
        #    (Phase A: ``ensure_player_for_auth_user``).
        payload = schemas.UserRegister(
            email=f"tokenws-{suffix}@example.com",
            username=f"tokenws_{suffix}",
            password="correct-horse-battery",
        )
        auth_user = await auth_flows.register(db_session, payload)

        player = (
            await db_session.execute(
                sa.select(models.User).where(models.User.auth_user_id == auth_user.id)
            )
        ).scalar_one()

        # 2. Create a workspace and anchor a workspace_member row on player_id.
        grid_version_id = await get_default_division_grid_version_id(db_session)
        if grid_version_id is None:
            pytest.skip("no default division grid version configured in dev DB")
        workspace = models.Workspace(
            slug=f"tokenws-test-{suffix}",
            name=f"Token WS Test {suffix}",
            default_division_grid_version_id=grid_version_id,
        )
        db_session.add(workspace)
        await db_session.flush()

        await ensure_workspace_system_roles(db_session, workspace.id)
        await get_or_create_workspace_member(db_session, workspace_id=workspace.id, player_id=player.id)

        # 3. Assign the RBAC "admin" system role (workspace_member has no
        #    stored role column any more -- this is the only role signal).
        await assign_workspace_system_role(
            db_session, user_id=auth_user.id, workspace_id=workspace.id, role_name="admin"
        )
        await db_session.commit()

        # 4. Reload with RBAC eagerly loaded (mirrors token-issuance flow) and
        #    build the token payload.
        current_user = await db_session.get(models.AuthUser, auth_user.id)
        token_payload = await _build_access_token_payload(db_session, current_user)
        return workspace.id, token_payload

    workspace_id, token_payload = asyncio.run(_run())

    membership = next((m for m in token_payload.workspaces if m.workspace_id == workspace_id), None)
    assert membership is not None, token_payload.workspaces
    assert membership.role == "admin"
    assert "admin" in membership.rbac_roles
