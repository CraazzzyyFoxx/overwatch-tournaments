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
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

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

from shared.core.social import SocialProvider  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from src.services.registration import service as reg_service  # noqa: E402


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


async def _battle_tag_account(session, *, user_id: int, battle_tag: str):
    from shared.services import social_identity

    return await social_identity.upsert_social_account(
        session, user_id=user_id, provider=SocialProvider.BATTLENET, username=battle_tag
    )


def _registration(*, battle_tag: str):
    # BalancerRegistration no longer carries auth_user_id or user_id (identity is
    # anchored via workspace_member_id — dbarch02); ensure_player_identity takes
    # the registering account's auth_user_id as an explicit keyword argument
    # instead of reading it off the row. tournament_id=None makes the member
    # anchoring a no-op (no workspace resolvable), which keeps these tests
    # focused on player reconciliation without provisioning workspaces.
    return SimpleNamespace(
        id=None,
        tournament_id=None,
        battle_tag=battle_tag,
        smurf_tags_json=None,
        workspace_member_id=None,
        deleted_at=None,
    )


def test_reuses_account_owned_player_and_attaches_new_battle_tag() -> None:
    """Case (a): the auth account already owns a player (no prior battletag) —
    the new battletag is attached to that player, not a fresh one."""
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        async with _db_sessions() as session_maker:
            battle_tag = f"Acct{suffix}#111"

            async with session_maker() as session:
                auth_user = await _make_auth_user(session, suffix)
                player = await _make_player(session, suffix, auth_user_id=auth_user.id)
                await session.commit()
                auth_user_id, player_id = auth_user.id, player.id

            async with session_maker() as session:
                registration = _registration(battle_tag=battle_tag)
                resolved = await reg_service.ensure_player_identity(
                    session, registration, auth_user_id=auth_user_id
                )
                await session.commit()

            async with session_maker() as session:
                from shared.services import social_identity

                account = await social_identity.find_by_handle(
                    session, provider=SocialProvider.BATTLENET, username=battle_tag
                )
                account_user_id = None if account is None else account.user_id

            return player_id, resolved, account is not None, account_user_id

    player_id, resolved, account_found, account_user_id = asyncio.run(_run())
    assert resolved == player_id
    assert account_found
    assert account_user_id == player_id


def test_colliding_shadow_battle_tag_collapses_onto_account_owned_player() -> None:
    """Case (b): a distinct shadow player already owns the battletag — its
    battlenet identity is collapsed onto the account-owned player instead of
    being left split across two ``players.user`` rows."""
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        async with _db_sessions() as session_maker:
            battle_tag = f"Collide{suffix}#222"

            async with session_maker() as session:
                auth_user = await _make_auth_user(session, suffix)
                owned_player = await _make_player(session, f"owned{suffix}", auth_user_id=auth_user.id)
                shadow_player = await _make_player(session, f"shadow{suffix}")
                await _battle_tag_account(session, user_id=shadow_player.id, battle_tag=battle_tag)
                await session.commit()
                auth_user_id = auth_user.id
                owned_id, shadow_id = owned_player.id, shadow_player.id

            async with session_maker() as session:
                registration = _registration(battle_tag=battle_tag)
                resolved = await reg_service.ensure_player_identity(
                    session, registration, auth_user_id=auth_user_id
                )
                await session.commit()

            async with session_maker() as session:
                from shared.services import social_identity

                account = await social_identity.find_by_handle(
                    session, provider=SocialProvider.BATTLENET, username=battle_tag
                )
                remaining_on_shadow = await social_identity.list_social_accounts(session, shadow_id)
                account_user_id = None if account is None else account.user_id
                remaining_providers = [a.provider for a in remaining_on_shadow]

            return owned_id, shadow_id, resolved, account is not None, account_user_id, remaining_providers

    owned_id, shadow_id, resolved, account_found, account_user_id, remaining_providers = asyncio.run(_run())

    # The registration resolves to the account-owned player, not the shadow.
    assert resolved == owned_id
    assert resolved != shadow_id

    # The handle now belongs to the account-owned player, not the shadow.
    assert account_found
    assert account_user_id == owned_id
    assert all(provider != SocialProvider.BATTLENET for provider in remaining_providers)


def test_shadow_only_no_account_falls_back_to_battle_tag_dedup() -> None:
    """Case (c): no auth account owns a player — behaviour is exactly the
    pre-existing battletag dedup (shadow player reused, no auth link)."""
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        async with _db_sessions() as session_maker:
            battle_tag = f"ShadowOnly{suffix}#333"

            async with session_maker() as session:
                shadow_player = await _make_player(session, f"onlyshadow{suffix}")
                await _battle_tag_account(session, user_id=shadow_player.id, battle_tag=battle_tag)
                await session.commit()
                shadow_id = shadow_player.id

            async with session_maker() as session:
                registration = _registration(battle_tag=battle_tag)
                resolved = await reg_service.ensure_player_identity(session, registration, auth_user_id=None)
                await session.commit()

            return shadow_id, resolved

    shadow_id, resolved = asyncio.run(_run())
    assert resolved == shadow_id
