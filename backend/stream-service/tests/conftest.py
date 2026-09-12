"""Shared test fixtures for stream-service.

Env defaults and the real-DB ``db_session``/``real_db_sessionmaker`` hooks
used across this suite live in ``shared.testing`` -- see that package's
docstring. stream-service does not use the cashews cache, so there is no
cache wiring here (see ``shared.testing.cache`` for services that do).
"""

from shared.testing import apply_test_env_defaults

# Must run before any sibling test module imports ``src.core.config`` --
# conftest.py always imports first in its own directory. Process env and a
# local ``.env`` win; committed ``shared/testing/test.env`` fills the rest.
apply_test_env_defaults()

from shared.testing import db_session  # noqa: E402,F401
