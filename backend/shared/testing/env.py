"""Load test environment so every service's ``Settings`` can construct.

Every service's ``Settings`` extends ``BaseServiceSettings``, which requires
``POSTGRES_*`` / ``REDIS_URL`` (plus whatever fields the service itself adds)
just to *construct* — before a test ever imports ``src.core.db`` or
``src.core.config``, those env vars must already exist.

Call :func:`apply_test_env_defaults` once from each service's ``tests/conftest.py``
— conftest.py always imports before sibling test modules, so the environment is
ready before any test module runs its own top-level imports.

Load order (later files only fill empty keys; already-exported variables win):

1. Process environment
2. A local ``.env`` if present (cwd, ``backend/.env``, repo-root ``.env``)
3. The committed :data:`TEST_ENV_PATH` dummy values

``backend/env/*.env`` is never loaded: those files are the docker-compose
stack (``POSTGRES_HOST=postgres``) and may point at production.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path

from dotenv import load_dotenv

_THIS_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
TEST_ENV_PATH = _THIS_DIR / "test.env"


def local_env_paths() -> list[Path]:
    """Existing ``.env`` files that may carry a developer's real DSN.

    Deduped by resolved path so ``cwd == backend/`` does not load the same
    file twice.
    """
    seen: set[Path] = set()
    found: list[Path] = []
    for candidate in (Path.cwd() / ".env", BACKEND_ROOT / ".env", REPO_ROOT / ".env"):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not candidate.is_file():
            continue
        seen.add(resolved)
        found.append(candidate)
    return found


def apply_test_env_defaults(**overrides: str) -> None:
    """Fill missing ``os.environ`` keys from a local ``.env``, then ``test.env``.

    ``overrides`` pins a value after the files, still without clobbering a
    real environment / loaded ``.env`` value::

        apply_test_env_defaults(POSTGRES_DB="anak_dev")
    """
    for path in local_env_paths():
        load_dotenv(path, override=False, encoding="utf-8")
    load_dotenv(TEST_ENV_PATH, override=False, encoding="utf-8")
    for key, value in overrides.items():
        os.environ.setdefault(key, value)
    _honour_asyncio_debug_setting()
    from shared.testing.db import isolate_xdist_worker_db  # db imports this module

    isolate_xdist_worker_db()


def _setup_asyncio_runner(self: unittest.IsolatedAsyncioTestCase) -> None:
    assert self._asyncioRunner is None, "asyncio runner is already initialized"
    # debug=None: asyncio debug only under PYTHONASYNCIODEBUG=1 / -X dev.
    self._asyncioRunner = asyncio.Runner(debug=None, loop_factory=self.loop_factory)


def _honour_asyncio_debug_setting() -> None:
    """``IsolatedAsyncioTestCase`` hard-codes asyncio debug mode, ~8% of a DB suite's wall time."""
    unittest.IsolatedAsyncioTestCase._setupAsyncioRunner = _setup_asyncio_runner  # type: ignore[method-assign]
