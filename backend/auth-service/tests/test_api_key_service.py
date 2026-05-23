from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
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

import pytest  # noqa: E402

from src import models, schemas  # noqa: E402
from src.services import api_key_service  # noqa: E402


class _FakeExecuteResult:
    def __init__(self, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = list(scalars or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class _FakeSession:
    def __init__(self, results: list[dict] | None = None) -> None:
        self._results = list(results or [])
        self.added = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.refresh_calls = 0

    def add(self, row) -> None:
        self.added.append(row)

    async def execute(self, stmt):
        if not self._results:
            raise AssertionError("Unexpected execute() call")
        return _FakeExecuteResult(**self._results.pop(0))

    async def commit(self) -> None:
        self.commit_calls += 1

    async def flush(self) -> None:
        self.flush_calls += 1

    async def refresh(self, row) -> None:
        self.refresh_calls += 1
        row.id = 99
        row.created_at = datetime.now(UTC)
        row.updated_at = None


def _user(*, active: bool = True) -> models.AuthUser:
    return models.AuthUser(
        id=7,
        email="ada@example.com",
        username="ada",
        is_active=active,
        is_superuser=False,
        is_verified=True,
    )


def _workspace(*, active: bool = True) -> models.Workspace:
    return models.Workspace(id=11, slug="main", name="Main", is_active=active)


def _api_key_row(
    *,
    secret: str = "secret-token",
    revoked_at=None,
    expires_at=None,
    user: models.AuthUser | None = None,
    workspace: models.Workspace | None = None,
) -> models.ApiKey:
    return models.ApiKey(
        id=123,
        auth_user_id=7,
        workspace_id=11,
        public_id="publicid",
        secret_hash=api_key_service._hash_secret(secret),
        name="Balancer API",
        scopes_json=list(api_key_service.DEFAULT_API_KEY_SCOPES),
        limits_json=dict(api_key_service.DEFAULT_API_KEY_LIMITS),
        config_policy_json=dict(api_key_service.DEFAULT_API_KEY_CONFIG_POLICY),
        expires_at=expires_at,
        revoked_at=revoked_at,
        last_used_at=None,
        created_at=datetime.now(UTC),
        updated_at=None,
        user=user if user is not None else _user(),
        workspace=workspace if workspace is not None else _workspace(),
    )


def test_create_api_key_returns_secret_once_and_stores_only_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    tokens = iter(["publicid", "secret-token"])

    async def allow_manage(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(api_key_service, "ensure_can_manage_api_keys", allow_manage)
    monkeypatch.setattr(api_key_service.secrets, "token_hex", lambda _bytes: next(tokens))

    response = asyncio.run(
        api_key_service.create_api_key(
            session,
            user=_user(),
            payload=schemas.ApiKeyCreate(name="  Balancer API  ", workspace_id=11),
        )
    )

    stored = session.added[0]
    assert response.key == "aqt_sk_publicid_secret-token"
    assert stored.secret_hash == api_key_service._hash_secret("secret-token")
    assert stored.secret_hash != "secret-token"
    assert stored.name == "Balancer API"
    assert "secret" not in response.api_key.model_dump()
    assert session.flush_calls == 1
    assert session.commit_calls == 1
    assert session.refresh_calls == 1


def test_validate_api_key_returns_api_key_payload_and_updates_last_used(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _api_key_row()
    session = _FakeSession([{"scalar": row}])

    async def allow_access(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr(api_key_service, "_has_workspace_import_access", allow_access)

    payload = asyncio.run(api_key_service.validate_api_key(session, "aqt_sk_publicid_secret-token"))

    assert payload is not None
    assert payload.credential_type == "api_key"
    assert payload.api_key is not None
    assert payload.api_key.id == 123
    assert payload.api_key.workspace_id == 11
    assert payload.api_key.scopes == ["balancer.jobs"]
    assert payload.workspaces[0].workspace_id == 11
    assert payload.workspaces[0].role == "api_key"
    assert row.last_used_at is not None
    assert session.commit_calls == 1


@pytest.mark.parametrize(
    ("row", "raw_key"),
    [
        (_api_key_row(secret="expected"), "bad-format"),
        (_api_key_row(secret="expected"), "aqt_sk_publicid_wrong"),
        (_api_key_row(revoked_at=datetime.now(UTC)), "aqt_sk_publicid_secret-token"),
        (_api_key_row(expires_at=datetime.now(UTC) - timedelta(seconds=1)), "aqt_sk_publicid_secret-token"),
        (_api_key_row(user=_user(active=False)), "aqt_sk_publicid_secret-token"),
        (_api_key_row(workspace=_workspace(active=False)), "aqt_sk_publicid_secret-token"),
    ],
)
def test_validate_api_key_rejects_invalid_revoked_expired_or_inactive(
    monkeypatch: pytest.MonkeyPatch,
    row: models.ApiKey,
    raw_key: str,
) -> None:
    session = _FakeSession([{"scalar": row}])

    async def allow_access(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr(api_key_service, "_has_workspace_import_access", allow_access)

    payload = asyncio.run(api_key_service.validate_api_key(session, raw_key))

    assert payload is None
    assert session.commit_calls == 0


def test_validate_api_key_rejects_when_owner_loses_workspace_access(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _api_key_row()
    session = _FakeSession([{"scalar": row}])

    async def deny_access(*args, **kwargs) -> bool:
        return False

    monkeypatch.setattr(api_key_service, "_has_workspace_import_access", deny_access)

    payload = asyncio.run(api_key_service.validate_api_key(session, "aqt_sk_publicid_secret-token"))

    assert payload is None
    assert session.commit_calls == 0
