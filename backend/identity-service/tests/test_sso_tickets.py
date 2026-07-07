"""``sso_tickets``: one-time Redis ticket used to hand a session to a custom
domain across a registrable-domain boundary cookies can't cross (Task 8).

Uses an in-memory fake Redis double rather than a real server -- the module
only calls ``set``/``getdel`` through ``get_redis()``, so a small dict-backed
double faithfully exercises the single-use (GETDEL) contract without infra.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError


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

from src.services import sso_tickets  # noqa: E402


class _FakeRedisClient:
    """Dict-backed double: real ``set``/``getdel`` semantics, no TTL enforcement."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def getdel(self, key: str) -> str | None:
        return self._store.pop(key, None)


class _DownRedisClient:
    """Simulates an unreachable Redis for every op this module uses."""

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise RedisConnectionError("redis unavailable")

    async def getdel(self, key: str) -> str | None:
        raise RedisConnectionError("redis unavailable")


def test_issue_redeem_roundtrip_returns_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake)

    code = asyncio.run(sso_tickets.issue("access-1", "refresh-1", "/dashboard"))
    assert code

    payload = asyncio.run(sso_tickets.redeem(code))
    assert payload == {"access_token": "access-1", "refresh_token": "refresh-1", "redirect": "/dashboard"}


def test_redeem_is_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake)

    code = asyncio.run(sso_tickets.issue("access-1", "refresh-1", "/dashboard"))

    first = asyncio.run(sso_tickets.redeem(code))
    second = asyncio.run(sso_tickets.redeem(code))

    assert first is not None
    assert second is None


def test_redeem_unknown_code_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake)

    assert asyncio.run(sso_tickets.redeem("does-not-exist")) is None


def test_redeem_empty_code_returns_none_without_touching_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    # A blank ticket is never valid; short-circuit before any Redis call so
    # a missing/blank query param can't even reach the client.
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: (_ for _ in ()).throw(AssertionError("should not be called")))

    assert asyncio.run(sso_tickets.redeem("")) is None


def test_issue_stores_under_prefixed_key_with_60s_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _CapturingRedis:
        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            captured["key"] = key
            captured["value"] = value
            captured["ex"] = ex

    monkeypatch.setattr(sso_tickets, "get_redis", lambda: _CapturingRedis())

    code = asyncio.run(sso_tickets.issue("access-1", "refresh-1", "/dashboard"))

    assert captured["key"] == f"sso:ticket:{code}"
    assert captured["ex"] == 60


def test_issue_raises_when_redis_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    # issue() has no safe fallback -- cookies can't cross the registrable
    # domain boundary, so a ticket nobody could ever redeem is worse than an
    # explicit failure. Must raise, not swallow.
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: _DownRedisClient())

    with pytest.raises(RedisConnectionError):
        asyncio.run(sso_tickets.issue("access-1", "refresh-1", "/dashboard"))


def test_redeem_fails_closed_when_redis_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: _DownRedisClient())

    assert asyncio.run(sso_tickets.redeem("some-code")) is None


def test_redeem_discards_corrupted_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _CorruptRedis:
        async def getdel(self, key: str) -> str:
            return "{not valid json"

    monkeypatch.setattr(sso_tickets, "get_redis", lambda: _CorruptRedis())

    assert asyncio.run(sso_tickets.redeem("some-code")) is None
