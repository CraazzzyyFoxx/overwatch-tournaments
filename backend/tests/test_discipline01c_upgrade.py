"""``discipline01c`` against a POPULATED database (spec §14.3, §14.5, §14.6; D87).

A template database is upgraded to ``discipline01b`` (``enclayer02`` with its flag, as the release runs it), seeded with
member ranks, hidden ratings and a division grid, checked by the operator's pre-flight, its live object names scrambled,
upgraded to ``discipline01c`` and read back. Copies with broken data must stop the revision with the offending rows
listed. Needs the ephemeral test Postgres; skips otherwise.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import subprocess
import sys

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.division_grid import DivisionGrid, normalize_native_ranks_to_grid
from shared.models import DivisionGridVersion
from shared.testing.db import MIGRATION_PROOF_SKIP, ensure_test_postgres, migration_proofs_enabled, postgres_env

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PRE_REVISION = "discipline01b"
TARGET = "discipline01c"
TEMPLATE_DB = "discipline01c_legacy_tpl"
MIGRATED_DB = "discipline01c_migrated"
REJECTED_DB = "discipline01c_rejected"

_spec = importlib.util.spec_from_file_location(
    "discipline01c_revision", BACKEND / "migrations" / "versions" / "discipline01c_ranks.py"
)
assert _spec is not None and _spec.loader is not None
revision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(revision)
RECONCILE_SQL = (BACKEND / "scripts" / "discipline01_reconcile.sql").read_text(encoding="utf-8")


def _connect(dbname: str, *, autocommit: bool = True) -> psycopg.Connection:
    env = postgres_env()
    return psycopg.connect(
        host=env["host"],
        port=int(env["port"]),
        dbname=dbname,
        user=env["user"],
        password=env["password"],
        autocommit=autocommit,
    )


def _url(dbname: str) -> str:
    env = postgres_env()
    return f"postgresql+psycopg://{env['user']}:{env['password']}@{env['host']}:{env['port']}/{dbname}"


def _recreate(dbname: str, template: str | None = None) -> None:
    with _connect("postgres") as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{dbname}"' + (f' TEMPLATE "{template}"' if template else ""))


def _alembic(dbname: str, target: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=str(BACKEND),
        env={**os.environ, "DATABASE_URL": _url(dbname), **env},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _rows(conn, query: str, params=None) -> list[tuple]:
    return conn.execute(query, params).fetchall()


def _scalar(conn, query: str, params=None):
    return conn.execute(query, params).fetchone()[0]


def _insert(conn, table: str, **columns) -> int:
    names = ", ".join(f'"{name}"' for name in columns)
    placeholders = ", ".join(f"%({name})s" for name in columns)
    return conn.execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders}) RETURNING id", columns).fetchone()[0]


def _statements(script: str) -> list[str]:
    text = "\n".join(
        line for line in script.splitlines() if not line.startswith("\\") and not line.lstrip().startswith("--")
    )
    return [part.strip() for part in re.split(r";\s*\n", text + "\n") if part.strip()]


def _seed(conn) -> dict:
    ids: dict = {}
    ids["ws"] = _insert(conn, "workspace", slug="d1c", name="d1c")
    ids["author"] = _insert(
        conn,
        'auth."user"',
        email="d1c-author@example.test",
        username="d1c-author",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    for key in ("canon", "book", "hidden", "flex"):
        user = _insert(conn, "players.user", name=f"d1c-{key}")
        ids[f"member_{key}"] = _insert(conn, "workspace_member", workspace_id=ids["ws"], player_id=user)
    rank = "balancer.member_rank"
    ids["rank_tank"] = _insert(
        conn, rank, workspace_id=ids["ws"], workspace_member_id=ids["member_canon"], role="tank", rank_value=2500
    )
    ids["rank_support"] = _insert(
        conn,
        rank,
        workspace_id=ids["ws"],
        workspace_member_id=ids["member_book"],
        author_user_id=ids["author"],
        role=" Support ",
        rank_value=3100,
    )
    ids["rank_flex"] = _insert(
        conn, rank, workspace_id=ids["ws"], workspace_member_id=ids["member_flex"], role="flex", rank_value=2000
    )
    hidden = "balancer.member_hidden_rating"
    ids["hidden_damage"] = _insert(
        conn,
        hidden,
        workspace_id=ids["ws"],
        workspace_member_id=ids["member_hidden"],
        role="damage",
        mu=25.0,
        sigma=8.3,
    )
    ids["hidden_flex"] = _insert(
        conn, hidden, workspace_id=ids["ws"], workspace_member_id=ids["member_flex"], role="flex", mu=24.0, sigma=8.0
    )
    _seed_division_grid(conn, ids)
    return ids


def _seed_division_grid(conn, ids: dict) -> None:
    ids["grid"] = _insert(conn, "division_grid", workspace_id=ids["ws"], slug="d1c-grid", name="d1c grid")
    ids["grid_version"] = _insert(conn, "division_grid_version", grid_id=ids["grid"], version=1, label="v1")
    conn.execute(
        "UPDATE workspace SET default_division_grid_version_id = %s WHERE id = %s", (ids["grid_version"], ids["ws"])
    )
    ids["null_ws"] = _insert(conn, "workspace", slug="d1c-null", name="No explicit default")
    ids["system_ws"] = _insert(conn, "workspace", slug="d1c-system", name="System default")
    system_grid = _insert(conn, "division_grid", slug="d1c-system-grid", name="System")
    ids["system_version"] = _insert(conn, "division_grid_version", grid_id=system_grid, version=1, label="System")
    conn.execute(
        "UPDATE workspace SET default_division_grid_version_id = %s WHERE id = %s",
        (ids["system_version"], ids["system_ws"]),
    )
    ids["tiers"] = [
        _insert(
            conn,
            "division_grid_tier",
            version_id=ids["grid_version"],
            slug=f"division-{number}",
            number=number,
            name=f"Division {number}",
            sort_order=number - 1,
            rank_min=2100 - number * 100,
            rank_max=None if number == 1 else 2199 - number * 100,
            icon_url=f"/divisions/{number}.png",
            ow_rank_min=low,
            ow_rank_max=high,
        )
        for number, (low, high) in enumerate(((4900, 4700), (4500, 4699), (None, None), (2**40, 2**40 + 99)), 1)
    ]


def _scramble_names(conn) -> None:
    """Restored databases need not carry the migration chain's constraint or index names."""
    for index, (name,) in enumerate(
        _rows(
            conn,
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid = 'balancer.member_hidden_rating'::regclass AND contype = 'u'",
        )
    ):
        conn.execute(
            sql.SQL("ALTER TABLE balancer.member_hidden_rating RENAME CONSTRAINT {} TO {}").format(
                sql.Identifier(name), sql.Identifier(f"restored_{index}_hidden")
            )
        )
    for index, (name,) in enumerate(
        _rows(
            conn,
            "SELECT i.relname FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid"
            " WHERE x.indrelid = 'balancer.member_rank'::regclass AND x.indisunique AND NOT x.indisprimary",
        )
    ):
        conn.execute(
            sql.SQL("ALTER INDEX {} RENAME TO {}").format(
                sql.Identifier("balancer", name), sql.Identifier(f"restored_{index}_rank")
            )
        )


@pytest.fixture(scope="module")
def legacy_template():
    ensure_test_postgres()
    if not migration_proofs_enabled():
        pytest.skip(MIGRATION_PROOF_SKIP)
    _recreate(TEMPLATE_DB)
    done = _alembic(TEMPLATE_DB, PRE_REVISION, OWT_APPLY_ENCOUNTER_LAYER_DROP="1")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(TEMPLATE_DB) as conn:
        ids = _seed(conn)
        _scramble_names(conn)
        preflight = {question: _rows(conn, query) for question, query in revision.PREFLIGHT}
    yield {"ids": ids, "preflight": preflight}
    with _connect("postgres") as admin:
        for name in (MIGRATED_DB, REJECTED_DB, TEMPLATE_DB):
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="module")
def migrated(legacy_template):
    _recreate(MIGRATED_DB, TEMPLATE_DB)
    done = _alembic(MIGRATED_DB, TARGET)
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(MIGRATED_DB) as conn:
        yield {**legacy_template, "conn": conn}


def _rejected(statement: str, params=None) -> subprocess.CompletedProcess[str]:
    """A copy of the template with one row broken, upgraded."""
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        conn.execute(statement, params)
    return _alembic(REJECTED_DB, TARGET)


_HELD_ROLE = """
    SELECT r.code, d.code, d.discipline, d.rated, r.workspace_id IS NULL, x.dimension_id = r.dimension_id
      FROM {table} x
      JOIN catalog.role r ON r.id = x.role_id
      JOIN catalog.role_dimension d ON d.id = r.dimension_id
     WHERE x.id = %s
"""


def test_the_preflight_is_silent_on_clean_data(legacy_template) -> None:
    assert {question: rows for question, rows in legacy_template["preflight"].items() if rows} == {}


def test_tier_native_ranges_preserve_values_and_resolve_on_the_stored_grid(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _rows(
        conn,
        "SELECT native_rank_min, native_rank_max FROM division_grid_tier WHERE version_id = %s ORDER BY sort_order",
        (ids["grid_version"],),
    ) == [(4900, 4700), (4500, 4699), (None, None), (2**40, 2**40 + 99)]
    assert (
        _rows(
            conn,
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = 'division_grid_tier' AND column_name LIKE 'ow_rank_%'",
        )
        == []
    )
    engine = create_engine(_url(MIGRATED_DB))
    try:
        with Session(engine) as session:
            version = session.get(DivisionGridVersion, ids["grid_version"])
            grid = DivisionGrid.from_version(version)
            assert normalize_native_ranks_to_grid(
                {7: {"tank": 4700, "support": 4500, "damage": 2**40 + 99}, 8: {"tank": 4699}}, grid
            ) == {7: {"tank": 2000, "support": 1900, "damage": 1700}, 8: {"tank": 1900}}
            for outside in (4499, 4901, 1800, 2**40 - 1, 2**40 + 100):
                assert grid.resolve_division_from_native_rank(outside) is None
    finally:
        engine.dispose()


def test_existing_grids_are_overwatch_grids(migrated) -> None:
    assert _rows(
        migrated["conn"], "SELECT discipline FROM division_grid WHERE id = %s", (migrated["ids"]["grid"],)
    ) == [("overwatch",)]


def test_workspace_defaults_carry_own_system_and_null_choices(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _rows(
        conn,
        """
        SELECT workspace_id, discipline, version_id FROM workspace_division_grid_default
         WHERE workspace_id IN (%s, %s, %s) ORDER BY workspace_id
    """,
        (ids["ws"], ids["null_ws"], ids["system_ws"]),
    ) == [
        (ids["ws"], "overwatch", ids["grid_version"]),
        (ids["system_ws"], "overwatch", ids["system_version"]),
    ]


def test_foreign_workspace_default_refuses_the_revision(legacy_template) -> None:
    ids = legacy_template["ids"]
    done = _rejected(
        "UPDATE workspace SET default_division_grid_version_id = %s WHERE id = %s",
        (ids["grid_version"], ids["system_ws"]),
    )
    assert done.returncode != 0
    assert "workspace grid defaults with a missing or foreign version" in done.stderr
    with _connect(REJECTED_DB) as conn:
        assert _scalar(conn, "SELECT version_num FROM alembic_version") == PRE_REVISION


def test_default_reconcile_detects_a_lost_assignment(migrated) -> None:
    ids = migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        tx.execute("DELETE FROM workspace_division_grid_default WHERE workspace_id = %s", (ids["ws"],))
        function, create, _, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        assert ("workspace grid defaults", ids["ws"], str(ids["grid_version"])) in _rows(tx, skipped)
        tx.rollback()


def test_a_grid_names_a_known_discipline(migrated) -> None:
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            tx.execute("UPDATE division_grid SET discipline = 'chess' WHERE id = %s", (migrated["ids"]["grid"],))
        tx.rollback()


def test_ranks_point_at_their_overwatch_module_role(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    for key, code in (("rank_tank", "tank"), ("rank_support", "support")):
        assert _rows(conn, _HELD_ROLE.format(table="balancer.member_rank"), (ids[key],)) == [
            (code, "player_role", "overwatch", True, True, True)
        ]


def test_hidden_ratings_point_at_their_module_role(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _rows(conn, _HELD_ROLE.format(table="balancer.member_hidden_rating"), (ids["hidden_damage"],)) == [
        ("damage", "player_role", "overwatch", True, True, True)
    ]


def test_flex_ranks_are_dropped_and_kept_for_the_reconcile(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _scalar(conn, "SELECT count(*) FROM balancer.member_rank WHERE id = %s", (ids["rank_flex"],)) == 0
    assert _scalar(conn, "SELECT count(*) FROM balancer.member_hidden_rating WHERE id = %s", (ids["hidden_flex"],)) == 0
    assert _rows(
        conn, "SELECT source, row_id, row_json ->> 'role' FROM balancer.discipline01c_dropped_ranks ORDER BY source"
    ) == [
        ("balancer.member_hidden_rating", ids["hidden_flex"], "flex"),
        ("balancer.member_rank", ids["rank_flex"], "flex"),
    ]


def test_rank_uniqueness_is_by_role_id(migrated) -> None:
    ids = migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        role_id, dimension_id = _rows(
            tx, "SELECT role_id, dimension_id FROM balancer.member_rank WHERE id = %s", (ids["rank_tank"],)
        )[0]
        with pytest.raises(psycopg.errors.UniqueViolation):
            tx.execute(
                "INSERT INTO balancer.member_rank (workspace_id, workspace_member_id, role_id, dimension_id, rank_value)"
                " VALUES (%s, %s, %s, %s, 1)",
                (ids["ws"], ids["member_canon"], role_id, dimension_id),
            )
        tx.rollback()


@pytest.mark.parametrize(
    ("table", "member_key", "role", "payload"),
    [
        ("balancer.member_rank", "member_canon", "Tank", {"rank_value": 1}),
        ("balancer.member_hidden_rating", "member_hidden", " damage", {"mu": 1.0, "sigma": 1.0}),
    ],
)
def test_roles_colliding_once_normalized_stop_the_revision(legacy_template, table, member_key, role, payload) -> None:
    ids = legacy_template["ids"]
    columns = {"workspace_id": ids["ws"], "workspace_member_id": ids[member_key], "role": role, **payload}
    done = _rejected(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
        tuple(columns.values()),
    )
    assert done.returncode != 0
    assert "discipline01c pre-flight failed" in done.stderr
    assert "collide once their role is normalized" in done.stderr


def test_the_reconcile_report_is_clean(migrated) -> None:
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        function, create, summary, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        statuses = {row[0]: row[3] for row in _rows(tx, summary)}
        listed = _rows(tx, skipped)
        tx.rollback()
    assert listed == []
    assert set(statuses.values()) == {"ok"}
    assert {"member ranks", "hidden ratings", "flex ranks (dropped)", "workspace grid defaults"} <= set(statuses)


@pytest.mark.parametrize(
    ("table", "key", "label", "code"),
    [
        ("balancer.member_rank", "rank_tank", "member ranks", "tank"),
        ("balancer.member_hidden_rating", "hidden_damage", "hidden ratings", "damage"),
    ],
)
@pytest.mark.parametrize("wrong_scope", ["discipline", "dimension", "workspace"])
def test_rank_reconcile_rejects_roles_outside_the_overwatch_rated_module(
    wrong_scope, table, key, label, code, migrated
) -> None:
    ids = migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        role_id, dimension_id = _rows(tx, f"SELECT role_id, dimension_id FROM {table} WHERE id = %s", (ids[key],))[0]
        values = {"dimension_id": dimension_id, "code": code, "name": code.title()}
        if wrong_scope in ("discipline", "dimension"):
            values["dimension_id"] = _insert(
                tx,
                "catalog.role_dimension",
                discipline="lol" if wrong_scope == "discipline" else "overwatch",
                code="other",
                name="Other",
                selection_mode="single",
                rated=wrong_scope == "discipline",
            )
        else:
            values.update(workspace_id=ids["ws"], parent_role_id=role_id, code=f"{code}_main")
        replacement = _insert(tx, "catalog.role", **values)
        tx.execute(
            f"UPDATE {table} SET role_id = %s, dimension_id = %s WHERE id = %s",
            (replacement, values["dimension_id"], ids[key]),
        )
        function, create, _, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        assert (label, ids[key], code) in _rows(tx, skipped)
        tx.rollback()


def test_the_chain_ends_at_discipline01c_with_every_constraint_validated(migrated) -> None:
    conn = migrated["conn"]
    assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == TARGET
    assert _rows(conn, "SELECT conrelid::regclass::text, conname FROM pg_constraint WHERE NOT convalidated") == []


@pytest.mark.parametrize("table", ["balancer.member_rank", "balancer.member_hidden_rating"])
def test_rank_role_foreign_keys_have_leading_indexes(migrated, table) -> None:
    assert _scalar(
        migrated["conn"],
        """SELECT EXISTS (
            SELECT 1 FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
            WHERE i.indrelid = %s::regclass AND a.attname = 'role_id'
              AND i.indisvalid AND i.indpred IS NULL
        )""",
        (table,),
    )


def test_initially_immediate_deferrable_constraint_stops_the_revision(legacy_template) -> None:
    done = _rejected("CREATE TABLE public.immediate_guard (id integer UNIQUE DEFERRABLE INITIALLY IMMEDIATE)")
    assert done.returncode != 0
    assert "discipline01c cannot restore INITIALLY IMMEDIATE constraints" in done.stderr
    with _connect(REJECTED_DB) as conn:
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == PRE_REVISION


@pytest.mark.parametrize(
    ("table", "key"), [("balancer.member_rank", "rank_tank"), ("balancer.member_hidden_rating", "hidden_damage")]
)
def test_role_and_dimension_cannot_disagree(migrated, table, key) -> None:
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        tx.execute(f"UPDATE {table} SET dimension_id = -1 WHERE id = %s", (migrated["ids"][key],))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            tx.execute("SET CONSTRAINTS ALL IMMEDIATE")
        tx.rollback()
