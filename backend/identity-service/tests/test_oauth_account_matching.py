import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _ensure_test_env() -> None:
    env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "auth_test",
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

from src import schemas  # noqa: E402
from src.services.oauth_service import OAuthService  # noqa: E402


class _FakeScalarsResult:
    def __init__(self, values) -> None:
        self._values = list(values)

    def all(self):
        return list(self._values)

    def first(self):
        return self._values[0] if self._values else None

    def unique(self):
        seen = set()
        unique_values = []
        for value in self._values:
            key = getattr(value, "id", id(value))
            if key in seen:
                continue
            seen.add(key)
            unique_values.append(value)
        return _FakeScalarsResult(unique_values)


class _FakeExecuteResult:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = list(scalars or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        if self._scalar is None:
            raise AssertionError("Expected scalar result")
        return self._scalar

    def scalars(self):
        return _FakeScalarsResult(self._scalars)


class _FakeSession:
    def __init__(self, results: list[dict]) -> None:
        self._results = list(results)
        self.added = []
        self.refresh_calls = []
        self.commit_calls = 0
        self.flush_calls = 0

    async def execute(self, stmt):
        if not self._results:
            raise AssertionError("Unexpected execute() call")
        return _FakeExecuteResult(**self._results.pop(0))

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, obj) -> None:
        self.refresh_calls.append(obj)


def test_find_or_create_oauth_user_reuses_existing_user_by_email() -> None:
    existing_user = SimpleNamespace(id=11, email="player@example.com", username="existing-user")
    session = _FakeSession(
        [
            {"scalar": None},  # OAuthConnection lookup → none
            {"scalar": existing_user},  # email → AuthUser (reused)
            # _attach_verified_social_account: no player found by provider record → no-op
            {"scalars": []},  # subject match
            {"scalars": []},  # handle match
            {"scalar": None},  # players.user.auth_user_id lookup for auth_user → none
        ]
    )
    oauth_info = schemas.OAuthUserInfo(
        provider=schemas.OAuthProvider.DISCORD,
        provider_user_id="discord-123",
        email="player@example.com",
        username="discord-player",
        display_name="Discord Player",
        avatar_url="https://cdn.example/avatar.png",
        raw_data={"verified": True},
    )

    auth_user = asyncio.run(
        OAuthService.find_or_create_oauth_user(
            session,
            oauth_info,
            {"access_token": "access-token", "expires_in": 3600},
        )
    )

    assert auth_user is existing_user
    assert session.flush_calls == 0
    assert len(session.added) == 1
    oauth_connection = session.added[0]
    assert oauth_connection.auth_user_id == existing_user.id
    assert oauth_connection.provider == "discord"
    assert oauth_connection.provider_user_id == "discord-123"
    assert session.commit_calls == 1
    assert session.refresh_calls == [existing_user]


def test_find_or_create_oauth_user_reuses_existing_user_by_linked_battletag() -> None:
    existing_user = SimpleNamespace(id=21, email="existing@local", username="existing-user")
    # Player already linked to existing_user via players.user.auth_user_id.
    player = SimpleNamespace(id=210, auth_user_id=existing_user.id)
    session = _FakeSession(
        [
            {"scalar": None},  # OAuthConnection lookup → none
            # _find_player_by_provider_record: subject miss, handle hit
            {"scalars": []},  # subject (provider_user_id) match
            {"scalars": [player]},  # normalized handle match → player
            # _find_auth_user_for_player: player.auth_user_id set → AuthUser lookup
            {"scalar": existing_user},
            # matched_player.auth_user_id already == auth_user.id → no backfill query
            # _attach_verified_social_account: no player found by provider record → no-op
            {"scalars": []},  # subject match
            {"scalars": []},  # handle match
            {"scalar": None},  # players.user.auth_user_id lookup for auth_user → none
        ]
    )
    oauth_info = schemas.OAuthUserInfo(
        provider=schemas.OAuthProvider.BATTLENET,
        provider_user_id="bnet-123",
        email=None,
        username="Existing#1234",
        display_name="Existing#1234",
        raw_data={"battletag": "Existing#1234"},
    )

    auth_user = asyncio.run(
        OAuthService.find_or_create_oauth_user(
            session,
            oauth_info,
            {"access_token": "access-token", "expires_in": 3600},
        )
    )

    assert auth_user is existing_user
    assert session.flush_calls == 0
    assert len(session.added) == 1
    oauth_connection = session.added[0]
    assert oauth_connection.auth_user_id == existing_user.id
    assert oauth_connection.provider == "battlenet"
    assert oauth_connection.provider_user_id == "bnet-123"
    assert session.commit_calls == 1
    assert session.refresh_calls == [existing_user]


# ---------------------------------------------------------------------------
# _link_player_if_unowned: the shared guard behind both OAuth link sites.
# ---------------------------------------------------------------------------


def test_link_player_if_unowned_sets_link_when_unowned() -> None:
    player = SimpleNamespace(id=1, auth_user_id=None)
    auth_user = SimpleNamespace(id=99)

    linked = OAuthService._link_player_if_unowned(player, auth_user)

    assert linked is True
    assert player.auth_user_id == 99


def test_link_player_if_unowned_is_idempotent_for_same_owner() -> None:
    player = SimpleNamespace(id=1, auth_user_id=99)
    auth_user = SimpleNamespace(id=99)

    linked = OAuthService._link_player_if_unowned(player, auth_user)

    assert linked is False
    assert player.auth_user_id == 99


def test_link_player_if_unowned_never_overwrites_a_different_owner() -> None:
    """The conflict case (correction #9's guard): a player already linked to a
    different auth user is left untouched — never silently reassigned."""
    player = SimpleNamespace(id=1, auth_user_id=7)
    auth_user = SimpleNamespace(id=99)

    linked = OAuthService._link_player_if_unowned(player, auth_user)

    assert linked is False
    assert player.auth_user_id == 7


def test_find_or_create_oauth_user_never_overwrites_conflicting_player_link() -> None:
    """A race condition: between ``_find_existing_auth_user`` resolving its
    (auth_user, matched_player) pair and the backfill running, the player got
    linked to a *different* auth user (e.g. a concurrent request). The backfill
    must detect the mismatch and leave the existing link untouched rather than
    overwrite it — no flush attempted for the (non-)update."""
    existing_user = SimpleNamespace(id=31, email="conflict@local", username="conflict-user")
    other_owner_id = 777
    # Simulates the player having been linked to `other_owner_id` concurrently,
    # after _find_existing_auth_user already decided to pair it with existing_user.
    player = SimpleNamespace(id=310, auth_user_id=other_owner_id)
    session = _FakeSession(
        [
            {"scalar": None},  # OAuthConnection lookup → none
            # _attach_verified_social_account: no player found by provider record → no-op
            {"scalars": []},  # subject match
            {"scalars": []},  # handle match
            {"scalar": None},  # players.user.auth_user_id lookup for auth_user → none
        ]
    )
    oauth_info = schemas.OAuthUserInfo(
        provider=schemas.OAuthProvider.BATTLENET,
        provider_user_id="bnet-conflict",
        email=None,
        username="Conflict#1234",
        display_name="Conflict#1234",
        raw_data={"battletag": "Conflict#1234"},
    )

    async def _fake_find_existing(_session, _oauth_info):
        return existing_user, player

    with patch.object(OAuthService, "_find_existing_auth_user", staticmethod(_fake_find_existing)):
        auth_user = asyncio.run(
            OAuthService.find_or_create_oauth_user(
                session,
                oauth_info,
                {"access_token": "access-token", "expires_in": 3600},
            )
        )

    assert auth_user is existing_user
    # The player's link must remain pointed at its original (different) owner —
    # never silently reassigned to existing_user.
    assert player.auth_user_id == other_owner_id
    assert session.flush_calls == 0
