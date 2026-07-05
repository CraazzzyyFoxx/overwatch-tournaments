"""Signup (password + OAuth) provisions the players.user identity backbone.

This is a real-DB integration test (mirrors the app-service ``rpc`` fixture
DB-skip pattern in ``backend/app-service/tests/conftest.py``): it registers a
user through the actual ``auth_flows.register`` -> ``AuthService.create_user``
path against a live Postgres and asserts a ``players.user`` row was created
with ``auth_user_id`` pointing back at the new auth user.

Identity-service has no shared conftest.py (each test file sets up its own
env defaults per existing convention — see test_auth_sessions.py). The DB is
probed once per test; any connection failure (e.g. anak_dev unreachable)
skips cleanly instead of failing, and the test refuses to run against a
production database name.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa


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

from shared.models.identity.user import User  # noqa: E402

from src.schemas.auth import UserRegister  # noqa: E402
from src.services import auth_flows  # noqa: E402


@pytest.fixture
def db_session():
    """Yield a live AsyncSession, or skip the test if the DB is unreachable.

    Probes with ``select current_database()`` (mirrors
    ``backend/app-service/tests/conftest.py``'s ``rpc`` fixture) and hard-guards
    against ever running against a production database.
    """

    from src.core import db as db_module

    async def _probe_and_open():
        session = db_module.async_session_maker()
        dbname = (await session.execute(sa.text("select current_database()"))).scalar()
        return session, dbname

    try:
        session, dbname = asyncio.run(_probe_and_open())
    except Exception as exc:  # noqa: BLE001 — any connect failure => skip, not fail
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


def test_register_provisions_players_user(db_session) -> None:
    """Registering a new password-auth user creates a linked players.user row."""

    suffix = uuid.uuid4().hex[:10]
    payload = UserRegister(
        email=f"signup-{suffix}@example.com",
        username=f"signup_{suffix}",
        password="correct-horse-battery",
    )

    async def _run():
        auth_user = await auth_flows.register(db_session, payload)
        player = (
            await db_session.execute(sa.select(User).where(User.auth_user_id == auth_user.id))
        ).scalar_one_or_none()
        return auth_user, player

    auth_user, player = asyncio.run(_run())

    assert player is not None
    assert player.auth_user_id == auth_user.id
    assert player.name == auth_user.username
