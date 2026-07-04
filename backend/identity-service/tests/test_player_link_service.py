"""PlayerLinkService over the single-link ``players.user.auth_user_id`` column.

Identity/workspace refactor Task 4: link/unlink/get now UPDATE
``players.user.auth_user_id`` instead of inserting/deleting ``auth.user_player``
M2M rows. The storage-round-trip cases are real-DB integration tests (mirroring
the DB-skip pattern in ``test_signup_provisions_player.py`` /
``backend/app-service/tests/conftest.py``): the DB is probed once per test and
any connection failure (e.g. anak_dev unreachable) skips cleanly instead of
failing, and the tests refuse to run against a production database name.

A separate DB-free unit test asserts that ``link_player`` still enforces the
Discord/Battle.net ownership verification gate (the storage swap must not weaken
it).
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from shared.core.errors import BaseAPIException as HTTPException


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

from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.user import User  # noqa: E402

from src.services import player_link_service as pls_module  # noqa: E402
from src.services.player_link_service import PlayerLinkService  # noqa: E402

# ---------------------------------------------------------------------------
# DB-free unit test: ownership verification gate is preserved.
# ---------------------------------------------------------------------------


def test_link_player_requires_oauth_ownership_gate() -> None:
    """``link_player`` must still run ownership verification before storing.

    With no OAuth connections on the (fake) session, ``_get_oauth_connections``
    raises 400 and the link never touches ``auth_user_id`` — proving the gate
    runs first and the storage swap did not bypass it. This needs no DB.
    """

    class _EmptyScalars:
        def all(self):
            return []

    class _Result:
        def scalars(self):
            return _EmptyScalars()

    class _FakeSession:
        async def execute(self, _query):
            return _Result()

    current_user = SimpleNamespace(id=1, username="tester")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            PlayerLinkService.link_player(
                _FakeSession(),
                current_user,
                player_id=99,
                is_primary=True,
            )
        )

    assert exc_info.value.status_code == 400


class _UnlinkFakeSession:
    """Minimal async session for the guard unit tests: ``get`` returns a fixed
    player, ``commit`` records that it happened."""

    def __init__(self, player: SimpleNamespace) -> None:
        self._player = player
        self.committed = False

    async def get(self, _model, _pk):
        return self._player

    async def commit(self) -> None:
        self.committed = True


def test_unlink_blocked_when_workspace_membership_role_present() -> None:
    """Unlink must be refused (409) when the auth user still holds a real
    workspace membership role. ``workspace_member`` is anchored on this player,
    so clearing the link would strand that membership row auth-less. The link
    must be left intact, no commit issued, and the 409 must name the blocking
    workspaces so the user knows which to leave first.
    """
    player = SimpleNamespace(id=99, auth_user_id=7)
    session = _UnlinkFakeSession(player)

    with patch.object(
        pls_module,
        "workspace_names_blocking_player_unlink",
        AsyncMock(return_value=["Alpha Cup", "Beta League"]),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                PlayerLinkService._unlink_player_from_auth_user(session, player_id=99)
            )

    assert exc_info.value.status_code == 409
    assert "Alpha Cup" in exc_info.value.detail
    assert "Beta League" in exc_info.value.detail
    assert player.auth_user_id == 7  # link untouched
    assert session.committed is False


def test_unlink_allowed_when_no_workspace_membership_role() -> None:
    """A pure participant (no workspace membership role) can still unlink: the
    link is nulled and the change committed."""
    player = SimpleNamespace(id=99, auth_user_id=7)
    session = _UnlinkFakeSession(player)

    with patch.object(
        pls_module,
        "workspace_names_blocking_player_unlink",
        AsyncMock(return_value=[]),
    ):
        asyncio.run(
            PlayerLinkService._unlink_player_from_auth_user(session, player_id=99)
        )

    assert player.auth_user_id is None
    assert session.committed is True


def test_unlink_already_unlinked_is_noop() -> None:
    """Idempotent: unlinking a player whose link is already NULL neither checks
    membership nor commits."""
    player = SimpleNamespace(id=99, auth_user_id=None)
    session = _UnlinkFakeSession(player)

    with patch.object(
        pls_module, "workspace_names_blocking_player_unlink", AsyncMock()
    ) as guard:
        asyncio.run(
            PlayerLinkService._unlink_player_from_auth_user(session, player_id=99)
        )

    guard.assert_not_awaited()
    assert player.auth_user_id is None
    assert session.committed is False


# ---------------------------------------------------------------------------
# DB-backed integration tests: link/unlink/get round-trips.
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    """Yield a live AsyncSession, or skip the test if the DB is unreachable.

    Probes with ``select current_database()`` (mirrors
    ``test_signup_provisions_player.py``) and hard-guards against ever running
    against a production database.
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
        email=f"link-{suffix}@example.com",
        username=f"link_{suffix}",
        hashed_password="x",
    )
    session.add(auth_user)
    await session.flush()
    return auth_user


async def _make_player(session, suffix: str) -> User:
    player = User(name=f"player_{suffix}")
    session.add(player)
    await session.flush()
    return player


def test_link_sets_auth_user_id(db_session) -> None:
    """``_link_player_to_auth_user`` writes ``players.user.auth_user_id``."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        auth_user = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix)

        linked = await PlayerLinkService._link_player_to_auth_user(
            db_session, auth_user_id=auth_user.id, player_id=player.id
        )
        return auth_user.id, player.id, linked

    auth_user_id, player_id, linked = asyncio.run(_run())

    assert linked.id == player_id
    assert linked.auth_user_id == auth_user_id


def test_double_link_to_other_account_raises_409(db_session) -> None:
    """Re-linking a player owned by another auth user raises 409."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        owner = await _make_auth_user(db_session, f"o{suffix}")
        other = await _make_auth_user(db_session, f"x{suffix}")
        player = await _make_player(db_session, suffix)

        await PlayerLinkService._link_player_to_auth_user(
            db_session, auth_user_id=owner.id, player_id=player.id
        )

        with pytest.raises(HTTPException) as exc_info:
            await PlayerLinkService._link_player_to_auth_user(
                db_session, auth_user_id=other.id, player_id=player.id
            )
        return exc_info.value

    exc = asyncio.run(_run())
    assert exc.status_code == 409


def test_relink_same_account_is_idempotent(db_session) -> None:
    """Re-linking a player to its current owner is a no-op (no 409)."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        owner = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix)

        await PlayerLinkService._link_player_to_auth_user(
            db_session, auth_user_id=owner.id, player_id=player.id
        )
        again = await PlayerLinkService._link_player_to_auth_user(
            db_session, auth_user_id=owner.id, player_id=player.id
        )
        return owner.id, again

    owner_id, again = asyncio.run(_run())
    assert again.auth_user_id == owner_id


def test_unlink_nulls_auth_user_id(db_session) -> None:
    """``_unlink_player_from_auth_user`` clears the column back to NULL."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        owner = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix)

        await PlayerLinkService._link_player_to_auth_user(
            db_session, auth_user_id=owner.id, player_id=player.id
        )
        await PlayerLinkService._unlink_player_from_auth_user(db_session, player_id=player.id)

        refreshed = await db_session.get(User, player.id)
        return refreshed.auth_user_id

    assert asyncio.run(_run()) is None


def test_get_linked_players_returns_list_then_empty(db_session) -> None:
    """``get_linked_players`` returns ``[player]`` then ``[]`` after unlink."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        owner = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix)
        current_user = SimpleNamespace(id=owner.id, username=owner.username)

        await PlayerLinkService._link_player_to_auth_user(
            db_session, auth_user_id=owner.id, player_id=player.id
        )
        before = await PlayerLinkService.get_linked_players(db_session, current_user)

        await PlayerLinkService._unlink_player_from_auth_user(db_session, player_id=player.id)
        after = await PlayerLinkService.get_linked_players(db_session, current_user)

        return player.id, before, after

    player_id, before, after = asyncio.run(_run())

    assert [p.id for p in before] == [player_id]
    assert after == []


def test_admin_link_and_unlink_round_trip(db_session) -> None:
    """``admin_link_player``/``admin_unlink_player`` use the same column."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        owner = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix)

        linked = await PlayerLinkService.admin_link_player(
            db_session, owner.id, player.id, is_primary=True
        )
        linked_id = linked.auth_user_id

        await PlayerLinkService.admin_unlink_player(db_session, owner.id, player.id)
        refreshed = await db_session.get(User, player.id)
        return owner.id, linked_id, refreshed.auth_user_id

    owner_id, linked_id, after = asyncio.run(_run())
    assert linked_id == owner_id
    assert after is None
