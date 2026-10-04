"""The registrant's recheck button cooldown: one call per user per window."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent
for path in (str(SERVICE_ROOT), str(BACKEND_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


from redis.exceptions import RedisError  # noqa: E402

from shared.core.errors import ApiHTTPException  # noqa: E402
from src.services.registration import recheck  # noqa: E402


class _Redis:
    """SET NX EX + TTL, with a fixed clock: a key never expires mid-test."""

    def __init__(self) -> None:
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        if nx and key in self.ttls:
            return False
        self.ttls[key] = ex
        return True

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)


class _BrokenRedis:
    async def set(self, *args: object, **kwargs: object) -> bool:
        raise RedisError("connection lost")


class RecheckCooldownTests(IsolatedAsyncioTestCase):
    async def test_second_call_in_the_window_is_refused_with_retry_after(self) -> None:
        redis = _Redis()
        await recheck.assert_recheck_allowed(auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        redis.ttls["reg:recheck:2"] = 42
        with self.assertRaises(ApiHTTPException) as caught:
            await recheck.assert_recheck_allowed(auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        self.assertEqual(429, caught.exception.status_code)
        self.assertEqual({"Retry-After": "42"}, caught.exception.headers)

    async def test_other_users_are_not_held_back(self) -> None:
        redis = _Redis()
        await recheck.assert_recheck_allowed(auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        await recheck.assert_recheck_allowed(auth_user_id=3, redis=redis)  # type: ignore[arg-type]

    async def test_a_redis_failure_lets_the_check_through(self) -> None:
        await recheck.assert_recheck_allowed(auth_user_id=2, redis=_BrokenRedis())  # type: ignore[arg-type]
