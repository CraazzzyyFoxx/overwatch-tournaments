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
"""

import os
from collections.abc import Awaitable, Callable, Generator
from typing import Any

# Provide env defaults before importing config so ``Settings()`` constructs even
# when no env file is loaded (mirrors the other DB-backed test modules). A real
# environment / env file still wins via ``setdefault``.
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.caching import configure_cache
from src.core.config import settings

# The cashews cache is a process-global singleton with no default backend. The
# decommissioned HTTP app (main.py) used to configure it at import — which the old
# `from main import app` conftest pulled in transitively. With main.py gone, the
# worker (serve.py) configures it in its process; tests must do the same or any
# cache-touching flow raises cashews NotConfiguredError.
configure_cache()


def _create_test_engine():
    connect_args: dict[str, str] = {}
    if settings.db_statement_timeout > 0:
        connect_args["options"] = f"-c statement_timeout={settings.db_statement_timeout}"

    return create_engine(
        settings.db_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
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

    def register(self, *modules: Any) -> "RpcHarness":
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
    against the populated test DB (anak_dev). Probe it once and skip cleanly when
    unreachable (mirrors the balancer integration tests), and never run against
    production.
    """
    import asyncio

    import sqlalchemy as sa

    from src.core import db

    async def _probe() -> str | None:
        async with db.async_session_maker() as session:
            return (await session.execute(sa.text("select current_database()"))).scalar()

    try:
        dbname = asyncio.run(_probe())
    except Exception as exc:  # noqa: BLE001 — any connect failure => skip, not fail
        pytest.skip(f"database unreachable: {exc}")
    if dbname in {"anak_v5", "anak_prod"}:  # hard guard: never run against prod
        pytest.skip("refusing to run integration tests against production")

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
