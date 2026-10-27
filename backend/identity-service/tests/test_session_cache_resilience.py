import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import fakeredis.aioredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.models.identity.auth_user import AuthUser
from shared.rbac import RBAC_USER_KEY_PREFIX
from shared.schemas.user_merge_auth import AuthMergeFinalizationRequest
from src.core import cache as cache_module  # noqa: E402
from src.core import redis as redis_module  # noqa: E402
from src.services import session_cache as session_cache_module  # noqa: E402
from src.services.rbac import AuthUserAdminService
from src.services.session_cache import session_cache  # noqa: E402
from src.services.token_payload import TokenPayloadBuilder  # noqa: E402


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

    async def eval(self, *_args: object) -> None:
        raise RedisConnectionError("redis unavailable")

    async def mget(self, _keys: list[str]) -> None:
        raise RedisConnectionError("redis unavailable")

    def pipeline(self, transaction: bool = True) -> None:
        raise RedisConnectionError("redis unavailable")

    async def publish(self, _channel: str, _message: str) -> None:
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


def _fake_redis(monkeypatch) -> fakeredis.aioredis.FakeRedis:
    """A real script interpreter behind both client lookups the session cache uses."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_module, "get_redis", lambda: client)
    monkeypatch.setattr(session_cache_module, "get_redis", lambda: client)
    return client


_USER = {"email": "u7@example.com", "username": "u7", "is_active": True, "is_superuser": False}


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
    monkeypatch.setattr(session_cache_module, "get_redis", lambda: _FailingRedisClient())

    assert asyncio.run(session_cache.rbac_state(7)) == (None, None)
    asyncio.run(
        session_cache.set_rbac(
            7, generation="0", user=_USER, roles=["admin"], permissions=[{"resource": "role", "action": "read"}]
        )
    )
    asyncio.run(session_cache.invalidate_rbac(7))


def test_invalidating_rbac_tells_the_gateway_once_the_entry_is_gone(monkeypatch) -> None:
    # The gateway caches each token's verdict on its own; it only re-asks after
    # this frame. Published after the drop, or the re-ask could hit the old entry.
    client = _fake_redis(monkeypatch)
    published: list[tuple[str, str, list[str]]] = []

    async def publish(channel: str, message: str) -> None:
        entries = await client.keys(f"{RBAC_USER_KEY_PREFIX}*")
        published.append((channel, json.loads(message)["event"]["event_type"], entries))

    client.publish = publish

    async def scenario() -> None:
        await session_cache.set_rbac(7, generation="0", user=_USER, roles=["admin"], permissions=[])
        assert await session_cache.get_rbac(7) is not None
        await session_cache.invalidate_rbac(7, 8)

    asyncio.run(scenario())

    assert published == [
        ("realtime:user:7:rbac", "rbac.changed", []),
        ("realtime:user:8:rbac", "rbac.changed", []),
    ]


def test_rbac_round_trip_always_carries_every_component(monkeypatch) -> None:
    # "member of nothing" / "denied nothing" must be representable answers: a
    # hit without the key is indistinguishable from an unknown one, so the
    # reader would treat it as a miss, reload from the database and rewrite the
    # entry on every single request — a permanent partial cache miss.
    _fake_redis(monkeypatch)

    async def scenario() -> tuple[dict | None, dict | None]:
        _, generation = await session_cache.rbac_state(7)
        await session_cache.set_rbac(
            7, generation=generation, user=_USER, roles=["admin"], permissions=[{"resource": "role", "action": "read"}]
        )
        cached = await session_cache.get_rbac(7)
        await session_cache.invalidate_rbac(7)
        return cached, await session_cache.get_rbac(7)

    cached, after_invalidation = asyncio.run(scenario())

    assert cached == {
        "user": _USER,
        "roles": ["admin"],
        "permissions": [{"resource": "role", "action": "read"}],
        "workspaces": [],
        "workspace_roles": {},
        "denies": [],
    }
    # The invariant, stated independently of the values above: every component
    # is written, empty ones included.
    assert set(cached) == {"user", "roles", "permissions", "workspaces", "workspace_roles", "denies"}
    assert after_invalidation is None


class _MidFillChange:
    """Every repository a fill queries. The membership read returns the answer
    from before a commit, and that commit's RBAC drop lands while the fill is
    still in flight -- the window between validate_token's database reads and
    its cache write."""

    def __init__(self, change) -> None:
        self.change = change

    async def rbac_for_user(self, _session: object, _user_id: int, workspace_ids: list[int]) -> tuple:
        return (["user"], []), {workspace_id: ([], []) for workspace_id in workspace_ids}

    async def list_denied_triples(self, _session: object, _user_id: int) -> list:
        return []

    async def list_memberships_for_auth_user(self, _session: object, user_id: int) -> list[tuple[int, str]]:
        answer = [(5, "left-workspace")]
        if self.change is not None:
            await self.change(user_id)
        return answer


@pytest.mark.parametrize(
    "drop",
    [
        lambda user_id: session_cache.invalidate_rbac(user_id),
        lambda user_id: session_cache.finalize_profile_merge([user_id], set(), 900),
    ],
    ids=["membership-change", "profile-merge"],
)
def test_a_fill_that_read_the_database_before_an_rbac_drop_does_not_restore_it(monkeypatch, drop) -> None:
    # Without the fence the fill writes the pre-change RBAC back after the
    # drop, and the gateway -- told to re-ask -- re-reads it for the whole TTL:
    # a removed member keeps the workspace.
    _fake_redis(monkeypatch)
    repos = _MidFillChange(drop)
    builder = TokenPayloadBuilder(cache=session_cache, roles=repos, members=repos, denies=repos)
    user = SimpleNamespace(id=7, email="u7@example.com", username="u7", is_active=True, is_superuser=False)

    async def load(_session, _user_id):
        return user

    async def scenario() -> tuple[dict | None, dict | None]:
        await builder.resolve(None, 7, load)
        after_racing_fill = await session_cache.get_rbac(7)
        repos.change = None
        await builder.resolve(None, 7, load)
        return after_racing_fill, await session_cache.get_rbac(7)

    after_racing_fill, after_clean_fill = asyncio.run(scenario())

    assert after_racing_fill is None
    # The fence costs nothing once the change is behind us: the next fill caches.
    assert after_clean_fill is not None
    assert after_clean_fill["workspaces"] == [[5, "left-workspace"]]


def test_a_build_that_read_no_generation_before_its_row_answers_without_caching(monkeypatch) -> None:
    # The row predates any generation read here, so its account fields could be
    # older than a drop no fence would catch: answer, never store.
    _fake_redis(monkeypatch)
    repos = _MidFillChange(None)
    builder = TokenPayloadBuilder(cache=session_cache, roles=repos, members=repos, denies=repos)
    user = SimpleNamespace(id=7, email="u7@example.com", username="u7", is_active=True, is_superuser=False)

    async def scenario():
        return await builder.build(None, user), await session_cache.get_rbac(7)

    payload, stored = asyncio.run(scenario())

    assert [ws.workspace_id for ws in payload.workspaces] == [5]
    assert stored is None


def test_one_round_trip_reads_the_rbac_entry_and_the_sid_blacklist(monkeypatch) -> None:
    client = _fake_redis(monkeypatch)
    calls: list[str] = []
    mget = client.mget

    async def counting_mget(keys):
        calls.append("mget")
        return await mget(keys)

    client.mget = counting_mget

    async def scenario() -> list:
        await session_cache.blacklist_sessions({"sid-1", "sid-2", ""}, 900)
        await session_cache.set_rbac(7, generation="0", user=_USER, roles=[], permissions=[])
        return [
            await session_cache.token_state(7, "sid-1"),
            await session_cache.token_state(7, "sid-2"),
            await session_cache.token_state(7, "sid-3"),
            await session_cache.token_state(8, None),
        ]

    revoked_1, revoked_2, live, no_sid = asyncio.run(scenario())

    assert revoked_1[2] is True and revoked_2[2] is True
    assert live == (revoked_1[0], "0", False)
    assert live[0]["user"] == _USER
    assert no_sid == (None, "0", False)
    assert calls == ["mget"] * 4


def test_blacklisting_is_skipped_when_the_access_token_ttl_is_gone(monkeypatch) -> None:
    # A non-positive TTL would write a key nothing can ever expire.
    client = _WorkingRedisClient()
    monkeypatch.setattr(cache_module, "get_redis", lambda: client)
    monkeypatch.setattr(session_cache_module, "get_redis", lambda: client)

    asyncio.run(session_cache.blacklist_session("sid-1", 0))
    asyncio.run(session_cache.blacklist_session("", 900))
    asyncio.run(session_cache.blacklist_sessions({"sid-1"}, 0))

    assert client.store == {}


def test_session_blacklist_degrades_without_failing_the_request(monkeypatch) -> None:
    # Revocation still holds in the database at the next refresh, so a stale
    # access token survives at most one access-token TTL — never an outage.
    monkeypatch.setattr(cache_module, "get_redis", lambda: _FailingRedisClient())
    monkeypatch.setattr(session_cache_module, "get_redis", lambda: _FailingRedisClient())

    asyncio.run(session_cache.blacklist_session("sid-1", 900))
    asyncio.run(session_cache.blacklist_sessions({"sid-1", "sid-2"}, 900))
    assert asyncio.run(session_cache.token_state(7, "sid-1")) == (None, None, False)


def test_rbac_entries_live_ten_minutes(monkeypatch) -> None:
    client = _fake_redis(monkeypatch)

    async def scenario() -> int:
        await session_cache.set_rbac(7, generation="0", user=_USER, roles=[], permissions=[])
        return await client.ttl(f"{RBAC_USER_KEY_PREFIX}7")

    assert session_cache_module.RBAC_TTL_SECONDS == 600
    assert 590 < asyncio.run(scenario()) <= 600


def test_startup_flush_drops_every_rbac_entry_and_nothing_else(monkeypatch) -> None:
    client = _fake_redis(monkeypatch)

    async def scenario() -> tuple[int, list[str]]:
        for user_id in range(1, 1201):  # more than one SCAN/UNLINK batch
            await client.set(f"{RBAC_USER_KEY_PREFIX}{user_id}", "{}")
        await session_cache.blacklist_session("sid-1", 900)
        await client.set("rbac:v3:user:1", "{}")
        return await session_cache.flush_rbac_cache(), sorted(await client.keys("*"))

    flushed, left = asyncio.run(scenario())

    assert flushed == 1200
    assert left == ["auth:sid:revoked:sid-1", "rbac:v3:user:1"]


def test_startup_flush_is_fail_soft(monkeypatch) -> None:
    monkeypatch.setattr(redis_module, "_redis", None)

    assert asyncio.run(session_cache.flush_rbac_cache()) == 0


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
    client = _fake_redis(monkeypatch)

    async def scenario() -> None:
        await session_cache.set_rbac(7, generation="0", user=_USER, roles=[], permissions=[])
        (key,) = await client.keys("*")
        await client.set(key, "{not json")

        assert await session_cache.get_rbac(7) is None
        assert await client.keys("*") == []

        # Sanity: the eviction above targeted the key the cache actually writes.
        await session_cache.set_rbac(7, generation="0", user=_USER, roles=[], permissions=[])
        assert json.loads(await client.get(key))["workspaces"] == []

    asyncio.run(scenario())


def test_profile_merge_finalization_fails_closed_when_redis_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(redis_module, "_redis", None)
    operator = AuthUser(
        id=7, email="merge-operator@test.invalid", username="merge-operator", is_active=True, is_superuser=True
    )
    request = AuthMergeFinalizationRequest(auth_user_ids=[11, 12], session_ids=[uuid4()])
    with pytest.raises(RuntimeError, match="not initialised"):
        asyncio.run(AuthUserAdminService().finalize_profile_merge(operator, request))
