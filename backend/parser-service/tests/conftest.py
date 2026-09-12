"""Shared test fixtures for parser-service.

Env defaults, cache wiring, and the real-DB ``db_session``/
``real_db_sessionmaker`` hooks used across this suite live in
``shared.testing`` -- see that package's docstring.
"""

from shared.testing import apply_test_env_defaults

# Must run before any sibling test module imports ``src.core.config`` --
# conftest.py always imports first in its own directory. Process env and a
# local ``.env`` win; committed ``shared/testing/test.env`` fills the rest.
apply_test_env_defaults()

from shared.testing import configure_test_cache, db_session  # noqa: E402,F401

# The cashews cache is a process-global singleton with no default backend --
# any cache-touching flow raises ``NotConfiguredError`` until something calls
# ``cache.setup(...)`` in this process. ``serve.py`` does this via
# ``configure_cache()``; tests route every known prefix to an in-memory
# backend instead (see ``shared.testing.cache``).
configure_test_cache()
