"""Shared test fixtures for app-service.

The HTTP service (``main.py`` + ``src/routes``) has been decommissioned; the
deployed process is the FastStream worker ``serve.py`` exposing typed
``rpc.app.*`` handlers in ``src/rpc/*``. The former HTTP ``client`` fixture (a
Starlette test client over ``main.app``) is gone — integration tests call the
RPC handlers directly instead.

Handlers are nested closures registered via ``@broker.subscriber("topic")`` in
each module's ``register(broker, logger)``. ``_CaptureBroker`` records those
closures by topic so a test can invoke a handler with a request envelope
(``{"id":.., "query":{k:[..]}, "payload":{..}, "identity":{..}}``) and assert on
the returned ``{"ok":bool, "data":..}`` / error envelope. ``rpc`` is the package
fixture exposing that registry.

Env defaults, cache wiring, and the real-DB ``db_session``/
``real_db_sessionmaker`` hooks used elsewhere in this suite live in
``shared.testing`` -- see that package's docstring.
"""

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
from src.core.config import settings  # noqa: E402

# The cashews cache is a process-global singleton with no default backend --
# any cache-touching flow raises ``NotConfiguredError`` until something calls
# ``cache.setup(...)`` in this process. ``serve.py`` does this via
# ``configure_cache()``; tests route every known prefix to an in-memory
# backend instead (see ``shared.testing.cache``).
configure_test_cache()


def _create_test_engine():
    ensure_test_postgres()
    connect_args: dict[str, object] = {"connect_timeout": CONNECT_TIMEOUT}
    if settings.db_statement_timeout > 0:
        connect_args["options"] = f"-c statement_timeout={settings.db_statement_timeout}"

    return create_engine(
        settings.db_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@pytest.fixture(scope="session")
def db() -> Generator[Session]:
    test_engine = _create_test_engine()
    test_session_maker = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
    with test_session_maker() as session:
        yield session
    test_engine.dispose()


def build_query(params: dict[str, Any]) -> dict[str, list[str]]:
    """Convert a flat HTTP-style params dict into the gateway query envelope.

    The gateway forwards query params as ``{key: [str, ...]}`` (always lists). A
    list value becomes the list of stringified items; an empty list yields an
    empty list (the param is "present but empty", mirroring ``?entities=``); a
    scalar becomes a single-element list. Bools serialize lowercase to match
    FastAPI's ``true``/``false`` query coercion.
    """

    def _str(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    query: dict[str, list[str]] = {}
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            query[key] = [_str(v) for v in value]
        else:
            query[key] = [_str(value)]
    return query


class _CaptureBroker:
    """Minimal stand-in for the FastStream broker used in tests.

    ``register(broker, logger)`` only ever calls ``broker.subscriber(topic)`` as a
    decorator (verified across ``src/rpc/*``). This records the decorated handler
    keyed by topic and returns it unchanged so the module imports/registers exactly
    as it does under ``serve.py`` — no RabbitMQ connection required.
    """

    def __init__(self) -> None:
        self.handlers: dict[str, Callable[..., Awaitable[dict]]] = {}

    def subscriber(self, topic: str, *args: Any, **kwargs: Any):
        def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
            self.handlers[topic] = fn
            return fn

        return decorator


class RpcHarness:
    """Registers RPC modules against a capture broker and dispatches by topic."""

    def __init__(self) -> None:
        import logging

        self.broker = _CaptureBroker()
        self.logger = logging.getLogger("app-rpc-tests")

    def register(self, *modules: Any) -> RpcHarness:
        for module in modules:
            module.register(self.broker, self.logger)
        return self

    async def call(self, topic: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        handler = self.broker.handlers[topic]
        return await handler(data or {}, None)

    def call_sync(self, topic: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Drive an async RPC handler from a synchronous pytest test.

        The handlers open their own async DB session via ``async_session_maker``;
        no event loop is running in a plain pytest test, so ``asyncio.run`` owns
        the loop for the call. Returns the ``{"ok": .., "data"/"error": ..}`` envelope.
        """
        import asyncio

        return asyncio.run(self.call(topic, data))


@pytest.fixture(scope="session")
def rpc() -> RpcHarness:
    """Session-scoped harness exposing every ``rpc.app.*`` read/aggregation handler.

    The bespoke read modules plus the shared CRUD read engine are registered so
    integration tests can dispatch ``harness.call("rpc.app.<topic>", envelope)``.

    These are read-integration tests: the handlers open their own async session
    against whatever ``POSTGRES_*`` resolved to (a local ``.env`` or the
    ephemeral ``anak_test``). :func:`ensure_test_postgres` skips in ~2s when
    that DSN is down, and never runs against production.
    """
    ensure_test_postgres()

    from src.rpc import (
        achievements,
        gamemodes,
        heroes,
        maps,
        reads_generic,
        statistics,
        users,
    )

    harness = RpcHarness()
    harness.register(
        reads_generic,
        users,
        heroes,
        maps,
        gamemodes,
        achievements,
        statistics,
    )
    return harness
