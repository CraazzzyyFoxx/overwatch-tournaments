"""Unified pytest hooks shared by every backend service's test suite.

Each service is its own uv-workspace member with its own ``tests/`` directory
and its own ``Settings`` (pydantic-settings, extending
``shared.core.config.BaseServiceSettings``). Before this module existed, every
service re-derived the same three things by hand, in nearly every test file:

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
re-implement these in individual test modules.
"""

from __future__ import annotations

from shared.testing.cache import configure_test_cache
from shared.testing.db import (
    PROTECTED_DB_NAMES,
    create_test_async_engine,
    db_session,
    ensure_test_postgres,
    real_db_sessionmaker,
)
from shared.testing.env import apply_test_env_defaults
from shared.testing.factories import division_grid, division_tier
from shared.testing.sqlite_dialect import install_postgres_type_shims

__all__ = (
    "PROTECTED_DB_NAMES",
    "apply_test_env_defaults",
    "configure_test_cache",
    "create_test_async_engine",
    "db_session",
    "division_grid",
    "division_tier",
    "ensure_test_postgres",
    "install_postgres_type_shims",
    "real_db_sessionmaker",
)
