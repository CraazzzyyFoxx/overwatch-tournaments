"""DB-backed reconciliation tests for ``ensure_player_identity`` (identity/workspace
refactor Task 5).

``ensure_player_identity`` now prefers a player already linked to the
registering auth account (``players.user.auth_user_id``) over the historical
battletag-dedup lookup, and — when a *different* shadow player already owns
that battletag — collapses the shadow's battlenet identity onto the
account-owned player rather than silently splitting it across two rows.

These are real-DB integration tests (mirroring the skip pattern used by
``identity-service/tests/test_player_link_service.py``): the DB is probed once
per test and any connection failure (e.g. anak_dev unreachable) skips cleanly
instead of failing, and the tests refuse to run against a production database.
The narrower precedence/wiring behaviour is covered without a DB in
``test_registration_sheet_sync_identity.py``.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

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

from shared.core.social import SocialProvider  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.social import SocialAccount  # noqa: E402
from shared.models.identity.user import User  # noqa: E402

from src.services.registration import service as reg_service  # noqa: E402


@pytest.fixture
def db_session():
    """Yield a live AsyncSession, or skip the test if the DB is unreachable.

    Probes with ``select current_database()`` and hard-guards against ever
    running against a production database.
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


async def _make_auth_user(session, suffix: str) -> AuthUser:
    auth_user = AuthUser(
        email=f"epi-{suffix}@example.com",
        username=f"epi_{suffix}",
        hashed_password="x",
    )
    session.add(auth_user)
    await session.flush()
    return auth_user


async def _make_player(session, suffix: str, *, auth_user_id: int | None = None) -> User:
    player = User(name=f"epi_player_{suffix}", auth_user_id=auth_user_id)
    session.add(player)
    await session.flush()
    return player


async def _battle_tag_account(session, *, user_id: int, battle_tag: str) -> SocialAccount:
    from shared.services import social_identity

    return await social_identity.upsert_social_account(
        session, user_id=user_id, provider=SocialProvider.BATTLENET, username=battle_tag
    )


def _registration(*, battle_tag: str, user_id: int | None = None):
    # BalancerRegistration no longer carries auth_user_id (identity is anchored via
    # workspace_member); ensure_player_identity now takes the registering account's
    # auth_user_id as an explicit keyword argument instead of reading it off the row.
    return SimpleNamespace(
        battle_tag=battle_tag,
        smurf_tags_json=None,
        user_id=user_id,
    )


def test_reuses_account_owned_player_and_attaches_new_battle_tag(db_session) -> None:
    """Case (a): the auth account already owns a player (no prior battletag) —
    the new battletag is attached to that player, not a fresh one."""
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        auth_user = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix, auth_user_id=auth_user.id)
        await db_session.commit()

        battle_tag = f"Acct{suffix}#111"
        registration = _registration(battle_tag=battle_tag)
        resolved = await reg_service.ensure_player_identity(db_session, registration, auth_user_id=auth_user.id)
        await db_session.commit()
        return player.id, resolved, battle_tag

    player_id, resolved, battle_tag = asyncio.run(_run())
    assert resolved == player_id

    async def _verify():
        from shared.services import social_identity

        account = await social_identity.find_by_handle(
            db_session, provider=SocialProvider.BATTLENET, username=battle_tag
        )
        return account

    account = asyncio.run(_verify())
    assert account is not None
    assert account.user_id == player_id


def test_colliding_shadow_battle_tag_collapses_onto_account_owned_player(db_session) -> None:
    """Case (b): a distinct shadow player already owns the battletag — its
    battlenet identity is collapsed onto the account-owned player instead of
    being left split across two ``players.user`` rows."""
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        auth_user = await _make_auth_user(db_session, suffix)
        owned_player = await _make_player(db_session, f"owned{suffix}", auth_user_id=auth_user.id)
        shadow_player = await _make_player(db_session, f"shadow{suffix}")
        battle_tag = f"Collide{suffix}#222"
        await _battle_tag_account(db_session, user_id=shadow_player.id, battle_tag=battle_tag)
        await db_session.commit()

        registration = _registration(battle_tag=battle_tag)
        resolved = await reg_service.ensure_player_identity(db_session, registration, auth_user_id=auth_user.id)
        await db_session.commit()
        return owned_player.id, shadow_player.id, resolved, battle_tag

    owned_id, shadow_id, resolved, battle_tag = asyncio.run(_run())

    # The registration resolves to the account-owned player, not the shadow.
    assert resolved == owned_id
    assert resolved != shadow_id

    async def _verify():
        from shared.services import social_identity

        account = await social_identity.find_by_handle(
            db_session, provider=SocialProvider.BATTLENET, username=battle_tag
        )
        remaining_on_shadow = await social_identity.list_social_accounts(db_session, shadow_id)
        return account, remaining_on_shadow

    account, remaining_on_shadow = asyncio.run(_verify())
    # The handle now belongs to the account-owned player, not the shadow.
    assert account is not None
    assert account.user_id == owned_id
    assert all(a.provider != SocialProvider.BATTLENET for a in remaining_on_shadow)


def test_shadow_only_no_account_falls_back_to_battle_tag_dedup(db_session) -> None:
    """Case (c): no auth account owns a player — behaviour is exactly the
    pre-existing battletag dedup (shadow player reused, no auth link)."""
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        shadow_player = await _make_player(db_session, f"onlyshadow{suffix}")
        battle_tag = f"ShadowOnly{suffix}#333"
        await _battle_tag_account(db_session, user_id=shadow_player.id, battle_tag=battle_tag)
        await db_session.commit()

        registration = _registration(battle_tag=battle_tag)
        resolved = await reg_service.ensure_player_identity(db_session, registration, auth_user_id=None)
        await db_session.commit()
        return shadow_player.id, resolved

    shadow_id, resolved = asyncio.run(_run())
    assert resolved == shadow_id
