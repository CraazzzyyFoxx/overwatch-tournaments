"""Shared test fixtures for stats-service.

Env defaults, cache wiring, and the real-DB ``db_session``/
``real_db_sessionmaker`` hooks used across this suite live in
``shared.testing`` -- see that package's docstring.

The public statistics reads (``rpc.stats.{statistics,users,achievements}.*``) are
nested closures registered via ``@broker.subscriber(subject, channel=...)`` in each
module's ``register(broker, logger, *, channel)``. ``_CaptureBroker`` records those
closures by subject so a test can invoke a handler with a request envelope
(``{"id":.., "query":{k:[..]}, "payload":{..}, "identity":{..}}``) and assert on
the returned ``{"ok":bool, "data":..}`` / error envelope. ``rpc`` is the package
fixture exposing that registry.
"""

import os
from collections.abc import Awaitable, Callable, Generator
from typing import Any

from shared.testing import apply_test_env_defaults

# Must run before any sibling test module imports ``src.core.config`` --
# conftest.py always imports first in its own directory. Process env and a
# local ``.env`` win; committed ``shared/testing/test.env`` fills the rest.
apply_test_env_defaults()

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from shared.testing import configure_test_cache, db_session, ensure_test_postgres  # noqa: E402,F401
from shared.testing.db import CONNECT_TIMEOUT  # noqa: E402
from shared.testing.stats_parity import (  # noqa: E402,F401
    stats_parity_database,
    stats_parity_template,
)
from src.core.config import settings  # noqa: E402
from tests._ingest_support import ingest_database, ingest_template  # noqa: E402,F401

# The cashews cache is a process-global singleton with no default backend --
# any cache-touching flow raises ``NotConfiguredError`` until something calls
# ``cache.setup(...)`` in this process. ``serve_rpc.py``/``serve_worker.py`` do this via
# ``configure_cache()``; tests route every known prefix to an in-memory
# backend instead (see ``shared.testing.cache``).
configure_test_cache()


def pytest_configure(config: pytest.Config) -> None:
    # Same marker app-service's pytest.ini declares; the moved /users/* read tests carry it.
    config.addinivalue_line("markers", "validation: validates request payload/query constraints without DB data")


#: A smoke read of a populated developer database: it names real players, tournaments and achievements (user 599,
#: tournament 36, achievement 1, ...) that a freshly migrated ``anak_test`` -- CI's -- does not have.
seeded_db = pytest.mark.skipif(
    os.environ.get("OWT_SEEDED_DB") != "1",
    reason="smoke read of a populated developer database (real player/tournament ids); set OWT_SEEDED_DB=1",
)


@pytest.fixture(scope="session")
def db() -> Generator[Session]:
    ensure_test_postgres()
    connect_args: dict[str, object] = {"connect_timeout": CONNECT_TIMEOUT}
    if settings.db_statement_timeout > 0:
        connect_args["options"] = f"-c statement_timeout={settings.db_statement_timeout}"
    test_engine = create_engine(settings.db_url, pool_pre_ping=True, connect_args=connect_args)
    with sessionmaker(test_engine, class_=Session, expire_on_commit=False)() as session:
        yield session
    test_engine.dispose()


def build_query(params: dict[str, Any]) -> dict[str, list[str]]:
    """Convert a flat HTTP-style params dict into the gateway query envelope.

    The gateway forwards query params as ``{key: [str, ...]}`` (always lists). A
    list value becomes the list of stringified items; an empty list yields an
    empty list (the param is "present but empty", mirroring ``?entities=``); a
    scalar becomes a single-element list. Bools serialize lowercase.
    """

    def _str(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    return {
        key: [_str(v) for v in value] if isinstance(value, (list, tuple)) else [_str(value)]
        for key, value in params.items()
    }


class _CaptureBroker:
    """Records each ``@broker.subscriber(subject, **kwargs)`` handler by subject; no RabbitMQ connection."""

    def __init__(self) -> None:
        self.handlers: dict[str, Callable[..., Awaitable[dict]]] = {}

    def subscriber(self, subject: str, **_kwargs: Any):
        def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
            self.handlers[subject] = fn
            return fn

        return decorator


class RpcHarness:
    """Registers public-read RPC modules against a capture broker and dispatches by subject."""

    def __init__(self) -> None:
        from loguru import logger

        self.broker = _CaptureBroker()
        # The handlers log with loguru's ``{}`` placeholders (``serve_rpc.py`` hands them a
        # loguru logger); a stdlib logger would turn a failing RPC into a logging
        # TypeError that hides the real exception.
        self.logger = logger

    def register(self, *modules: Any) -> RpcHarness:
        for module in modules:
            module.register(self.broker, self.logger, channel=None)
        return self

    async def call(self, subject: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.broker.handlers[subject](data or {}, None)

    def call_sync(self, subject: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Drive an async RPC handler from a synchronous pytest test (``asyncio.run`` owns the loop).

        Each call's loop dies with it, so its pooled connections go too (see ``_drop_loop_bound_async_connections``):
        a test may call twice.
        """
        import asyncio

        from src.core import db as async_db

        try:
            return asyncio.run(self.call(subject, data))
        finally:
            async_db.async_engine.sync_engine.dispose(close=False)


@pytest.fixture(autouse=True)
def _drop_loop_bound_async_connections() -> Generator[None]:
    """Forget pooled asyncpg connections once a test is over.

    Tests drive the async engine through ``asyncio.run``, and every call gets a fresh
    loop; a connection pooled by a finished loop breaks the next one ("Event loop is
    closed", "'NoneType' object has no attribute 'send'"). ``close=False`` drops the
    pool without touching the dead loop.
    """
    yield
    from src.core import db as async_db

    async_db.async_engine.sync_engine.dispose(close=False)


@pytest.fixture(scope="session")
def rpc() -> RpcHarness:
    """Session-scoped harness exposing every public ``rpc.stats.{statistics,users,achievements}.*`` read.

    The handlers open their own async session against whatever ``POSTGRES_*``
    resolved to; :func:`ensure_test_postgres` skips in ~2s when that DSN is down,
    and never runs against production.
    """
    ensure_test_postgres()

    from src.rpc import achievement_reads, statistics, users

    return RpcHarness().register(users, achievement_reads, statistics)
