"""Tests never open a TCP connection to Redis.

There is no Redis in the test environment (CI has none either), and on Windows a connect to the closed
``localhost:6379`` costs 2-4 s -- thousands of them made the suites take hours. Importing a service entrypoint
(``serve.py``, ``lifecycle.create_process``) runs ``configure_realtime(redis_url=...)`` in the test process, after which
every emit/cache-generation read dialled the dead port. Three layers, all installed by ``import shared.testing``:

1. ``redis.asyncio.Redis.from_url`` returns a ``fakeredis`` client, so the clients services build from
   ``settings.redis_url`` (realtime publisher, locks, rate limiters, ...) work against an in-memory server. A test that
   injects its own client or patches ``from_url`` is unaffected.
2. ``shared.testing.cache.pin_cache_in_memory`` keeps the cashews singleton on ``mem://`` backends.
3. Last resort: a connect to the configured ``REDIS_URL`` host:port raises :class:`RedisDialError` at once and is
   recorded; the autouse :func:`forbid_redis_dials` fixture then fails the test, because production code catches
   ``RedisError`` and would otherwise swallow the regression. ``OWT_TEST_ALLOW_REDIS=1`` lifts layer 3 for a developer
   running a real Redis.
"""

from __future__ import annotations

import os
import traceback
from collections.abc import Iterator
from urllib.parse import urlsplit

import fakeredis.aioredis
import pytest
import redis.asyncio as redis_async
import redis.asyncio.connection as redis_async_connection
import redis.connection as redis_connection
from redis.exceptions import RedisError

__all__ = ("RedisDialError", "forbid_redis_dials", "install_redis_guard")

_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
_dials: list[str] = []
_installed = False


class RedisDialError(RedisError):
    """Cause of the ``ConnectionError`` redis-py's ``connect()`` raises, after its own retries (instant, no real dial)."""


def _refuse_dial(host: str, port: int) -> None:
    configured = urlsplit(os.environ.get("REDIS_URL", ""))
    if os.environ.get("OWT_TEST_ALLOW_REDIS") == "1" or not configured.hostname:
        return
    same_host = host == configured.hostname or {host, configured.hostname} <= _LOOPBACK
    if not same_host or port != (configured.port or 6379):
        return
    caller = "".join(traceback.format_stack(limit=12)[:-2])
    _dials.append(f"{host}:{port}\n{caller}")
    raise RedisDialError(
        f"test tried to connect to Redis at {host}:{port}; tests must use fakeredis or an in-memory backend "
        "(see shared.testing.redis_guard)"
    )


def install_redis_guard() -> None:
    """Idempotent; see the module docstring."""
    global _installed
    if _installed:
        return
    _installed = True

    real_from_url = redis_async.Redis.from_url.__func__  # type: ignore[attr-defined]

    def from_url(cls: type[redis_async.Redis], url: str, **kwargs: object) -> redis_async.Redis:
        # ``FakeRedis.from_url`` calls ``super().from_url``, which lands here again with ``cls`` a fake.
        if issubclass(cls, fakeredis.aioredis.FakeRedis):
            return real_from_url(cls, url, **kwargs)
        return fakeredis.aioredis.FakeRedis.from_url(url, **kwargs)

    redis_async.Redis.from_url = classmethod(from_url)  # type: ignore[method-assign,assignment]

    real_async_connect = redis_async_connection.Connection._connect

    async def async_connect(self: redis_async_connection.Connection) -> None:
        _refuse_dial(self.host, self.port)
        await real_async_connect(self)

    redis_async_connection.Connection._connect = async_connect  # type: ignore[method-assign]

    real_connect = redis_connection.Connection._connect

    def connect(self: redis_connection.Connection) -> object:
        _refuse_dial(self.host, self.port)
        return real_connect(self)

    redis_connection.Connection._connect = connect  # type: ignore[method-assign]


@pytest.fixture(autouse=True)
def forbid_redis_dials() -> Iterator[None]:
    """Fail the test that tried to reach the real Redis, even if the code under test swallowed the error."""
    _dials.clear()
    yield
    if _dials:
        dials, _dials[:] = list(_dials), []
        pytest.fail(f"{len(dials)} attempt(s) to connect to Redis; first from:\n{dials[0]}", pytrace=False)
