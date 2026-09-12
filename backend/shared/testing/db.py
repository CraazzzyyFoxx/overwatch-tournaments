"""Unified real-Postgres session hook for integration tests across services.

Every service's ``src/core/db.py`` re-exports ``async_session_maker`` bound to
a module-global engine created once at import time. Reusing that global engine
across more than one ``asyncio.run()`` call is unsafe here: pooled asyncpg
connections are bound to the event loop that created them, and this codebase
has no ``pytest-asyncio`` -- async test bodies each get their own event loop
via a fresh ``asyncio.run()`` (or ``unittest.IsolatedAsyncioTestCase``, which
does the same internally). Reusing a pooled connection from a prior loop
raises "Future attached to a different loop" once a second test touches it.

:func:`real_db_sessionmaker` is the fix multiple test files had already
converged on independently (see ``tournament-service/tests/
test_auto_transitions.py``): a throwaway ``NullPool`` engine, created and
disposed inside a single event loop, so nothing outlives that one ``asyncio.
run()``/``IsolatedAsyncioTestCase`` test method.

:func:`ensure_test_postgres` is the session-wide provisioner. It is lazy (only
DB-touching fixtures/helpers call it) so unit tests never wait on Docker:

1. If ``POSTGRES_DB`` is a production name, skip without opening a socket.
2. Probe the current ``POSTGRES_*`` with a 2s timeout.
3. If that DSN is the committed dummy (``127.0.0.1:55432/anak_test``) and
   the probe failed, start ``docker-compose.test.yml`` and ``alembic upgrade
   head``. GitHub Actions leaves this off (``CI=true``) unless
   ``TEST_POSTGRES_DOCKER=1``.
4. Otherwise skip — never hang on a SYN retry.

Usage in an async test body or ``IsolatedAsyncioTestCase`` method::

    async def test_something():
        async with real_db_sessionmaker() as sessionmaker:
            async with sessionmaker() as session:
                ...

:func:`db_session` is a plain ``pytest.fixture`` for the common single-
session, plain-``def test_x(db_session):`` case; the whole probe lives inside
one ``asyncio.run()`` and hands back an ordinary (already-connected)
``AsyncSession`` for the test body to drive with its own ``asyncio.run(...)``
calls -- safe as long as the test issues at most one such call per session
(the pattern every existing sync-fixture caller already follows).
"""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from shared.testing.env import BACKEND_ROOT, REPO_ROOT

#: Database names integration tests must never run against, regardless of
#: what POSTGRES_* resolves to (a dev machine's real ``.env`` may point at a
#: shared server whose default database is one of these).
PROTECTED_DB_NAMES: frozenset[str] = frozenset({"anak_v5", "anak_prod"})

CONNECT_TIMEOUT = 2
COMPOSE_TIMEOUT = 120
ALEMBIC_TIMEOUT = 180

EPHEMERAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
EPHEMERAL_PORT = "55432"
EPHEMERAL_DB = "anak_test"

_ensured = False
_skip_reason: str | None = None


def _settings():
    # Imported lazily and by name: each service has its own `src.core.config`
    # module at this same dotted path, resolved relative to whichever
    # service's `tests/` directory is on sys.path for the current run.
    return importlib.import_module("src.core.config").settings


def postgres_env() -> dict[str, str]:
    return {
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": os.environ.get("POSTGRES_PASSWORD", "postgres"),
        "host": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "port": str(os.environ.get("POSTGRES_PORT", EPHEMERAL_PORT)),
        "db": os.environ.get("POSTGRES_DB", EPHEMERAL_DB),
    }


def postgres_psycopg_url() -> str:
    env = postgres_env()
    return f"postgresql+psycopg://{env['user']}:{env['password']}@{env['host']}:{env['port']}/{env['db']}"


def is_protected_db(name: str | None) -> bool:
    return (name or "").lower() in PROTECTED_DB_NAMES


def is_ephemeral_test_dsn() -> bool:
    """True when POSTGRES_* still point at the committed dummy, not a real DSN."""
    env = postgres_env()
    return env["host"].lower() in EPHEMERAL_HOSTS and env["port"] == EPHEMERAL_PORT and env["db"] == EPHEMERAL_DB


def _ci_blocks_docker() -> bool:
    flag = os.environ.get("TEST_POSTGRES_DOCKER", "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return True
    if flag in {"1", "true", "yes", "on"}:
        return False
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def _probe() -> str | None:
    """Return ``current_database()`` or None. Bounded by :data:`CONNECT_TIMEOUT`."""
    import psycopg

    env = postgres_env()
    try:
        with psycopg.connect(
            host=env["host"],
            port=int(env["port"]),
            dbname=env["db"],
            user=env["user"],
            password=env["password"],
            connect_timeout=CONNECT_TIMEOUT,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("select current_database()")
                row = cur.fetchone()
                return str(row[0]) if row else None
    except Exception:  # noqa: BLE001 -- any connect failure is "not up"
        return None


def _docker_compose_up() -> bool:
    compose = REPO_ROOT / "docker-compose.test.yml"
    if not compose.is_file():
        return False
    try:
        completed = subprocess.run(
            ["docker", "compose", "-f", str(compose), "up", "-d", "--wait"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=COMPOSE_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _alembic_upgrade() -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = postgres_psycopg_url()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        check=True,
        timeout=ALEMBIC_TIMEOUT,
        env=env,
    )


def _skip(reason: str) -> None:
    global _skip_reason
    _skip_reason = reason
    pytest.skip(reason)


def ensure_test_postgres() -> None:
    """Skip, or make sure a non-production Postgres is reachable. Idempotent."""
    global _ensured
    if _ensured:
        return
    if _skip_reason is not None:
        pytest.skip(_skip_reason)

    if is_protected_db(os.environ.get("POSTGRES_DB")):
        _skip("refusing to run integration tests against production")

    probed = _probe()
    if probed is not None:
        if is_protected_db(probed):
            _skip("refusing to run integration tests against production")
        if is_ephemeral_test_dsn():
            try:
                _alembic_upgrade()
            except Exception as exc:  # noqa: BLE001
                _skip(f"alembic upgrade failed: {exc}")
        _ensured = True
        return

    if is_ephemeral_test_dsn() and not _ci_blocks_docker() and _docker_compose_up():
        try:
            _alembic_upgrade()
        except Exception as exc:  # noqa: BLE001
            _skip(f"alembic upgrade failed: {exc}")
        probed = _probe()
        if probed is not None:
            _ensured = True
            return

    _skip("database unreachable")


def create_test_async_engine(**kwargs: Any) -> AsyncEngine:
    """Throwaway engine for ``IsolatedAsyncioTestCase`` after :func:`ensure_test_postgres`.

    Uses the psycopg async dialect (same URL the balancer IsolatedAsyncioTestCase
    files used before this helper) and ``NullPool`` so connections cannot outlive
    the per-test event loop. ``connect_timeout`` is the libpq/psycopg knob;
    asyncpg callers should keep using :func:`real_db_sessionmaker`.
    """
    ensure_test_postgres()
    connect_args = dict(kwargs.pop("connect_args", {}))
    connect_args.setdefault("connect_timeout", CONNECT_TIMEOUT)
    kwargs.setdefault("poolclass", NullPool)
    return create_async_engine(postgres_psycopg_url(), connect_args=connect_args, **kwargs)


def _async_connect_args() -> dict[str, Any]:
    return {"timeout": CONNECT_TIMEOUT}


@asynccontextmanager
async def real_db_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a session factory bound to a fresh throwaway engine, or skip.

    One engine per call, disposed on exit -- safe to call from any number of
    tests, in any order, without event-loop-lifetime issues.
    """
    ensure_test_postgres()
    engine = create_async_engine(
        _settings().db_url_asyncpg,
        poolclass=NullPool,
        connect_args=_async_connect_args(),
    )
    try:
        try:
            async with engine.connect() as conn:
                dbname = (await conn.execute(sa.text("select current_database()"))).scalar()
        except Exception as exc:  # noqa: BLE001 -- any connect failure => skip, not fail
            pytest.skip(f"database unreachable: {exc}")
        if is_protected_db(dbname if isinstance(dbname, str) else None):
            pytest.skip("refusing to run integration tests against production")
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
def db_session() -> Iterator[AsyncSession]:
    """Function-scoped live ``AsyncSession``, or skip if unreachable/prod.

    Unlike ``real_db_sessionmaker``, the engine has to outlive the ``async
    with`` block that probes it -- the caller keeps using the session after
    this fixture returns -- so it is opened and disposed by hand instead of
    reusing that context manager.
    """

    async def _open() -> tuple[AsyncEngine, AsyncSession]:
        ensure_test_postgres()
        engine = create_async_engine(
            _settings().db_url_asyncpg,
            poolclass=NullPool,
            connect_args=_async_connect_args(),
        )
        try:
            async with engine.connect() as conn:
                dbname = (await conn.execute(sa.text("select current_database()"))).scalar()
        except Exception as exc:  # noqa: BLE001 -- any connect failure => skip, not fail
            await engine.dispose()
            pytest.skip(f"database unreachable: {exc}")
        if is_protected_db(dbname if isinstance(dbname, str) else None):
            await engine.dispose()
            pytest.skip("refusing to run integration tests against production")
        return engine, async_sessionmaker(engine, expire_on_commit=False)()

    engine, session = asyncio.run(_open())
    try:
        yield session
    finally:

        async def _close() -> None:
            await session.close()
            await engine.dispose()

        asyncio.run(_close())
