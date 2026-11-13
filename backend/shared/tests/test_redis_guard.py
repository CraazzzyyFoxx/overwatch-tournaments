"""The test-session Redis guard (``shared.testing.redis_guard``): no test reaches a real Redis."""

from __future__ import annotations

import os
import unittest

from shared.testing import apply_test_env_defaults

apply_test_env_defaults()

import redis.asyncio as redis_async  # noqa: E402
from cashews import cache  # noqa: E402
from redis import exceptions as redis_exceptions  # noqa: E402

from shared.testing import redis_guard  # noqa: E402


class RedisGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_clients_built_from_the_configured_url_are_in_memory(self) -> None:
        client = redis_async.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        await client.set("k", "v")
        self.assertEqual("v", await client.get("k"))
        await client.aclose()

    async def test_a_real_connection_to_the_configured_redis_is_refused_at_once_and_recorded(self) -> None:
        connection = redis_async.Connection(host="localhost", port=6379)
        with self.assertRaises(redis_exceptions.ConnectionError) as raised:
            await connection.connect()
        self.assertIsInstance(raised.exception.__cause__, redis_guard.RedisDialError)
        self.assertTrue(redis_guard._dials)
        redis_guard._dials.clear()  # the autouse fixture would otherwise (rightly) fail this test

    async def test_the_cache_singleton_cannot_be_pointed_at_redis(self) -> None:
        cache.setup("redis://localhost:6379/0", prefix="guardtest:")
        await cache.set("guardtest:k", 1)
        self.assertEqual(1, await cache.get("guardtest:k"))
