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

import pytest  # noqa: E402

from shared.testing import configure_test_cache, db_session  # noqa: E402,F401


@pytest.fixture(autouse=True, scope="session")
def setup_test_cache() -> None:
    configure_test_cache()
