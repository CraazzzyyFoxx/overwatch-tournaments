from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))

from shared.services.distributed_lock import distributed_lock  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        del script, numkeys
        if self.values.get(key) != token:
            return 0
        del self.values[key]
        return 1


class DistributedLockTests(IsolatedAsyncioTestCase):
    async def test_second_waiter_acquires_after_release(self) -> None:
        redis = FakeRedis()
        acquired: list[str] = []

        async def waiter() -> None:
            async with distributed_lock(
                redis,
                "challonge:sync:42:import",
                ttl_seconds=30,
                acquire_timeout_seconds=1,
                retry_interval_seconds=0.001,
            ) as token:
                acquired.append(token.value)

        async with distributed_lock(
            redis,
            "challonge:sync:42:import",
            ttl_seconds=30,
            acquire_timeout_seconds=1,
            retry_interval_seconds=0.001,
        ) as first_token:
            task = asyncio.create_task(waiter())
            await asyncio.sleep(0.01)
            self.assertEqual([], acquired)
            self.assertEqual(first_token.value, redis.values["challonge:sync:42:import"])

        await task

        self.assertEqual(1, len(acquired))
        self.assertNotIn("challonge:sync:42:import", redis.values)
