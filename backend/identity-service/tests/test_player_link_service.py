"""PlayerLinkService over the single-link ``players.user.auth_user_id`` column.

Identity/workspace refactor Task 4: link/unlink/get now UPDATE
``players.user.auth_user_id`` instead of inserting/deleting ``auth.user_player``
M2M rows. The storage-round-trip cases are real-DB integration tests (mirroring
the DB-skip pattern in ``test_signup_provisions_player.py`` /
``backend/app-service/tests/conftest.py``): the DB is probed once per test and
any connection failure (e.g. anak_dev unreachable) skips cleanly instead of
failing, and the tests refuse to run against a production database name.

The DB-free unit tests cover the guards around that storage: the
Discord/Battle.net ownership gate (400 when no such connection exists, 403 when
neither identity matches the player's handles, including the ``provider_data``
fallbacks), the 409 when the player belongs to another account, idempotent
re-link, the baseline ``member`` role autofill, and the unlink guards (404 for a
foreign player, 409 naming the blocking workspaces). Data access is injected, so
these use stub repositories rather than a faked ``session.execute``.
"""

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core.social import SocialProvider  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from shared.repository import UserRepository  # noqa: E402
from src.services import players as players_module  # noqa: E402
from src.services.players import PlayerLinkService, players  # noqa: E402
from tests._fakes import FakeOAuthConnections as _StubConnections  # noqa: E402
from tests._fakes import FakeSessionCache  # noqa: E402
from tests._fakes import FakeSocialAccounts as _StubSocials  # noqa: E402

# ---------------------------------------------------------------------------
# DB-free unit tests: stub repositories, real service logic.
# ---------------------------------------------------------------------------

NO_CONNECTION_DETAIL = "Link Discord, Battle.net, Riot or Steam OAuth account before linking a player"
NO_MATCH_DETAIL = "Discord, Battle.net, Riot or Steam account does not match selected player"


class _StubPlayers:
    """``UserRepository`` stand-in over a single in-memory player row."""

    def __init__(self, player=None) -> None:
        self._player = player

    async def get(self, _session, player_id: int):
        if self._player is not None and self._player.id == player_id:
            return self._player
        return None

    async def get_by_auth_user_id(self, _session, auth_user_id: int):
        if self._player is not None and self._player.auth_user_id == auth_user_id:
            return self._player
        return None

    # The real write: it only sets the column and flushes.
    link_auth_user = UserRepository.link_auth_user


class _StubMembers:
    """``WorkspaceMemberRepository`` stand-in for the role-autofill lookup."""

    def __init__(self, workspace_ids=()) -> None:
        self._workspace_ids = list(workspace_ids)

    async def workspace_ids_for_player(self, _session, player_id: int):
        assert player_id is not None
        return list(self._workspace_ids)


class _FakeSession:
    """Records whether the link/unlink actually reached the DB."""

    def __init__(self) -> None:
        self.committed = False
        self.flushed = False

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj) -> None:
        return None


def _conn(provider: str, **kwargs):
    return SimpleNamespace(
        provider=provider,
        username=kwargs.pop("username", "provider-subject"),
        display_name=kwargs.pop("display_name", None),
        email=kwargs.pop("email", None),
        provider_data=kwargs.pop("provider_data", None),
        **kwargs,
    )


def _service(*, connections=(), handles=None, player=None, workspace_ids=(), cache=None) -> PlayerLinkService:
    return PlayerLinkService(
        connections=_StubConnections(connections),
        socials=_StubSocials(handles=handles),
        players=_StubPlayers(player),
        members=_StubMembers(workspace_ids),
        cache=cache if cache is not None else FakeSessionCache(),
    )


def _player(player_id: int = 99, auth_user_id: int | None = None):
    return SimpleNamespace(id=player_id, auth_user_id=auth_user_id)


CURRENT_USER = SimpleNamespace(id=7, username="tester")


def test_link_player_requires_oauth_ownership_gate() -> None:
    """``link`` must still run ownership verification before storing.

    With no Discord/Battle.net connection the gate raises 400 and the link never
    touches ``auth_user_id`` — proving the gate runs first and the storage swap
    did not bypass it.
    """
    player = _player()
    service = _service(player=player)
    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.link(session, CURRENT_USER, player_id=99))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == NO_CONNECTION_DETAIL
    assert player.auth_user_id is None
    assert session.committed is False


@pytest.mark.parametrize(
    ("connection", "handles"),
    [
        pytest.param(
            _conn("discord", username="Mercy"),
            {SocialProvider.DISCORD: ["mercy"]},
            id="discord-username",
        ),
        pytest.param(
            _conn("discord", username="Someone", provider_data={"username": "AnaMain"}),
            {SocialProvider.DISCORD: ["anamain"]},
            id="discord-provider-data-username",
        ),
        pytest.param(
            _conn("battlenet", username="Hero#2100"),
            {SocialProvider.BATTLENET: ["hero#2100"]},
            id="battlenet-username-battletag",
        ),
        pytest.param(
            _conn("battlenet", provider_data={"battletag": "Hero#2100"}),
            {SocialProvider.BATTLENET: ["Hero#2100"]},
            id="battlenet-provider-data-battletag",
        ),
        pytest.param(
            _conn("riot", username="Hide on bush#KR1"),
            {SocialProvider.RIOT: ["Hide on bush # kr1"]},
            id="riot-riot-id",
        ),
    ],
)
def test_link_accepts_matching_oauth_identity(connection, handles) -> None:
    """Ownership matches on the player's Discord names or battletags, including
    the ``provider_data`` fallbacks."""
    player = _player()
    service = _service(connections=[connection], handles=handles, player=player)
    session = _FakeSession()

    linked = asyncio.run(service.link(session, CURRENT_USER, player_id=99))

    assert linked is player
    assert player.auth_user_id == CURRENT_USER.id
    assert session.committed is True


def test_link_rejects_when_no_identity_matches() -> None:
    """A connected but non-matching Discord/Battle.net identity is 403, and the
    link is not written."""
    player = _player()
    service = _service(
        connections=[_conn("discord", username="Someone"), _conn("battlenet", username="Other#1111")],
        handles={SocialProvider.DISCORD: ["mercy"], SocialProvider.BATTLENET: ["hero#2100"]},
        player=player,
    )
    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.link(session, CURRENT_USER, player_id=99))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == NO_MATCH_DETAIL
    assert player.auth_user_id is None
    assert session.committed is False


@pytest.mark.parametrize(
    "connection",
    [
        pytest.param(_conn("discord", username="someone", display_name="AnaMain"), id="discord-display-name"),
        pytest.param(_conn("discord", username="someone", provider_data={"global_name": "AnaMain"}), id="global-name"),
        pytest.param(_conn("discord", username="someone", email="anamain"), id="discord-email"),
        pytest.param(_conn("steam", username="1", display_name="76561197960287930"), id="steam-persona-name"),
    ],
)
def test_link_rejects_display_names_and_emails_as_proof(connection) -> None:
    """Q3: only unique handles prove ownership; a display name or email is free text."""
    player = _player()
    service = _service(
        connections=[connection],
        # 22202 is the account id the persona name (a SteamID64) would read as.
        handles={SocialProvider.DISCORD: ["anamain"], SocialProvider.STEAM: ["22202"]},
        player=player,
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.link(_FakeSession(), CURRENT_USER, player_id=99))
    assert (exc_info.value.status_code, exc_info.value.detail) == (403, NO_MATCH_DETAIL)
    assert player.auth_user_id is None


def test_link_and_unlink_drop_the_accounts_rbac_cache_after_commit() -> None:
    """The player carries workspace memberships, so the account's cached RBAC is stale on both."""
    cache = FakeSessionCache()
    player = _player()
    service = _service(
        connections=[_conn("discord", username="Mercy")],
        handles={SocialProvider.DISCORD: ["mercy"]},
        player=player,
        cache=cache,
    )
    asyncio.run(service.link(_FakeSession(), CURRENT_USER, player_id=99))
    assert cache.invalidated == [CURRENT_USER.id]

    with patch.object(players_module, "workspace_names_blocking_player_unlink", AsyncMock(return_value=[])):
        asyncio.run(service.unlink(_FakeSession(), CURRENT_USER, player_id=99))
    assert cache.invalidated == [CURRENT_USER.id, CURRENT_USER.id]


def test_link_rejects_a_riot_id_that_names_another_player() -> None:
    player = _player()
    service = _service(
        connections=[_conn("riot", username="Faker#KR1")],
        handles={SocialProvider.RIOT: ["Hide on bush#KR1"]},
        player=player,
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.link(_FakeSession(), CURRENT_USER, player_id=99))
    assert (exc_info.value.status_code, exc_info.value.detail) == (403, NO_MATCH_DETAIL)
    assert player.auth_user_id is None


def test_link_conflicts_when_player_owned_by_another_account() -> None:
    """Ownership can match and the link still be refused (409) when the player
    already belongs to a different auth user."""
    player = _player(auth_user_id=42)
    service = _service(
        connections=[_conn("discord", username="Mercy")],
        handles={SocialProvider.DISCORD: ["mercy"]},
        player=player,
    )
    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.link(session, CURRENT_USER, player_id=99))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Player is already linked to another account"
    assert player.auth_user_id == 42
    assert session.committed is False


def test_relink_to_same_account_is_idempotent() -> None:
    """Re-linking a player to its current owner is a no-op (no 409)."""
    player = _player(auth_user_id=CURRENT_USER.id)
    service = _service(
        connections=[_conn("discord", username="Mercy")],
        handles={SocialProvider.DISCORD: ["mercy"]},
        player=player,
    )

    again = asyncio.run(service.link(_FakeSession(), CURRENT_USER, player_id=99))

    assert again.auth_user_id == CURRENT_USER.id


def test_link_autofills_baseline_member_role() -> None:
    """Every workspace the player is anchored to gets the baseline ``member``
    role for the freshly linked auth user."""
    service = _service(
        connections=[_conn("discord", username="Mercy")],
        handles={SocialProvider.DISCORD: ["mercy"]},
        player=_player(),
        workspace_ids=(11, 22),
    )
    autofill = AsyncMock()

    with patch.object(players_module, "assign_default_member_role_if_roleless", autofill):
        asyncio.run(service.link(_FakeSession(), CURRENT_USER, player_id=99))

    granted = [call.kwargs for call in autofill.await_args_list]
    assert granted == [
        {"user_id": CURRENT_USER.id, "workspace_id": 11},
        {"user_id": CURRENT_USER.id, "workspace_id": 22},
    ]


def test_unlink_rejects_player_linked_to_another_account() -> None:
    """Unlinking someone else's player is 404 — the link is not the caller's."""
    player = _player(auth_user_id=42)
    service = _service(player=player)
    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.unlink(session, CURRENT_USER, player_id=99))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Player link not found"
    assert player.auth_user_id == 42
    assert session.committed is False


def test_unlink_blocked_when_workspace_membership_role_present() -> None:
    """Unlink must be refused (409) when the auth user still holds a real
    workspace membership role. ``workspace_member`` is anchored on this player,
    so clearing the link would strand that membership row auth-less. The link
    must be left intact, no commit issued, and the 409 must name the blocking
    workspaces so the user knows which to leave first.
    """
    player = _player(auth_user_id=7)
    service = _service(player=player)
    session = _FakeSession()

    with patch.object(
        players_module,
        "workspace_names_blocking_player_unlink",
        AsyncMock(return_value=["Alpha Cup", "Beta League"]),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(service._unlink_from_auth_user(session, player_id=99))

    assert exc_info.value.status_code == 409
    assert "Alpha Cup" in exc_info.value.detail
    assert "Beta League" in exc_info.value.detail
    assert player.auth_user_id == 7  # link untouched
    assert session.committed is False


def test_unlink_allowed_when_no_workspace_membership_role() -> None:
    """A pure participant (no workspace membership role) can still unlink: the
    link is nulled and the change committed."""
    player = _player(auth_user_id=7)
    service = _service(player=player)
    session = _FakeSession()

    with patch.object(
        players_module,
        "workspace_names_blocking_player_unlink",
        AsyncMock(return_value=[]),
    ):
        asyncio.run(service._unlink_from_auth_user(session, player_id=99))

    assert player.auth_user_id is None
    assert session.committed is True


def test_unlink_already_unlinked_is_noop() -> None:
    """Idempotent: unlinking a player whose link is already NULL neither checks
    membership nor commits."""
    player = _player(auth_user_id=None)
    service = _service(player=player)
    session = _FakeSession()

    with patch.object(players_module, "workspace_names_blocking_player_unlink", AsyncMock()) as guard:
        asyncio.run(service._unlink_from_auth_user(session, player_id=99))

    guard.assert_not_awaited()
    assert player.auth_user_id is None
    assert session.committed is False


# ---------------------------------------------------------------------------
# DB-backed integration tests: link/unlink/get round-trips.
# ---------------------------------------------------------------------------


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
    """``_link_to_auth_user`` writes ``players.user.auth_user_id``."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        auth_user = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix)

        linked = await players._link_to_auth_user(db_session, auth_user_id=auth_user.id, player_id=player.id)
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

        await players._link_to_auth_user(db_session, auth_user_id=owner.id, player_id=player.id)

        with pytest.raises(HTTPException) as exc_info:
            await players._link_to_auth_user(db_session, auth_user_id=other.id, player_id=player.id)
        return exc_info.value

    exc = asyncio.run(_run())
    assert exc.status_code == 409


def test_relink_same_account_is_idempotent(db_session) -> None:
    """Re-linking a player to its current owner is a no-op (no 409)."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        owner = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix)

        await players._link_to_auth_user(db_session, auth_user_id=owner.id, player_id=player.id)
        again = await players._link_to_auth_user(db_session, auth_user_id=owner.id, player_id=player.id)
        return owner.id, again

    owner_id, again = asyncio.run(_run())
    assert again.auth_user_id == owner_id


def test_unlink_nulls_auth_user_id(db_session) -> None:
    """``_unlink_from_auth_user`` clears the column back to NULL."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        owner = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix)

        await players._link_to_auth_user(db_session, auth_user_id=owner.id, player_id=player.id)
        await players._unlink_from_auth_user(db_session, player_id=player.id)

        refreshed = await db_session.get(User, player.id)
        return refreshed.auth_user_id

    assert asyncio.run(_run()) is None


def test_get_linked_players_returns_list_then_empty(db_session) -> None:
    """``linked_players`` returns ``[player]`` then ``[]`` after unlink."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        owner = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix)
        current_user = SimpleNamespace(id=owner.id, username=owner.username)

        await players._link_to_auth_user(db_session, auth_user_id=owner.id, player_id=player.id)
        before = await players.linked_players(db_session, current_user)

        await players._unlink_from_auth_user(db_session, player_id=player.id)
        after = await players.linked_players(db_session, current_user)

        return player.id, before, after

    player_id, before, after = asyncio.run(_run())

    assert [p.id for p in before] == [player_id]
    assert after == []


def test_admin_link_and_unlink_round_trip(db_session) -> None:
    """``admin_link``/``admin_unlink`` use the same column."""

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        owner = await _make_auth_user(db_session, suffix)
        player = await _make_player(db_session, suffix)

        linked = await players.admin_link(db_session, owner.id, player.id)
        linked_id = linked.auth_user_id

        await players.admin_unlink(db_session, player.id)
        refreshed = await db_session.get(User, player.id)
        return owner.id, linked_id, refreshed.auth_user_id

    owner_id, linked_id, after = asyncio.run(_run())
    assert linked_id == owner_id
    assert after is None
