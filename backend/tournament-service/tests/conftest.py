"""Shared test fixtures for tournament-service.

Env defaults, cache wiring, and the real-DB ``db_session``/
``real_db_sessionmaker`` hooks used across this suite live in
``shared.testing`` -- see that package's docstring.
"""

from shared.testing import apply_test_env_defaults

# Must run before any sibling test module imports ``src.core.config`` --
# conftest.py always imports first in its own directory. Process env and a
# local ``.env`` win; committed ``shared/testing/test.env`` fills the rest.
apply_test_env_defaults()

import asyncio  # noqa: E402
from collections.abc import Generator  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from shared.testing import configure_test_cache, db_session, ensure_test_postgres  # noqa: E402,F401
from shared.testing.db import CONNECT_TIMEOUT  # noqa: E402
from shared.testing.stats_parity import stats_parity_database, stats_parity_template  # noqa: E402,F401
from tests._rpc_fakes import CapturingBroker  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def setup_test_cache() -> None:
    configure_test_cache()


class DashboardRpc:
    """The organizer dashboard subscribers (``src/rpc/dashboard.py``) on a capture broker, dispatched by subject."""

    def __init__(self) -> None:
        # The handlers log with loguru's ``{}`` placeholders (``serve.py`` hands them a loguru logger); a stdlib
        # logger would turn a failing RPC into a logging TypeError that hides the real exception.
        from loguru import logger

        from src.rpc import dashboard

        self.broker = CapturingBroker()
        dashboard.register(self.broker, logger)

    async def call(self, subject: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.broker.handlers[subject](data or {}, None)

    def call_sync(self, subject: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Drive an async handler from a synchronous test (``asyncio.run`` owns the loop)."""
        return asyncio.run(self.call(subject, data))


@pytest.fixture
def rpc() -> Generator[DashboardRpc]:
    """The dashboard handlers against the real test DB (they open their own async session).

    Each ``asyncio.run`` gets a fresh loop, so the handlers' pooled asyncpg connections are dropped before and after
    the test (``close=False``: never touch a dead loop). A connection left by an earlier test belongs to that test's
    closed loop: reused here, it fails with "Future attached to a different loop" or "Event loop is closed".
    """
    ensure_test_postgres()
    from src.core import db as async_db

    async_db.async_engine.sync_engine.dispose(close=False)
    yield DashboardRpc()
    async_db.async_engine.sync_engine.dispose(close=False)


@pytest.fixture(scope="session")
def db() -> Generator[Session]:
    """A sync session for seeding."""
    ensure_test_postgres()
    from src.core.config import settings

    connect_args: dict[str, object] = {"connect_timeout": CONNECT_TIMEOUT}
    if settings.db_statement_timeout > 0:
        connect_args["options"] = f"-c statement_timeout={settings.db_statement_timeout}"
    engine = create_engine(settings.db_url, pool_pre_ping=True, connect_args=connect_args)
    with sessionmaker(engine, class_=Session, expire_on_commit=False)() as session:
        yield session
    engine.dispose()
