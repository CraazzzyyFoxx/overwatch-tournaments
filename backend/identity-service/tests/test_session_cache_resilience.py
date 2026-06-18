import asyncio
import os
import sys
from pathlib import Path

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

from src.core import redis as redis_module  # noqa: E402
from src.services import session_cache  # noqa: E402


class _StartupRedisClient:
    def __init__(self) -> None:
        self.closed = False

    async def ping(self) -> None:
        raise RedisConnectionError("redis is restarting")

    async def aclose(self) -> None:
        self.closed = True


class _FailingRedisClient:
    async def get(self, _key: str):
        raise RedisConnectionError("redis unavailable")

    async def set(self, _key: str, _payload: str, ex: int | None = None) -> None:
        raise RedisConnectionError("redis unavailable")

    async def delete(self, _key: str) -> None:
        raise RedisConnectionError("redis unavailable")


def test_init_redis_keeps_client_when_ping_fails(monkeypatch) -> None:
    client = _StartupRedisClient()
    monkeypatch.setattr(redis_module.aioredis, "from_url", lambda *args, **kwargs: client)

    asyncio.run(redis_module.init_redis())

    assert redis_module.get_redis() is client

    asyncio.run(redis_module.close_redis())
    assert client.closed is True


def test_get_rbac_returns_none_when_redis_read_fails(monkeypatch) -> None:
    monkeypatch.setattr(session_cache, "get_redis", lambda: _FailingRedisClient())

    cached = asyncio.run(session_cache.get_rbac(42))

    assert cached is None


def test_set_and_invalidate_rbac_ignore_redis_failures(monkeypatch) -> None:
    monkeypatch.setattr(session_cache, "get_redis", lambda: _FailingRedisClient())

    asyncio.run(session_cache.set_rbac(7, ["admin"], [{"resource": "role", "action": "read"}]))
    asyncio.run(session_cache.invalidate_rbac(7))
