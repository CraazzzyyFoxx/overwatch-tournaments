"""``link_intents``: single-use Redis nonce carrying the linking user across
the apex OAuth bounce for custom-domain account linking (Task 10).

Uses an in-memory fake Redis double rather than a real server -- the module
only calls ``set``/``getdel`` through ``get_redis()``, so a small dict-backed
double faithfully exercises the single-use (GETDEL) contract without infra.
Mirrors ``test_sso_tickets.py``'s structure exactly (same module shape).
"""

import asyncio
import json
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

from src.services import link_intents  # noqa: E402


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


def test_issue_redeem_roundtrip_returns_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedisClient()
    monkeypatch.setattr(link_intents, "get_redis", lambda: fake)

    nonce = asyncio.run(link_intents.issue(42))
    assert nonce

    user_id = asyncio.run(link_intents.redeem(nonce))
    assert user_id == 42


def test_redeem_is_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """The core replay-protection guarantee (SECURITY DESIGN): a nonce that
    transits a redirect URL before being signed into the OAuth state must
    never be redeemable twice, or a captured nonce would let an attacker
    link their own provider account to the victim's user."""
    fake = _FakeRedisClient()
    monkeypatch.setattr(link_intents, "get_redis", lambda: fake)

    nonce = asyncio.run(link_intents.issue(42))

    first = asyncio.run(link_intents.redeem(nonce))
    second = asyncio.run(link_intents.redeem(nonce))

    assert first == 42
    assert second is None


def test_redeem_unknown_nonce_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedisClient()
    monkeypatch.setattr(link_intents, "get_redis", lambda: fake)

    assert asyncio.run(link_intents.redeem("does-not-exist")) is None


def test_redeem_empty_nonce_returns_none_without_touching_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    # A blank nonce is never valid; short-circuit before any Redis call so a
    # missing/blank field can't even reach the client.
    monkeypatch.setattr(
        link_intents, "get_redis", lambda: (_ for _ in ()).throw(AssertionError("should not be called"))
    )

    assert asyncio.run(link_intents.redeem("")) is None


def test_issue_stores_under_prefixed_key_with_120s_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _CapturingRedis:
        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            captured["key"] = key
            captured["value"] = value
            captured["ex"] = ex

    monkeypatch.setattr(link_intents, "get_redis", lambda: _CapturingRedis())

    nonce = asyncio.run(link_intents.issue(42))

    assert captured["key"] == f"oauth:link-intent:{nonce}"
    assert captured["ex"] == 120
    assert json.loads(captured["value"]) == {"user_id": 42}  # type: ignore[arg-type]


def test_issue_raises_when_redis_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    # issue() has no safe fallback -- a nonce nobody could ever redeem is
    # worse than an explicit failure. Must raise, not swallow.
    monkeypatch.setattr(link_intents, "get_redis", lambda: _DownRedisClient())

    with pytest.raises(RedisConnectionError):
        asyncio.run(link_intents.issue(42))


def test_redeem_fails_closed_when_redis_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(link_intents, "get_redis", lambda: _DownRedisClient())

    assert asyncio.run(link_intents.redeem("some-nonce")) is None


def test_redeem_discards_corrupted_json_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _CorruptRedis:
        async def getdel(self, key: str) -> str:
            return "{not valid json"

    monkeypatch.setattr(link_intents, "get_redis", lambda: _CorruptRedis())

    assert asyncio.run(link_intents.redeem("some-nonce")) is None


def test_redeem_discards_payload_missing_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    class _MalshapedRedis:
        async def getdel(self, key: str) -> str:
            return json.dumps({"not_user_id": 42})

    monkeypatch.setattr(link_intents, "get_redis", lambda: _MalshapedRedis())

    assert asyncio.run(link_intents.redeem("some-nonce")) is None


def test_redeem_discards_payload_with_non_integer_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    class _MalshapedRedis:
        async def getdel(self, key: str) -> str:
            return json.dumps({"user_id": "not-an-int"})

    monkeypatch.setattr(link_intents, "get_redis", lambda: _MalshapedRedis())

    assert asyncio.run(link_intents.redeem("some-nonce")) is None
