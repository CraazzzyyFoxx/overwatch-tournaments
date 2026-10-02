import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.models.identity.auth_user import AuthUser
from shared.schemas.user_merge_auth import AuthMergeFinalizationRequest
from src.core import cache as cache_module  # noqa: E402
from src.core import redis as redis_module  # noqa: E402
from src.services.rbac_admin import AuthUserAdminService
from src.services.session_cache import session_cache  # noqa: E402


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

    async def set(self, _key: str, _payload: str, ex: int | None = None, nx: bool = False) -> None:
        raise RedisConnectionError("redis unavailable")

    async def delete(self, _key: str) -> None:
        raise RedisConnectionError("redis unavailable")


class _WorkingRedisClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, payload: str, ex: int | None = None, nx: bool = False) -> None:
        self.store[key] = payload

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


def test_init_redis_keeps_client_when_ping_fails(monkeypatch) -> None:
    client = _StartupRedisClient()
    monkeypatch.setattr(redis_module.aioredis, "from_url", lambda *args, **kwargs: client)

    asyncio.run(redis_module.init_redis())

    assert redis_module.get_redis() is client

    asyncio.run(redis_module.close_redis())
    assert client.closed is True


def test_get_rbac_returns_none_when_redis_read_fails(monkeypatch) -> None:
    monkeypatch.setattr(cache_module, "get_redis", lambda: _FailingRedisClient())

    assert asyncio.run(session_cache.get_rbac(42)) is None


def test_set_and_invalidate_rbac_ignore_redis_failures(monkeypatch) -> None:
    monkeypatch.setattr(cache_module, "get_redis", lambda: _FailingRedisClient())

    asyncio.run(session_cache.set_rbac(7, roles=["admin"], permissions=[{"resource": "role", "action": "read"}]))
    asyncio.run(session_cache.invalidate_rbac(7))


def test_rbac_round_trip_always_carries_every_component(monkeypatch) -> None:
    # "member of nothing" / "denied nothing" must be representable answers: a
    # hit without the key is indistinguishable from an unknown one, so the
    # reader would treat it as a miss, reload from the database and rewrite the
    # entry on every single request — a permanent partial cache miss.
    client = _WorkingRedisClient()
    monkeypatch.setattr(cache_module, "get_redis", lambda: client)

    asyncio.run(session_cache.set_rbac(7, roles=["admin"], permissions=[{"resource": "role", "action": "read"}]))
    cached = asyncio.run(session_cache.get_rbac(7))

    assert cached == {
        "roles": ["admin"],
        "permissions": [{"resource": "role", "action": "read"}],
        "workspaces": [],
        "workspace_roles": {},
        "denies": [],
    }
    # The invariant, stated independently of the values above: every component
    # is written, empty ones included.
    assert set(cached) == {"roles", "permissions", "workspaces", "workspace_roles", "denies"}

    asyncio.run(session_cache.invalidate_rbac(7))
    assert asyncio.run(session_cache.get_rbac(7)) is None


def test_blacklisted_session_is_visible_to_the_token_path(monkeypatch) -> None:
    client = _WorkingRedisClient()
    monkeypatch.setattr(cache_module, "get_redis", lambda: client)

    asyncio.run(session_cache.blacklist_sessions({"sid-1", "sid-2"}, 900))

    assert asyncio.run(session_cache.is_session_blacklisted("sid-1")) is True
    assert asyncio.run(session_cache.is_session_blacklisted("sid-2")) is True
    assert asyncio.run(session_cache.is_session_blacklisted("sid-3")) is False
    assert asyncio.run(session_cache.is_session_blacklisted(None)) is False


def test_blacklisting_is_skipped_when_the_access_token_ttl_is_gone(monkeypatch) -> None:
    # A non-positive TTL would write a key nothing can ever expire.
    client = _WorkingRedisClient()
    monkeypatch.setattr(cache_module, "get_redis", lambda: client)

    asyncio.run(session_cache.blacklist_session("sid-1", 0))
    asyncio.run(session_cache.blacklist_session("", 900))

    assert client.store == {}


def test_session_blacklist_degrades_without_failing_the_request(monkeypatch) -> None:
    # Revocation still holds in the database at the next refresh, so a stale
    # access token survives at most one access-token TTL — never an outage.
    monkeypatch.setattr(cache_module, "get_redis", lambda: _FailingRedisClient())

    asyncio.run(session_cache.blacklist_session("sid-1", 900))
    assert asyncio.run(session_cache.is_session_blacklisted("sid-1")) is False


def test_refresh_idempotency_round_trip_and_degradation(monkeypatch) -> None:
    client = _WorkingRedisClient()
    monkeypatch.setattr(cache_module, "get_redis", lambda: client)

    asyncio.run(session_cache.set_refresh_idem("hash-1", "access-1", "refresh-1"))
    assert asyncio.run(session_cache.get_refresh_idem("hash-1")) == {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
    }

    monkeypatch.setattr(cache_module, "get_redis", lambda: _FailingRedisClient())
    asyncio.run(session_cache.set_refresh_idem("hash-2", "access-2", "refresh-2"))
    assert asyncio.run(session_cache.get_refresh_idem("hash-1")) is None


def test_corrupt_rbac_entry_is_evicted_instead_of_pinning_the_slow_path(monkeypatch) -> None:
    client = _WorkingRedisClient()
    monkeypatch.setattr(cache_module, "get_redis", lambda: client)

    asyncio.run(session_cache.set_rbac(7, roles=[], permissions=[]))
    (key,) = client.store
    client.store[key] = "{not json"

    assert asyncio.run(session_cache.get_rbac(7)) is None
    assert client.store == {}

    # Sanity: the eviction above targeted the key the cache actually writes.
    asyncio.run(session_cache.set_rbac(7, roles=[], permissions=[]))
    assert json.loads(client.store[key])["workspaces"] == []


def test_profile_merge_finalization_fails_closed_when_redis_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(redis_module, "_redis", None)
    operator = AuthUser(
        id=7, email="merge-operator@test.invalid", username="merge-operator", is_active=True, is_superuser=True
    )
    request = AuthMergeFinalizationRequest(auth_user_ids=[11, 12], session_ids=[uuid4()])
    with pytest.raises(RuntimeError, match="not initialised"):
        asyncio.run(AuthUserAdminService().finalize_profile_merge(operator, request))
