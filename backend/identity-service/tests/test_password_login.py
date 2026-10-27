"""Password login: off-loop bcrypt, constant-time authentication, and the per-account lock."""

import asyncio
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import fakeredis.aioredis
import pytest
from prometheus_client import REGISTRY
from redis.exceptions import ConnectionError as RedisConnectionError

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import schemas  # noqa: E402
from src.services import auth_users as auth_users_module  # noqa: E402
from src.services import login_throttle as throttle_module  # noqa: E402
from src.services import security  # noqa: E402
from src.services.auth import AuthenticationService  # noqa: E402
from src.services.auth_users import AuthUserService  # noqa: E402
from src.services.login_throttle import LoginThrottle  # noqa: E402
from src.services.security import passwords  # noqa: E402

_PASSWORD = "Correct-Horse-1"
_HASHED_PASSWORD = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(4)).decode()


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _use_redis(monkeypatch: pytest.MonkeyPatch, client) -> None:
    monkeypatch.setattr(throttle_module, "get_redis", lambda: client)


# --- the lock -----------------------------------------------------------------------------------------------------


def test_ten_failures_lock_the_email_for_the_whole_window(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    _use_redis(monkeypatch, client)
    throttle = LoginThrottle()

    async def scenario() -> None:
        for _ in range(9):
            await throttle.record_failure("Ada@Example.com")
        assert await throttle.is_locked("ada@example.com") is False

        await throttle.record_failure("ada@example.com")
        # One counter per address, whatever its case.
        assert await throttle.is_locked("ADA@example.com") is True
        (key,) = await client.keys("auth:login:fail:*")
        assert "ada" not in key  # hashed: Redis never holds the address
        assert 0 < await client.ttl(key) <= throttle_module.WINDOW_SECONDS

        await throttle.clear("ada@example.com")
        assert await throttle.is_locked("ada@example.com") is False

    asyncio.run(scenario())


class _Users:
    """``AuthUserService.authenticate`` with a fixed answer per email."""

    def __init__(self, accounts: dict[str, SimpleNamespace]) -> None:
        self.accounts = accounts
        self.calls: list[str] = []

    async def authenticate(self, session, email: str, password: str):
        self.calls.append(email)
        user = self.accounts.get(email)
        return user if user is not None and password == _PASSWORD else None


def _login_service(users: _Users) -> AuthenticationService:
    service = AuthenticationService(users=users, throttle=LoginThrottle())

    async def issue_session(session, user, *, user_agent, ip_address, commit=True):
        return schemas.Token(access_token="access", refresh_token="refresh")

    service.issue_session = issue_session
    return service


def test_a_locked_email_is_refused_before_its_password_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_redis(monkeypatch, fakeredis.aioredis.FakeRedis(decode_responses=True))
    users = _Users({"ada@example.com": SimpleNamespace(id=7, is_active=True)})
    service = _login_service(users)
    locked_before = _sample("identity_login_total", result="locked")

    async def scenario() -> HTTPException:
        for _ in range(throttle_module.MAX_FAILURES):
            await service.throttle.record_failure("ada@example.com")
        with pytest.raises(HTTPException) as caught:
            # Even the right password: the lock answers first.
            await service.login(object(), "ada@example.com", _PASSWORD, None, None)
        return caught.value

    error = asyncio.run(scenario())

    assert (error.status_code, error.detail) == (429, "Too many failed login attempts. Try again later.")
    assert users.calls == []
    assert _sample("identity_login_total", result="locked") == locked_before + 1


def test_unknown_emails_count_and_a_successful_login_clears_the_count(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    _use_redis(monkeypatch, client)
    service = _login_service(_Users({"ada@example.com": SimpleNamespace(id=7, is_active=True)}))

    async def scenario() -> None:
        with pytest.raises(HTTPException) as unknown:
            await service.login(object(), "nobody@example.com", _PASSWORD, None, None)
        assert unknown.value.status_code == 401
        assert len(await client.keys("auth:login:fail:*")) == 1

        with pytest.raises(HTTPException):
            await service.login(object(), "ada@example.com", "wrong-Password-1", None, None)
        assert len(await client.keys("auth:login:fail:*")) == 2

        token = await service.login(object(), "ada@example.com", _PASSWORD, None, None)
        assert token.access_token == "access"
        # Ada's counter is gone; the unknown address keeps its own.
        assert len(await client.keys("auth:login:fail:*")) == 1

    asyncio.run(scenario())


def test_a_redis_outage_disables_the_lock_not_the_login(monkeypatch: pytest.MonkeyPatch) -> None:
    def down():
        raise RedisConnectionError("redis unavailable")

    monkeypatch.setattr(throttle_module, "get_redis", down)
    service = _login_service(_Users({"ada@example.com": SimpleNamespace(id=7, is_active=True)}))
    degraded = {
        action: _sample("identity_redis_degraded_total", store="login throttle", action=action)
        for action in ("read", "write", "invalidation")
    }

    async def scenario() -> None:
        with pytest.raises(HTTPException) as wrong:
            await service.login(object(), "ada@example.com", "wrong-Password-1", None, None)
        assert wrong.value.status_code == 401
        assert (await service.login(object(), "ada@example.com", _PASSWORD, None, None)).access_token == "access"

    asyncio.run(scenario())

    assert _sample("identity_redis_degraded_total", store="login throttle", action="read") == degraded["read"] + 2
    assert _sample("identity_redis_degraded_total", store="login throttle", action="write") == degraded["write"] + 1
    assert (
        _sample("identity_redis_degraded_total", store="login throttle", action="invalidation")
        == degraded["invalidation"] + 1
    )


# --- constant-time authentication ------------------------------------------------------------------------------------


class _AccountsByEmail:
    def __init__(self, user) -> None:
        self.user = user

    async def get_identity_by_email(self, session, email: str):
        return self.user


class _RecordingHasher:
    def __init__(self) -> None:
        self.verified: list[str] = []

    async def verify(self, plain_password: str, hashed_password: str) -> bool:
        self.verified.append(hashed_password)
        return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


@pytest.mark.parametrize(
    "account",
    [None, SimpleNamespace(id=7, hashed_password=None)],
    ids=["unknown email", "passwordless account"],
)
def test_an_account_without_a_hash_still_pays_one_bcrypt_verify(account) -> None:
    hasher = _RecordingHasher()
    service = AuthUserService(users=_AccountsByEmail(account), hasher=hasher)

    assert asyncio.run(service.authenticate(object(), "ada@example.com", _PASSWORD)) is None

    # Same work as a wrong password, against a real cost-12 hash.
    assert hasher.verified == [auth_users_module._DUMMY_PASSWORD_HASH]
    assert bcrypt.checkpw(b"anything", auth_users_module._DUMMY_PASSWORD_HASH.encode()) is False
    assert auth_users_module._DUMMY_PASSWORD_HASH.startswith("$2b$12$")


def test_authenticate_returns_the_account_only_for_its_password() -> None:
    user = SimpleNamespace(id=7, hashed_password=_HASHED_PASSWORD)
    service = AuthUserService(users=_AccountsByEmail(user), hasher=_RecordingHasher())

    assert asyncio.run(service.authenticate(object(), "ada@example.com", "wrong-Password-1")) is None
    assert asyncio.run(service.authenticate(object(), "ada@example.com", _PASSWORD)) is user


# --- the hasher -----------------------------------------------------------------------------------------------------


def test_hashing_round_trips_and_is_timed() -> None:
    before = _sample("identity_password_hash_seconds_count", op="verify")

    async def scenario() -> tuple[bool, bool]:
        hashed = await passwords.hash(_PASSWORD)
        return await passwords.verify(_PASSWORD, hashed), await passwords.verify("wrong-Password-1", hashed)

    assert asyncio.run(scenario()) == (True, False)
    assert _sample("identity_password_hash_seconds_count", op="verify") == before + 2


def test_at_most_two_bcrypt_calls_run_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # A fresh semaphore with the module's capacity: one that ever waited stays bound to this test's event loop.
    monkeypatch.setattr(security, "_BCRYPT_SLOTS", asyncio.Semaphore(security._BCRYPT_SLOTS._value))
    running = 0
    peak = 0
    lock = threading.Lock()

    def slow_bcrypt(*_args: bytes) -> bool:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return True

    async def scenario() -> None:
        await asyncio.gather(*(security._bcrypt("verify", slow_bcrypt, b"x") for _ in range(6)))

    asyncio.run(scenario())

    assert peak == 2
