"""Unified pytest hooks shared by every backend service's test suite.

Each service is its own uv-workspace member with its own ``tests/`` directory
and its own ``Settings`` (pydantic-settings, extending
``shared.core.config.BaseServiceSettings``). Every suite needs the same three
things:

1. **env** (:mod:`shared.testing.env`) -- load a local ``.env`` if present,
   then the committed ``testing/test.env`` dummy so ``Settings()`` can
   construct. Process environment always wins.
2. **cache** (:mod:`shared.testing.cache`) -- cashews has no default backend
   and raises ``NotConfiguredError`` until something calls ``cache.setup(...)``
   in-process.
3. **db/sessions** (:mod:`shared.testing.db`) -- a real-Postgres session for
   integration tests that probes the connection, skips cleanly when it is
   unreachable, and refuses to ever run against a production database.

Import what you need from here in a service's ``tests/conftest.py``; do not
re-implement these in individual test modules. A conftest must import ``forbid_redis_dials`` too (autouse): it
fails any test that tried to reach Redis (:mod:`shared.testing.redis_guard`).
"""

from __future__ import annotations

from shared.testing.cache import configure_test_cache, pin_cache_in_memory
from shared.testing.db import (
    PROTECTED_DB_NAMES,
    create_test_async_engine,
    db_session,
    ensure_test_postgres,
    real_db_sessionmaker,
)
from shared.testing.env import apply_test_env_defaults
from shared.testing.factories import division_grid, division_tier
from shared.testing.redis_guard import forbid_redis_dials, install_redis_guard
from shared.testing.sqlite_dialect import create_sqlite_tables, install_postgres_type_shims

# No test ever dials Redis: see :mod:`shared.testing.redis_guard`. Installed here so that importing anything from this
# package (every conftest does) is enough.
pin_cache_in_memory()
install_redis_guard()

__all__ = (
    "PROTECTED_DB_NAMES",
    "apply_test_env_defaults",
    "configure_test_cache",
    "create_sqlite_tables",
    "create_test_async_engine",
    "db_session",
    "division_grid",
    "division_tier",
    "ensure_test_postgres",
    "forbid_redis_dials",
    "install_postgres_type_shims",
    "real_db_sessionmaker",
)
