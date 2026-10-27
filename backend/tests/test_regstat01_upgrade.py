"""regstat01 gives a fresh database the global built-in status rows, and leaves a v5-era one as it is.

A disposable database is taken to ``defgrid01``; one global builtin is added the way a database that ran the v5 chain
already holds it, and the real Alembic process applies ``regstat01``. Only locally owned scratch databases are touched
(``stats_parity``).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from shared.registration_statuses import BUILTIN_STATUS_META
from shared.testing.db import MIGRATION_PROOF_SKIP, migration_proofs_enabled
from shared.testing.stats_parity import legacy_database, upgrade_database


def _rows(url: str, statement: str) -> list:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.execute(sa.text(statement))]
    finally:
        engine.dispose()


def test_upgrade_seeds_every_missing_builtin_once_and_keeps_existing_rows():
    if not migration_proofs_enabled():
        pytest.skip(MIGRATION_PROOF_SKIP)
    with legacy_database() as url:
        result = upgrade_database(url, "defgrid01")
        assert result.returncode == 0, result.stdout + result.stderr
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO registration.status (scope, slug, kind, name, description) "
                        "VALUES ('registration', 'pending', 'builtin', 'Pending', 'kept as it was')"
                    )
                )
        finally:
            engine.dispose()

        result = upgrade_database(url, "regstat01")
        assert result.returncode == 0, result.stdout + result.stderr

        rows = _rows(
            url,
            "SELECT scope, slug, name, description FROM registration.status "
            "WHERE workspace_id IS NULL AND kind = 'builtin'",
        )
        keys = [(scope, slug) for scope, slug, _name, _description in rows]
        assert len(keys) == len(set(keys)), "one global row per builtin"
        # Every builtin the code knows has its canonical row, except ``excluded``, which the v5 seed never had.
        assert set(keys) == {(scope, slug) for scope, items in BUILTIN_STATUS_META.items() for slug in items} - {
            ("balancer", "excluded")
        }
        by_key = {(scope, slug): (name, description) for scope, slug, name, description in rows}
        assert by_key[("registration", "pending")] == ("Pending", "kept as it was")
        assert by_key[("balancer", "ready")] == ("Ready", "Registration is ready for the balancer pool.")
