import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException


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
from src.routes import auth as auth_routes  # noqa: E402
from src.services.auth_service import AuthService  # noqa: E402
from src.services.session_service import SessionService  # noqa: E402


class _FakeExecuteResult:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = list(scalars or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class _FakeSession:
    def __init__(self, results: list[dict]) -> None:
        self._results = list(results)
        self.executed = []
        self.commit_calls = 0

    async def execute(self, stmt):
        self.executed.append(stmt)
        if not self._results:
            raise AssertionError("Unexpected execute() call")
        return _FakeExecuteResult(**self._results.pop(0))

    async def commit(self) -> None:
        self.commit_calls += 1


def test_revoke_user_session_tokens_revokes_only_matching_browser() -> None:
    chrome_primary = SimpleNamespace(user_id=7, user_agent="Chrome", ip_address="10.0.0.1", is_revoked=False)
    firefox = SimpleNamespace(user_id=7, user_agent="Firefox", ip_address="10.0.0.1", is_revoked=False)
    chrome_rotated = SimpleNamespace(user_id=7, user_agent="Chrome", ip_address="10.0.0.2", is_revoked=False)
    already_revoked = SimpleNamespace(user_id=7, user_agent="Chrome", ip_address="10.0.0.1", is_revoked=True)

    session = _FakeSession(
        [
            {"scalars": [chrome_primary, firefox, chrome_rotated, already_revoked]},
        ]
    )

    revoked = asyncio.run(
        AuthService.revoke_user_session_tokens(
            session,
            user_id=7,
            user_agent="Chrome",
            ip_address="10.0.0.1",
            commit=False,
        )
    )

    assert revoked == 2
    assert chrome_primary.is_revoked is True
    assert chrome_rotated.is_revoked is True
    assert firefox.is_revoked is False
    assert already_revoked.is_revoked is True
    assert session.commit_calls == 0


def test_get_request_client_metadata_prefers_forwarded_headers() -> None:
    request = SimpleNamespace(
        headers={
            "x-original-user-agent": "Mozilla/5.0",
            "x-forwarded-for": "198.51.100.10, 172.18.0.9",
            "x-real-ip": "172.18.0.9",
            "user-agent": "node",
        },
        client=SimpleNamespace(host="172.18.0.9"),
    )

    user_agent, ip_address = AuthService.get_request_client_metadata(request)

    assert user_agent == "Mozilla/5.0"
    assert ip_address == "198.51.100.10"


def test_get_request_client_metadata_falls_back_to_direct_connection() -> None:
    request = SimpleNamespace(
        headers={"user-agent": "Mozilla/5.0"},
        client=SimpleNamespace(host="172.18.0.9"),
    )

    user_agent, ip_address = AuthService.get_request_client_metadata(request)

    assert user_agent == "Mozilla/5.0"
    assert ip_address == "172.18.0.9"


def test_revoke_session_tokens_revokes_only_matching_session_family() -> None:
    active_primary = SimpleNamespace(user_id=7, session_id=uuid4(), is_revoked=False, revoked_at=None)
    target_session_id = uuid4()
    target_current = SimpleNamespace(user_id=7, session_id=target_session_id, is_revoked=False, revoked_at=None)
    target_rotated = SimpleNamespace(user_id=7, session_id=target_session_id, is_revoked=False, revoked_at=None)

    session = _FakeSession(
        [
            {"scalars": [active_primary, target_current, target_rotated]},
        ]
    )

    revoked = asyncio.run(
        AuthService.revoke_session_tokens(
            session,
            user_id=7,
            session_id=target_session_id,
            commit=False,
        )
    )

    assert revoked == 2
    assert active_primary.is_revoked is False
    assert target_current.is_revoked is True
    assert target_current.revoked_at is not None
    assert target_rotated.is_revoked is True
    assert session.commit_calls == 0


def test_get_user_by_refresh_token_reuse_revokes_only_same_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    reused_token = SimpleNamespace(user_id=42, user_agent="Chrome", ip_address="10.0.0.1")
    session = _FakeSession(
        [
            {"scalar": None},
            {"scalar": reused_token},
        ]
    )

    scoped_revocations: list[tuple[int, str | None, str | None, bool]] = []
    global_revocations: list[int] = []

    async def fake_revoke_user_session_tokens(session, user_id, user_agent, ip_address, commit=True):
        scoped_revocations.append((user_id, user_agent, ip_address, commit))
        return 1

    async def fake_revoke_all_user_tokens(session, user_id, commit=True):
        global_revocations.append(user_id)
        return 1

    monkeypatch.setattr(AuthService, "revoke_user_session_tokens", fake_revoke_user_session_tokens, raising=False)
    monkeypatch.setattr(AuthService, "revoke_all_user_tokens", fake_revoke_all_user_tokens)

    result = asyncio.run(AuthService.get_user_by_refresh_token(session, "reused-refresh-token"))

    assert result is None
    assert scoped_revocations == [(42, "Chrome", "10.0.0.1", True)]
    assert global_revocations == []


def test_get_user_by_refresh_token_reuse_revokes_logical_session(monkeypatch: pytest.MonkeyPatch) -> None:
    reused_session_id = uuid4()
    reused_token = SimpleNamespace(user_id=42, session_id=reused_session_id, user_agent="Chrome", ip_address="10.0.0.1")
    session = _FakeSession(
        [
            {"scalar": None},
            {"scalar": reused_token},
        ]
    )

    session_revocations: list[tuple[int, object, bool]] = []
    scoped_revocations: list[tuple[int, str | None, str | None, bool]] = []

    async def fake_revoke_session_tokens(session, user_id, session_id, commit=True):
        session_revocations.append((user_id, session_id, commit))
        return 1

    async def fake_revoke_user_session_tokens(session, user_id, user_agent, ip_address, commit=True):
        scoped_revocations.append((user_id, user_agent, ip_address, commit))
        return 1

    monkeypatch.setattr(AuthService, "revoke_session_tokens", fake_revoke_session_tokens, raising=False)
    monkeypatch.setattr(AuthService, "revoke_user_session_tokens", fake_revoke_user_session_tokens, raising=False)

    result = asyncio.run(AuthService.get_user_by_refresh_token(session, "reused-refresh-token"))

    assert result is None
    assert session_revocations == [(42, reused_session_id, True)]
    assert scoped_revocations == []


def test_logout_rejects_refresh_token_owned_by_other_user(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_refresh_token_record(session, token):
        assert token == "foreign-refresh-token"
        return SimpleNamespace(user_id=999)

    async def fake_revoke_refresh_token(session, token, commit=True):
        raise AssertionError("logout should not revoke another user's refresh token")

    monkeypatch.setattr(
        "src.routes.auth.auth_service.AuthService.get_refresh_token_record",
        fake_get_refresh_token_record,
        raising=False,
    )
    monkeypatch.setattr(
        "src.routes.auth.auth_service.AuthService.revoke_refresh_token",
        fake_revoke_refresh_token,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_routes.logout(
                token_data=schemas.RefreshTokenRequest(refresh_token="foreign-refresh-token"),
                session=object(),
                current_user=SimpleNamespace(id=1, is_active=True),
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Refresh token does not belong to the current user"


def test_logout_revokes_logical_session_family(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = uuid4()
    revoke_calls: list[tuple[int, object]] = []

    async def fake_get_refresh_token_record(session, token):
        assert token == "own-refresh-token"
        return SimpleNamespace(user_id=1, session_id=session_id)

    async def fake_revoke_session_tokens(session, user_id, session_id_arg, commit=True):
        revoke_calls.append((user_id, session_id_arg))
        assert commit is True
        return 1

    async def fake_revoke_refresh_token(session, token, commit=True):
        raise AssertionError("logout should revoke the whole logical session family")

    monkeypatch.setattr(
        "src.routes.auth.auth_service.AuthService.get_refresh_token_record",
        fake_get_refresh_token_record,
        raising=False,
    )
    monkeypatch.setattr(
        "src.routes.auth.auth_service.AuthService.revoke_session_tokens",
        fake_revoke_session_tokens,
        raising=False,
    )
    monkeypatch.setattr(
        "src.routes.auth.auth_service.AuthService.revoke_refresh_token",
        fake_revoke_refresh_token,
    )

    asyncio.run(
        auth_routes.logout(
            token_data=schemas.RefreshTokenRequest(refresh_token="own-refresh-token"),
            session=object(),
            current_user=SimpleNamespace(id=1, is_active=True),
        )
    )

    assert revoke_calls == [(1, session_id)]


def test_refresh_route_preserves_session_id_during_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = uuid4()
    session_started_at = datetime.now(UTC)
    fake_refresh_record = SimpleNamespace(user_id=5, session_id=session_id, session_started_at=session_started_at)
    fake_user = SimpleNamespace(
        id=5,
        email="session@example.com",
        username="session-user",
        is_superuser=False,
        is_active=True,
    )
    create_calls: list[tuple[object, object, bool]] = []

    async def fake_get_active_refresh_token_record(session, token):
        assert token == "refresh-token"
        return fake_refresh_record

    async def fake_get_user_with_rbac(session, user_id, *, include_player_links=False):
        assert user_id == 5
        assert include_player_links is False
        return fake_user

    async def fake_revoke_refresh_token(session, token, commit=True):
        assert token == "refresh-token"
        assert commit is False
        return True

    async def fake_create_refresh_token_db(
        session,
        user_id,
        token,
        request=None,
        session_id=None,
        session_started_at=None,
        commit=True,
    ):
        create_calls.append((session_id, session_started_at, commit))
        assert user_id == 5
        assert token == "new-refresh-token"
        return SimpleNamespace()

    monkeypatch.setattr(AuthService, "get_active_refresh_token_record", fake_get_active_refresh_token_record)
    monkeypatch.setattr(AuthService, "get_user_with_rbac", fake_get_user_with_rbac)
    monkeypatch.setattr(AuthService, "revoke_refresh_token", fake_revoke_refresh_token)
    monkeypatch.setattr(AuthService, "create_refresh_token", lambda: "new-refresh-token")
    monkeypatch.setattr(AuthService, "create_refresh_token_db", fake_create_refresh_token_db)

    fake_session = SimpleNamespace(commit=AsyncMock())
    fake_request = SimpleNamespace(headers={"user-agent": "Chrome"}, client=SimpleNamespace(host="10.0.0.1"))

    response = asyncio.run(
        auth_routes.refresh_token(
            token_data=schemas.RefreshTokenRequest(refresh_token="refresh-token"),
            request=fake_request,
            session=fake_session,
        )
    )

    payload = AuthService.decode_token(response.access_token)

    assert response.refresh_token == "new-refresh-token"
    assert payload["sid"] == str(session_id)
    assert create_calls == [(session_id, session_started_at, False)]
    fake_session.commit.assert_awaited_once()


def test_list_current_user_sessions_route_uses_current_session_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[int, str | None]] = []

    async def fake_list_user_sessions(session, user_id, *, current_session_id=None, history_limit=20):
        captured.append((user_id, current_session_id, history_limit))
        return [
            {
                "session_id": "session-1",
                "is_current": True,
                "status": "active",
                "login_at": datetime.now(UTC),
                "last_seen_at": datetime.now(UTC),
                "expires_at": datetime.now(UTC),
                "revoked_at": None,
                "user_agent": "Chrome",
                "ip_address": "10.0.0.1",
            }
        ]

    monkeypatch.setattr("src.routes.auth.SessionService.list_user_sessions", fake_list_user_sessions)

    response = asyncio.run(
        auth_routes.list_current_user_sessions(
            session=object(),
            current_user=SimpleNamespace(id=7, is_active=True, _current_session_id="session-1"),
            )
        )

    assert captured == [(7, "session-1", 20)]
    assert len(response) == 1
    assert response[0].is_current is True


def test_list_user_sessions_returns_all_active_and_limited_history() -> None:
    summaries = [
        {"session_id": "active-1", "status": "active"},
        {"session_id": "active-2", "status": "active"},
        {"session_id": "revoked-1", "status": "revoked"},
        {"session_id": "expired-1", "status": "expired"},
        {"session_id": "expired-2", "status": "expired"},
    ]

    limited = SessionService._limit_user_session_history(summaries, history_limit=2)

    assert [item["session_id"] for item in limited] == [
        "active-1",
        "active-2",
        "revoked-1",
        "expired-1",
    ]


def test_revoke_current_user_session_blocks_current_session() -> None:
    session_id = uuid4()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_routes.revoke_current_user_session(
                session_id=session_id,
                session=object(),
                current_user=SimpleNamespace(id=7, is_active=True, _current_session_id=str(session_id)),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Current session cannot be revoked from the sessions list"
