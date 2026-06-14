import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace


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
            {"scalar": None},
            {"scalar": existing_user},
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
    session = _FakeSession(
        [
            {"scalar": None},
            {"scalars": [existing_user]},
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
