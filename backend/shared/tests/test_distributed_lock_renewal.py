"""``distributed_lock`` keeps its key for as long as the body runs, not just for the TTL."""

from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase

from shared.services.distributed_lock import DistributedLockUnavailable, acquire_distributed_lock, distributed_lock


class _ExpiringRedis:
    """``SET NX EX`` and the release/renew scripts, with keys that expire on the event loop's clock."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[str, float]] = {}

    def _live(self, key: str) -> str | None:
        value = self.values.get(key)
        if value is not None and value[1] <= asyncio.get_running_loop().time():
            del self.values[key]
            return None
        return None if value is None else value[0]

    async def set(self, key: str, value: str, *, nx: bool = False, ex: float) -> bool:
        if nx and self._live(key) is not None:
            return False
        self.values[key] = (value, asyncio.get_running_loop().time() + ex)
        return True

    async def eval(self, _script: str, _numkeys: int, key: str, token: str, *renew_ms: str) -> int:
        if self._live(key) != token:
            return 0
        if renew_ms:
            self.values[key] = (token, asyncio.get_running_loop().time() + int(renew_ms[0]) / 1000)
        else:
            del self.values[key]
        return 1


class DistributedLockRenewalTests(IsolatedAsyncioTestCase):
    async def test_a_body_longer_than_the_ttl_keeps_the_lock_until_it_ends(self) -> None:
        redis = _ExpiringRedis()
        async with distributed_lock(redis, "challonge:sync:1:import", ttl_seconds=0.6) as token:
            await asyncio.sleep(1.0)
            with self.assertRaises(DistributedLockUnavailable):
                await acquire_distributed_lock(
                    redis, "challonge:sync:1:import", ttl_seconds=1, acquire_timeout_seconds=0
                )
            self.assertEqual(token.value, redis._live("challonge:sync:1:import"))

        self.assertIsNone(redis._live("challonge:sync:1:import"), "released on exit")

    async def test_one_failed_renewal_does_not_let_the_lock_lapse(self) -> None:
        """A Redis hiccup on one renewal is retried on the next tick instead of ending renewal for good."""
        redis = _ExpiringRedis()
        healthy_eval = redis.eval
        calls = 0

        async def flaky_eval(script: str, numkeys: int, key: str, token: str, *renew_ms: str) -> int:
            nonlocal calls
            if renew_ms:
                calls += 1
                if calls == 1:
                    raise ConnectionError("redis went away for a moment")
            return await healthy_eval(script, numkeys, key, token, *renew_ms)

        redis.eval = flaky_eval  # type: ignore[method-assign]
        async with distributed_lock(redis, "challonge:sync:2:import", ttl_seconds=0.6) as token:
            await asyncio.sleep(1.0)  # renewals at 0.2 (fails), 0.4, 0.6, 0.8: the key never expires
            self.assertEqual(token.value, redis._live("challonge:sync:2:import"))

        self.assertGreater(calls, 1)
        self.assertIsNone(redis._live("challonge:sync:2:import"), "released on exit")
