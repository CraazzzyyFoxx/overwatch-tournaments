"""``validate_token`` -- the gateway's per-request call -- on and off the RBAC cache.

A full hit (every component, the account's ``user`` fields included) costs one
Redis round trip (MGET of the entry, its generation and the sid blacklist) and
no SQL at all; a miss loads the account identity-only -- after reading the
generation that fences its fill -- and fills the whole entry; a Redis outage
degrades to the database instead of failing the request.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import fakeredis.aioredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import models  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.rbac import RBAC_USER_KEY_PREFIX  # noqa: E402
from src.core import cache as cache_module  # noqa: E402
from src.core.metrics import REDIS_DEGRADED_TOTAL  # noqa: E402
from src.services import session_cache as session_cache_module  # noqa: E402
from src.services.api_keys import ApiKeyService  # noqa: E402
from src.services.session_cache import SessionCache  # noqa: E402
from src.services.token_payload import TokenPayloadBuilder  # noqa: E402
from src.services.token_validation import TokenValidationService  # noqa: E402
from tests._fakes import make_api_key_row  # noqa: E402

_ENTRY_KEY = f"{RBAC_USER_KEY_PREFIX}7"
_GEN_KEY = "rbac:gen:7"
_SID_KEY = "auth:sid:revoked:sid-1"
_USER = {"email": "ada@example.com", "username": "ada", "is_active": True, "is_superuser": False}
_DENY = {"resource": "team", "action": "delete", "workspace_id": None}


def _entry(**user: object) -> dict:
    return {
        "user": {**_USER, **user},
        "roles": ["user"],
        "permissions": [{"resource": "tournament", "action": "read"}],
        "workspaces": [[11, "main"]],
        "workspace_roles": {"11": {"roles": ["admin"], "permissions": [{"resource": "team", "action": "create"}]}},
        "denies": [_DENY],
    }


class _NoSql:
    """A session that fails the test on any statement."""

    def __getattr__(self, name):
        async def _fail(*_args, **_kwargs):
            raise AssertionError(f"a full RBAC cache hit must not touch the database ({name})")

        return _fail


class _ExplodingRepo:
    def __getattr__(self, name):
        async def _fail(*_args, **_kwargs):
            raise AssertionError(f"a full RBAC cache hit must not call {name}()")

        return _fail


class _MgetOnly:
    """Answers MGET from a dict and records it; any other command fails the test."""

    def __init__(self, store: dict[str, str]) -> None:
        self.store = store
        self.calls: list[tuple[str, ...]] = []

    async def mget(self, keys: list[str]) -> list[str | None]:
        self.calls.append(tuple(keys))
        return [self.store.get(key) for key in keys]

    def __getattr__(self, name):
        raise AssertionError(f"a full hit is one MGET, not {name}")


class _DownRedis:
    def __getattr__(self, _name):
        async def _fail(*_args, **_kwargs):
            raise RedisConnectionError("redis unavailable")

        return _fail


class _Repos:
    """What a fill reads: one membership, one combined role query, the denies."""

    async def list_memberships_for_auth_user(self, _session, user_id: int) -> list[tuple[int, str]]:
        assert user_id == 7
        return [(11, "main")]

    async def rbac_for_user(self, _session, user_id: int, workspace_ids: list[int]) -> tuple:
        assert (user_id, workspace_ids) == (7, [11])
        return (["user"], [{"resource": "tournament", "action": "read"}]), {
            11: (["admin"], [{"resource": "team", "action": "create"}])
        }

    async def list_denied_triples(self, _session, user_id: int) -> list[dict]:
        return [_DENY]


class _Users:
    def __init__(self, user: models.AuthUser | None = None) -> None:
        self.user = user
        self.loads = 0

    async def get_identity(self, _session, user_id: int, **_kwargs) -> models.AuthUser:
        assert self.user is not None, "a full RBAC cache hit must not load the account"
        assert user_id == 7
        self.loads += 1
        return self.user

    async def get_with_rbac(self, *_args, **_kwargs):
        raise AssertionError("the token path never hydrates ORM roles")


def _ada(*, active: bool = True) -> models.AuthUser:
    return models.AuthUser(id=7, email="ada@example.com", username="ada", is_active=active, is_superuser=False)


def _service(*, users: _Users, repos) -> TokenValidationService:
    cache = SessionCache()
    return TokenValidationService(
        codec=SimpleNamespace(decode=lambda _raw: {"sub": "7", "type": "access", "sid": "sid-1"}),
        cache=cache,
        users=users,
        payloads=TokenPayloadBuilder(cache=cache, roles=repos, members=repos, denies=repos),
    )


def _use(monkeypatch: pytest.MonkeyPatch, client) -> None:
    monkeypatch.setattr(cache_module, "get_redis", lambda: client)
    monkeypatch.setattr(session_cache_module, "get_redis", lambda: client)


def test_a_full_hit_is_one_redis_round_trip_and_no_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _MgetOnly({_ENTRY_KEY: json.dumps(_entry())})
    _use(monkeypatch, client)
    service = _service(users=_Users(), repos=_ExplodingRepo())

    payload = asyncio.run(service.validate(_NoSql(), "access-token"))

    assert client.calls == [(_ENTRY_KEY, _GEN_KEY, _SID_KEY)]
    assert (payload.sub, payload.email, payload.username, payload.is_superuser) == (7, "ada@example.com", "ada", False)
    assert payload.roles == ["user"]
    assert payload.denies == [_DENY]
    (membership,) = payload.workspaces
    assert (membership.workspace_id, membership.slug, membership.rbac_roles) == (11, "main", ["admin"])


def test_an_inactive_cached_user_is_refused_without_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _MgetOnly({_ENTRY_KEY: json.dumps(_entry(is_active=False))})
    _use(monkeypatch, client)
    service = _service(users=_Users(), repos=_ExplodingRepo())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.validate(_NoSql(), "access-token"))

    assert exc_info.value.status_code == 401


def test_a_revoked_session_is_refused_by_the_same_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _MgetOnly({_ENTRY_KEY: json.dumps(_entry()), _SID_KEY: "1"})
    _use(monkeypatch, client)
    service = _service(users=_Users(), repos=_ExplodingRepo())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.validate(_NoSql(), "access-token"))

    assert exc_info.value.status_code == 401
    assert len(client.calls) == 1


def test_a_miss_loads_identity_only_and_fills_the_whole_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    _use(monkeypatch, client)
    users = _Users(_ada())
    service = _service(users=users, repos=_Repos())

    async def scenario():
        filled = await service.validate(object(), "access-token")
        stored = json.loads(await client.get(_ENTRY_KEY))
        # The next request is a full hit: no account load, no repository call.
        service.payloads.roles = service.payloads.members = service.payloads.denies = _ExplodingRepo()
        return filled, stored, await service.validate(_NoSql(), "access-token")

    filled, stored, hit = asyncio.run(scenario())

    assert stored == _entry()
    assert users.loads == 1
    assert hit == filled
    assert (filled.email, filled.username) == ("ada@example.com", "ada")


def test_an_inactive_account_on_a_miss_is_refused_and_the_refusal_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    _use(monkeypatch, client)
    users = _Users(_ada(active=False))
    service = _service(users=users, repos=_Repos())

    async def scenario() -> list[int]:
        statuses = []
        for session in (object(), _NoSql()):  # the second request is answered by Redis alone
            try:
                await service.validate(session, "access-token")
            except HTTPException as exc:
                statuses.append(exc.status_code)
        return statuses

    assert asyncio.run(scenario()) == [401, 401]
    assert users.loads == 1


def test_a_redis_outage_degrades_to_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _DownRedis())
    service = _service(users=_Users(_ada()), repos=_Repos())
    degraded = REDIS_DEGRADED_TOTAL.labels(store="RBAC cache", action="read")
    before = degraded._value.get()

    payload = asyncio.run(service.validate(object(), "access-token"))

    assert payload.denies == [_DENY], "the deny overlay must not fail open without Redis"
    assert [ws.workspace_id for ws in payload.workspaces] == [11]
    assert degraded._value.get() == before + 1


class _DroppedAfterLoad(_Users):
    """The account row is read; THEN a change to it commits and drops the entry
    (``invalidate_rbac``) before the fill writes -- the deactivation race."""

    def __init__(self, user: models.AuthUser, cache: SessionCache) -> None:
        super().__init__(user)
        self.cache = cache

    async def get_identity(self, session, user_id: int, **kwargs) -> models.AuthUser:
        row = await super().get_identity(session, user_id, **kwargs)
        await self.cache.invalidate_rbac(user_id)
        return row


@pytest.mark.parametrize("resolver", ["validate", "resolve_active_user"])
def test_a_fill_whose_account_row_predates_a_drop_is_not_cached(monkeypatch: pytest.MonkeyPatch, resolver: str) -> None:
    """Otherwise ``is_active: true`` of a just-deleted account answers its live
    tokens from Redis, with no database check, for the whole TTL."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    _use(monkeypatch, client)
    service = _service(users=_Users(), repos=_Repos())
    service.users = _DroppedAfterLoad(_ada(), service.cache)

    async def scenario():
        await getattr(service, resolver)(object(), "access-token")
        return await client.get(_ENTRY_KEY), await client.get(_GEN_KEY)

    entry, generation = asyncio.run(scenario())

    assert entry is None
    assert generation == "1"


class _KeySession:
    def __init__(self) -> None:
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1


def _key_service(users: _Users, cache: SessionCache) -> ApiKeyService:
    row = make_api_key_row(scopes=["team.create"])

    async def get_by_public_id(_session, public_id: str):
        assert public_id == "publicid"
        return row

    repos = _Repos()
    return ApiKeyService(
        keys=SimpleNamespace(get_by_public_id=get_by_public_id),
        users=users,
        payloads=TokenPayloadBuilder(cache=cache, roles=repos, members=repos, denies=repos),
    )


def test_an_api_key_owner_is_cache_first(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    _use(monkeypatch, client)
    users = _Users(_ada())
    service = _key_service(users, SessionCache())

    async def scenario():
        first = await service.validate(_KeySession(), "owt_sk_publicid_secret-token")
        second = await service.validate(_KeySession(), "owt_sk_publicid_secret-token")
        return first, second, json.loads(await client.get(_ENTRY_KEY))

    first, second, stored = asyncio.run(scenario())

    assert first == second
    assert first.workspaces[0].rbac_permissions == [{"resource": "team", "action": "create"}]
    assert stored["user"] == _USER
    assert users.loads == 1, "the second request answers the owner from the cache"


def test_an_api_key_owner_fill_racing_a_drop_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same race through a key: a stale entry would keep a demoted or deleted
    owner's ``is_superuser``/``is_active`` behind every one of their keys."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    _use(monkeypatch, client)
    cache = SessionCache()
    service = _key_service(_DroppedAfterLoad(_ada(), cache), cache)

    async def scenario():
        payload = await service.validate(_KeySession(), "owt_sk_publicid_secret-token")
        return payload, await client.get(_ENTRY_KEY)

    payload, entry = asyncio.run(scenario())

    assert payload is not None
    assert entry is None


def test_an_inactive_api_key_owner_refuses_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    _use(monkeypatch, client)
    session = _KeySession()
    service = _key_service(_Users(_ada(active=False)), SessionCache())

    assert asyncio.run(service.validate(session, "owt_sk_publicid_secret-token")) is None
    assert session.commit_calls == 0
