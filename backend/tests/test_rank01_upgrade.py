"""``rank01`` moves the division-grid import jobs' mapping option to its new key, and back on downgrade.

A scratch database is upgraded to ``quota0003`` (the revision before ``rank01``) and seeded with import jobs the
previous release wrote, in every status a job can be retried from or reported in; it is then upgraded to ``rank01``,
downgraded and upgraded again. Each pass moves the key and keeps its value; a request without it is left untouched.
Needs the ephemeral test Postgres; skips otherwise.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import psycopg
import pytest
from psycopg.types.json import Json

from shared.testing.db import MIGRATION_PROOF_SKIP, ensure_test_postgres, migration_proofs_enabled, postgres_env

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PRE_REVISION = "quota0003"
TARGET = "rank01"
SCRATCH_DB = "rank01_import_jobs"
OLD = "include_ow_rank_mappings"
NEW = "include_native_rank_mappings"


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


def _url(dbname: str) -> str:
    env = postgres_env()
    return f"postgresql+psycopg://{env['user']}:{env['password']}@{env['host']}:{env['port']}/{dbname}"


def _alembic(command: str, target: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", command, target],
        cwd=str(BACKEND),
        env={**os.environ, "DATABASE_URL": _url(SCRATCH_DB), **env},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _insert(conn: psycopg.Connection, table: str, **columns) -> int:
    names = ", ".join(f'"{name}"' for name in columns)
    placeholders = ", ".join(f"%({name})s" for name in columns)
    return conn.execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders}) RETURNING id", columns).fetchone()[0]


def _requests() -> dict[int, dict]:
    with _connect(SCRATCH_DB) as conn:
        return dict(conn.execute("SELECT id, request_json FROM division_grid_import_job").fetchall())


@pytest.fixture(scope="module")
def legacy_jobs():
    ensure_test_postgres()
    if not migration_proofs_enabled():
        pytest.skip(MIGRATION_PROOF_SKIP)
    with _connect("postgres") as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    try:
        done = _alembic("upgrade", PRE_REVISION, OWT_APPLY_ENCOUNTER_LAYER_DROP="1")
        assert done.returncode == 0, done.stderr[-3000:]
        with _connect(SCRATCH_DB) as conn:
            target = _insert(conn, "workspace", slug="rank01-target", name="rank01-target")
            source = _insert(conn, "workspace", slug="rank01-source", name="rank01-source")
            requests = {
                "pending": {"source_grid_id": 5, "source_version_id": 20, "include_icons": True, OLD: False},
                "failed": {"source_grid_id": 5, "source_version_id": 21, "include_icons": False, OLD: True},
                "completed": {"source_grid_id": 6, "source_version_id": 30, "include_icons": True, OLD: True},
                "running": {"source_grid_id": 7, "source_version_id": 40},
            }
            for status, request in requests.items():
                _insert(
                    conn,
                    "division_grid_import_job",
                    workspace_id=target,
                    source_workspace_id=source,
                    status=status,
                    request_json=Json(request),
                    idempotency_key=f"division-grid-import:{status}",
                )
        yield _requests()
    finally:
        with _connect("postgres") as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')


def _moved(request: dict, old: str, new: str) -> dict:
    if old not in request:
        return request
    return {**{key: value for key, value in request.items() if key != old}, new: request[old]}


def test_the_mapping_option_follows_the_revision_both_ways(legacy_jobs) -> None:
    assert sum(OLD in request for request in legacy_jobs.values()) == 3
    for command, target, old, new in (
        ("upgrade", TARGET, OLD, NEW),
        ("downgrade", PRE_REVISION, NEW, OLD),
        ("upgrade", TARGET, OLD, NEW),
    ):
        done = _alembic(command, target)
        assert done.returncode == 0, done.stderr[-3000:]
        expected = {job_id: _moved(request, OLD, new) for job_id, request in legacy_jobs.items()}
        assert _requests() == expected, f"after {command} {target} ({old} -> {new})"
