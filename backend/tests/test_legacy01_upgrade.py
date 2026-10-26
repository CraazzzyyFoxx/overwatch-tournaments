"""``legacy01`` drops every migration-only leftover, and refuses to while a legacy table still holds a row.

A template is upgraded to the revision before ``legacy01`` with no drop flag at all, so every listed object exists
(``enclayer02``/``bsplit02`` stamped without dropping). Copies of it are then upgraded: empty, the drop runs without
``OWT_APPLY_LEGACY_DROP``; with one ``overwatch.hero`` row it raises, drops nothing and stamps nothing, unless the
flag is set. Needs the ephemeral test Postgres; skips otherwise.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys

import psycopg
import pytest

from shared.testing.db import (
    BEFORE_LEGACY_DROP,
    MIGRATION_PROOF_SKIP,
    ensure_test_postgres,
    migration_proofs_enabled,
    postgres_env,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE_DB = "legacy01_tpl"
EMPTY_DB = "legacy01_empty"
REFUSED_DB = "legacy01_refused"
FLAGGED_DB = "legacy01_flagged"

_spec = importlib.util.spec_from_file_location(
    "legacy01_revision", BACKEND / "migrations" / "versions" / "legacy01_drop_legacy_storage.py"
)
assert _spec is not None and _spec.loader is not None
revision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(revision)

LISTED = {
    *revision._SCHEMAS,
    *revision._TABLES,
    *(f"{table}.{column}" for table, columns in revision._COLUMNS for column in columns),
    *revision._TYPES,
}


def _connect(dbname: str) -> psycopg.Connection:
    env = postgres_env()
    return psycopg.connect(
        host=env["host"],
        port=int(env["port"]),
        dbname=dbname,
        user=env["user"],
        password=env["password"],
        autocommit=True,
    )


def _alembic(dbname: str, command: str, target: str, **env: str) -> subprocess.CompletedProcess[str]:
    pg = postgres_env()
    url = f"postgresql+psycopg://{pg['user']}:{pg['password']}@{pg['host']}:{pg['port']}/{dbname}"
    clean = {key: value for key, value in os.environ.items() if not key.startswith("OWT_APPLY_")}
    return subprocess.run(
        [sys.executable, "-m", "alembic", command, target],
        cwd=str(BACKEND),
        env={**clean, "DATABASE_URL": url, **env},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _recreate(dbname: str, template: str | None = None) -> None:
    with _connect("postgres") as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{dbname}"' + (f' TEMPLATE "{template}"' if template else ""))


def _present(dbname: str) -> set[str]:
    """Every listed schema, table, column and type that still exists."""
    with _connect(dbname) as conn:

        def exists(sql: str, *params: str) -> bool:
            return conn.execute(sql, params).fetchone()[0]

        return (
            {s for s in revision._SCHEMAS if exists("SELECT to_regnamespace(%s) IS NOT NULL", s)}
            | {t for t in revision._TABLES if exists("SELECT to_regclass(%s) IS NOT NULL", t)}
            | {
                f"{table}.{column}"
                for table, columns in revision._COLUMNS
                for column in columns
                if exists(
                    "SELECT EXISTS (SELECT 1 FROM pg_attribute"
                    " WHERE attrelid = to_regclass(%s) AND attname = %s AND NOT attisdropped)",
                    table,
                    column,
                )
            }
            | {t for t in revision._TYPES if exists("SELECT to_regtype(%s) IS NOT NULL", t)}
        )


def _version(dbname: str) -> str:
    with _connect(dbname) as conn:
        return conn.execute("SELECT version_num FROM public.alembic_version").fetchone()[0]


def _with_a_hero(dbname: str) -> None:
    _recreate(dbname, TEMPLATE_DB)
    with _connect(dbname) as conn:
        conn.execute("INSERT INTO overwatch.hero (slug, name, image_path, type) VALUES ('ana', 'Ana', 'x', 'support')")


@pytest.fixture(scope="module")
def template():
    ensure_test_postgres()
    if not migration_proofs_enabled():
        pytest.skip(MIGRATION_PROOF_SKIP)
    try:
        _recreate(TEMPLATE_DB)
        done = _alembic(TEMPLATE_DB, "upgrade", BEFORE_LEGACY_DROP)
        assert done.returncode == 0, done.stderr[-3000:]
        # The list is the database's: nothing in it is misspelled or already gone.
        assert _present(TEMPLATE_DB) == LISTED
        yield
    finally:
        with _connect("postgres") as admin:
            for name in (TEMPLATE_DB, EMPTY_DB, REFUSED_DB, FLAGGED_DB):
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_empty_legacy_storage_is_dropped_without_the_flag(template) -> None:
    _recreate(EMPTY_DB, TEMPLATE_DB)
    done = _alembic(EMPTY_DB, "upgrade", "head")
    assert done.returncode == 0, done.stderr[-3000:]
    assert _present(EMPTY_DB) == set()


def test_a_legacy_row_without_the_flag_refuses_and_stamps_nothing(template) -> None:
    _with_a_hero(REFUSED_DB)
    done = _alembic(REFUSED_DB, "upgrade", "head")
    assert done.returncode != 0
    assert "legacy01 refuses the drop" in done.stderr and "overwatch.hero" in done.stderr
    assert revision.FLAG in done.stderr
    assert _version(REFUSED_DB) == BEFORE_LEGACY_DROP
    assert _present(REFUSED_DB) == LISTED


def test_the_flag_drops_legacy_rows_and_there_is_no_way_back(template) -> None:
    _with_a_hero(FLAGGED_DB)
    done = _alembic(FLAGGED_DB, "upgrade", "legacy01", **{revision.FLAG: "1"})
    assert done.returncode == 0, done.stderr[-3000:]
    assert _present(FLAGGED_DB) == set()
    back = _alembic(FLAGGED_DB, "downgrade", "-1")
    assert back.returncode != 0
    assert "legacy01 is forward-fix only" in back.stderr
    assert _version(FLAGGED_DB) == "legacy01"
