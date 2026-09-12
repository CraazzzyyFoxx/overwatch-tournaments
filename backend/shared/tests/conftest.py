"""Shared test fixtures for the ``shared`` package's own test suite.

Env defaults and the real-DB ``db_session``/``real_db_sessionmaker`` hooks
used across this suite live in ``shared.testing`` itself -- see that
package's docstring. ``db_session``/``real_db_sessionmaker`` resolve
``src.core.config`` by dotted name, which does not exist for this package;
tests here that need a real session build their own engine from
``shared.core.config.BaseServiceSettings`` (or a service-specific
``Settings``) directly instead of using that fixture.
"""

from shared.testing import apply_test_env_defaults

# Must run before any sibling test module constructs a ``Settings`` object --
# conftest.py always imports first in its own directory. Process env and a
# local ``.env`` win; committed ``shared/testing/test.env`` fills the rest.
apply_test_env_defaults()
