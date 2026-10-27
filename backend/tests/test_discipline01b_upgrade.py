"""``discipline01b`` against a POPULATED database (spec §14.3, §14.5, §14.6).

A template database is upgraded to ``discipline01`` (``enclayer02`` with its flag, as the release runs it), seeded with
the role data of every table P2 carries, checked by the operator's pre-flight, its live object names scrambled, upgraded
to ``discipline01b`` and read back. Copies with broken data must stop the revision with the offending rows listed.
Needs the ephemeral test Postgres; skips otherwise.
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
from psycopg.types.json import Json, Jsonb

from shared.disciplines import DISCIPLINES
from shared.domain.player_sub_roles import normalize_sub_role, workspace_sub_role_code
from shared.testing.db import MIGRATION_PROOF_SKIP, ensure_test_postgres, migration_proofs_enabled, postgres_env

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PRE_REVISION = "discipline01"
TARGET = "discipline01c"
TEMPLATE_DB = "discipline01b_legacy_tpl"
MIGRATED_DB = "discipline01b_migrated"
REJECTED_DB = "discipline01b_rejected"

_spec = importlib.util.spec_from_file_location(
    "discipline01b_revision", BACKEND / "migrations" / "versions" / "discipline01b_roles.py"
)
assert _spec is not None and _spec.loader is not None
revision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(revision)
_kept_spec = importlib.util.spec_from_file_location(
    "subrole01_revision", BACKEND / "migrations" / "versions" / "subrole01_kept_sub_roles_restorable.py"
)
assert _kept_spec is not None and _kept_spec.loader is not None
kept_revision = importlib.util.module_from_spec(_kept_spec)
_kept_spec.loader.exec_module(kept_revision)
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
    ids["ws_a"] = _insert(conn, "workspace", slug="d1b-a", name="d1b-a")
    ids["ws_b"] = _insert(conn, "workspace", slug="d1b-b", name="d1b-b")
    catalog = "tournament.player_sub_role"
    ids["hitscan"] = _insert(
        conn, catalog, workspace_id=ids["ws_a"], role="damage", slug="hitscan", label="Hitscan", sort_order=1
    )
    ids["main_heal"] = _insert(
        conn,
        catalog,
        workspace_id=ids["ws_a"],
        role="support",
        slug="main_heal",
        label="Main Heal",
        sort_order=2,
        description="Primary healer",
    )
    ids["off_tank"] = _insert(
        conn, catalog, workspace_id=ids["ws_a"], role="tank", slug="off tank", label="Off Tank", is_active=False
    )
    for key in ("a", "b"):
        ids[f"t_{key}"] = _insert(
            conn, "tournament.tournament", workspace_id=ids[f"ws_{key}"], name=key, slug=f"d1b-t-{key}", status="live"
        )
        ids[f"team_{key}"] = _insert(
            conn, "tournament.team", tournament_id=ids[f"t_{key}"], name=key, balancer_name=key
        )
    for key, side, role, sub_role in (
        ("by_slug", "a", "damage", "hitscan"),
        ("whitespace", "a", "damage", "\tHitscan\n"),
        ("by_label", "a", "support", "Main Heal"),
        ("off_catalog", "a", "support", "light heal"),
        ("plain", "a", "tank", None),
        ("flex_sub", "a", "flex", "main"),
        ("no_catalog", "b", "damage", "projectile"),
    ):
        user = _insert(conn, "players.user", name=f"d1b-{key}")
        ids[f"member_{key}"] = _insert(conn, "workspace_member", workspace_id=ids[f"ws_{side}"], player_id=user)
        ids[key] = _insert(
            conn,
            "tournament.player",
            tournament_id=ids[f"t_{side}"],
            team_id=ids[f"team_{side}"],
            workspace_member_id=ids[f"member_{key}"],
            name=key,
            rank=2000,
            role=role,
            sub_role=sub_role,
        )
    for key, side, role, subrole in (("reg_a", "a", "damage", "Hitscan"), ("reg_b", "b", "support", "main_heal")):
        ids[key] = _insert(conn, "balancer.registration", tournament_id=ids[f"t_{side}"])
        ids[f"{key}_role"] = _insert(
            conn, "balancer.registration_role", registration_id=ids[key], role=role, subrole=subrole, priority=1
        )
    _seed_encounter_roster(conn, ids)
    _seed_team_formats(conn, ids)
    return ids


def _scramble_names(conn) -> None:
    """Restored databases need not carry the migration chain's constraint names."""
    for table in (
        "balancer.registration_role",
        "encounter.team_member_role",
        "balancer.custom_game_player_role",
        "analytics.ml_model_artifact",
    ):
        for index, (name,) in enumerate(
            _rows(
                conn,
                "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype IN ('u', 'p')",
                (table,),
            )
        ):
            conn.execute(
                sql.SQL("ALTER TABLE {} RENAME CONSTRAINT {} TO {}").format(
                    sql.Identifier(*table.split(".")),
                    sql.Identifier(name),
                    sql.Identifier(f"restored_{index}_{table.split('.')[1]}"),
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


_SUB_ROLES = """
    SELECT r.workspace_id, m.code, r.code, r.name, r.description, r.sort_order, r.active, r.selectable
      FROM catalog.role r JOIN catalog.role m ON m.id = r.parent_role_id
     WHERE r.workspace_id = %s
     ORDER BY m.code, r.code
"""


def test_the_preflight_is_silent_on_clean_data(legacy_template) -> None:
    assert {question: rows for question, rows in legacy_template["preflight"].items() if rows} == {}


def test_the_overwatch_ontology_is_seeded_as_the_module_declares(migrated) -> None:
    conn = migrated["conn"]
    declared = DISCIPLINES["overwatch"].rated_dimension
    assert _rows(
        conn, "SELECT code, name, selection_mode, rated FROM catalog.role_dimension WHERE discipline = 'overwatch'"
    ) == [(declared.code, declared.name, declared.selection_mode, declared.rated)]
    assert _rows(
        conn,
        "SELECT r.code, r.name, r.sort_order FROM catalog.role r JOIN catalog.role_dimension d ON d.id = r.dimension_id"
        " WHERE d.discipline = 'overwatch' AND r.workspace_id IS NULL ORDER BY r.sort_order",
    ) == [(role.code, role.name, order) for order, role in enumerate(declared.roles)]


def test_catalog_sub_roles_become_workspace_roles_under_their_role(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _rows(conn, _SUB_ROLES, (ids["ws_a"],)) == [
        (ids["ws_a"], "damage", "damage_hitscan", "Hitscan", None, 1, True, True),
        (
            ids["ws_a"],
            "support",
            "support_light_heal",
            "light heal",
            "Kept by discipline01b: used by players or registrations, absent from the workspace sub-role catalog.",
            1000,
            False,
            False,
        ),
        (ids["ws_a"], "support", "support_main_heal", "Main Heal", "Primary healer", 2, True, True),
        (ids["ws_a"], "tank", "tank_off_tank", "Off Tank", None, 0, False, True),
    ]


def test_subrole01_makes_kept_sub_roles_plain_and_restorable(migrated) -> None:
    """The provenance note leaves the description, and ``selectable`` stops being a second, hidden off-switch."""
    conn, ids = migrated["conn"], migrated["ids"]
    with conn.transaction(force_rollback=True):
        conn.execute(kept_revision.UPGRADE)
        assert _rows(conn, _SUB_ROLES, (ids["ws_a"],)) == [
            (ids["ws_a"], "damage", "damage_hitscan", "Hitscan", None, 1, True, True),
            (ids["ws_a"], "support", "support_light_heal", "light heal", None, 1000, False, True),
            (ids["ws_a"], "support", "support_main_heal", "Main Heal", "Primary healer", 2, True, True),
            (ids["ws_a"], "tank", "tank_off_tank", "Off Tank", None, 0, False, True),
        ]


def test_legacy_whitespace_matches_the_existing_catalog_leaf(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    with conn.transaction(force_rollback=True):
        conn.execute(revision.LEAF_FUNCTION)
        leaf_id = _scalar(
            conn,
            "SELECT id FROM catalog.role WHERE workspace_id = %s AND code = 'damage_hitscan'",
            (ids["ws_a"],),
        )
        assert (
            _scalar(
                conn,
                "SELECT pg_temp.discipline01b_leaf(%s, 'damage', sub_role) FROM tournament.player WHERE id = %s",
                (ids["ws_a"], ids["whitespace"]),
            )
            == leaf_id
        )


def test_sql_normalization_matches_python_whitespace(migrated) -> None:
    # Python's whitespace set includes control separators and Unicode spaces that
    # PostgreSQL's locale-dependent \s does not necessarily recognise.
    whitespace = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680" + "".join(map(chr, range(0x2000, 0x200B)))
    whitespace += "\u2028\u2029\u202f\u205f\u3000"
    conn = migrated["conn"]
    for char in whitespace:
        for value in (f"{char}Hitscan{char}", f"Main{char}{char}Heal", char):
            assert _scalar(conn, f"SELECT {revision._code('%s')}", (value,)) == (normalize_sub_role(value) or "")
            assert _scalar(
                conn, f"SELECT {revision._workspace_code('%s', '%s')}", ("damage", value)
            ) == workspace_sub_role_code("damage", value)


def test_values_outside_the_catalog_become_inactive_unselectable_sub_roles(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert [
        (parent, code, active, selectable)
        for _, parent, code, _, _, _, active, selectable in _rows(conn, _SUB_ROLES, (ids["ws_b"],))
    ] == [("damage", "damage_projectile", False, False), ("support", "support_main_heal", False, False)]


def test_a_flex_sub_role_creates_nothing(migrated) -> None:
    conn = migrated["conn"]
    assert _scalar(conn, "SELECT count(*) FROM catalog.role WHERE code IN ('flex', 'flex_main')") == 0


@pytest.mark.parametrize(
    ("statement", "listed"),
    [
        (
            "INSERT INTO tournament.player_sub_role (workspace_id, role, slug, label) VALUES (%(ws)s, 'support', repeat('x', 57), 'Long')",
            "'code': 'support_" + "x" * 57 + "'",
        ),
        (
            "INSERT INTO tournament.player_sub_role (workspace_id, role, slug, label) VALUES (%(ws)s, 'flex', 'anchor', 'Anchor')",
            "'code': 'flex_anchor', 'parents': ['flex']",
        ),
        (
            "INSERT INTO tournament.player_sub_role (workspace_id, role, slug, label)"
            " VALUES (%(ws)s, 'support', 'Main', 'Main'), (%(ws)s, 'support', 'main', 'main')",
            "'code': 'support_main', 'parents': ['support', 'support']",
        ),
        (
            "INSERT INTO tournament.player_sub_role (workspace_id, role, slug, label)"
            " VALUES (%(ws)s, 'support', '', 'Empty')",
            "'code': None, 'parents': ['support']",
        ),
        (
            "INSERT INTO tournament.player_sub_role (workspace_id, role, slug, label)"
            " VALUES (%(ws)s, 'support', E' \\t\\n', 'Whitespace')",
            "'code': None, 'parents': ['support']",
        ),
    ],
)
def test_unusable_sub_role_codes_stop_the_revision(legacy_template, statement: str, listed: str) -> None:
    done = _rejected(statement, {"ws": legacy_template["ids"]["ws_a"]})
    assert done.returncode != 0
    assert "workspace sub-roles that cannot become catalog roles" in done.stderr
    assert listed in done.stderr


def test_shared_slugs_under_two_parents_in_two_workspaces_migrate_distinctly(legacy_template) -> None:
    _recreate(REJECTED_DB, TEMPLATE_DB)
    owners = [legacy_template["ids"][key] for key in ("ws_a", "ws_b")]
    with _connect(REJECTED_DB) as conn:
        for workspace_id in owners:
            for role in ("damage", "support"):
                for slug in ("main", "flex"):
                    _insert(
                        conn,
                        "tournament.player_sub_role",
                        workspace_id=workspace_id,
                        role=role,
                        slug=slug,
                        label=slug.title(),
                    )
        assert _rows(conn, revision.PREFLIGHT[3][1]) == []
    done = _alembic(REJECTED_DB, TARGET)
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        rows = _rows(
            conn, "SELECT id, workspace_id, code FROM catalog.role WHERE code IN ('damage_main', 'support_main')"
        )
        assert len({row[0] for row in rows}) == 4
        assert {(workspace_id, code) for _, workspace_id, code in rows} == {
            (workspace_id, code) for workspace_id in owners for code in ("damage_main", "support_main")
        }
        conn.execute(revision.LEAF_FUNCTION)
        for role_id, workspace_id, code in rows:
            parent = code.split("_", 1)[0]
            assert _scalar(conn, "SELECT pg_temp.discipline01b_leaf(%s, %s, 'main')", (workspace_id, parent)) == role_id
        _, create, _, skipped = _statements(RECONCILE_SQL)
        conn.execute(create)
        assert _rows(conn, skipped) == []


def test_role_values_outside_the_vocabulary_stop_the_revision(legacy_template) -> None:
    done = _rejected(
        "UPDATE balancer.registration_role SET role = 'healer' WHERE id = %s", (legacy_template["ids"]["reg_a_role"],)
    )
    assert done.returncode != 0
    assert "role values outside tank|damage|support|flex" in done.stderr
    assert "'source': 'balancer.registration_role', 'value': 'healer'" in done.stderr


def test_flex_where_a_role_is_required_stops_the_revision(legacy_template) -> None:
    row = legacy_template["ids"]["reg_b_role"]
    done = _rejected("UPDATE balancer.registration_role SET role = 'flex' WHERE id = %s", (row,))
    assert done.returncode != 0
    assert "flex where a role is required" in done.stderr
    assert f"'row_id': {row}" in done.stderr


def test_every_workspace_may_play_overwatch_only_by_default(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _scalar(conn, "SELECT disciplines_enabled FROM workspace WHERE id = %s", (ids["ws_a"],)) == ["overwatch"]


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
    assert {
        "sub-roles",
        "off-catalog sub-roles (kept inactive)",
        "flex sub-roles (dropped)",
        "team formats",
        "balancer configs",
        "player roles",
        "registration roles",
        "team member roles",
        "mix player roles",
        "draft roles",
        "balancer slots",
        "ml artifacts",
    } <= set(statuses)


def test_the_chain_ends_at_discipline01b_with_every_constraint_validated(migrated) -> None:
    conn = migrated["conn"]
    assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == TARGET
    assert _rows(conn, "SELECT conrelid::regclass::text, conname FROM pg_constraint WHERE NOT convalidated") == []


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("tournament.player_role", "role_id"),
        ("encounter.team_member_role", "role_id"),
        ("balancer.registration_role", "role_id"),
        ("balancer.custom_game_player_role", "role_id"),
        ("balancer.team_slot", "role_id"),
        ("balancer.draft_player", "captain_role_id"),
        ("balancer.draft_pick", "target_role_id"),
        ("roster.format_role_rule", "role_id"),
    ],
)
def test_assignment_role_foreign_keys_have_leading_indexes(migrated, table, column) -> None:
    assert _scalar(
        migrated["conn"],
        """SELECT EXISTS (
            SELECT 1 FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
            WHERE i.indrelid = %s::regclass AND a.attname = %s
              AND i.indisvalid AND i.indpred IS NULL
        )""",
        (table, column),
    )


def test_initially_immediate_deferrable_constraint_stops_the_revision(legacy_template) -> None:
    done = _rejected("CREATE TABLE public.immediate_guard (id integer UNIQUE DEFERRABLE INITIALLY IMMEDIATE)")
    assert done.returncode != 0
    assert "discipline01b cannot restore INITIALLY IMMEDIATE constraints" in done.stderr
    with _connect(REJECTED_DB) as conn:
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == PRE_REVISION


def _seed_team_formats(conn, ids: dict) -> None:
    """A workspace default, tournament override, inheriting tournament, two mixes and two configs."""
    conn.execute(
        "UPDATE workspace SET default_roster_slots_json = %s WHERE id = %s",
        (Jsonb({"tank": 1, "flex": 5}), ids["ws_a"]),
    )
    conn.execute(
        "UPDATE tournament.tournament SET roster_slots_json = %s WHERE id = %s", (Jsonb({"flex": 6}), ids["t_b"])
    )
    ids["t_c"] = _insert(
        conn, "tournament.tournament", workspace_id=ids["ws_b"], name="c", slug="d1b-t-c", status="live"
    )
    ids["host"] = _insert(
        conn, "auth.user", email="d1b-host@x", username="d1b-host", is_active=True, is_superuser=False, is_verified=True
    )
    conn.execute(
        "INSERT INTO balancer.user_config (user_id, config_json, role_slots_json) VALUES (%s, %s, %s)",
        (
            ids["host"],
            Jsonb({"role_settings": {"tank": {"mix_weight": 2.0}, "flex": {"mix_weight": 0.5}}}),
            Jsonb({"damage": 3, "support": 3}),
        ),
    )
    ids["rule_a"] = _insert(
        conn, "encounter.scoring_rule", workspace_id=ids["ws_a"], preset="wins", game_formula="1", end_formula="1"
    )
    ids["mix_host"] = _insert(
        conn,
        "balancer.custom_game",
        workspace_id=ids["ws_a"],
        name="host",
        scoring_rule_id=ids["rule_a"],
        host_user_id=ids["host"],
    )
    ids["mix_plain"] = _insert(
        conn, "balancer.custom_game", workspace_id=ids["ws_a"], name="plain", scoring_rule_id=ids["rule_a"]
    )
    user = _insert(conn, "players.user", name="d1b-mixer")
    member = _insert(conn, "workspace_member", workspace_id=ids["ws_a"], player_id=user)
    ids["mix_player"] = _insert(
        conn, "balancer.custom_game_player", custom_game_id=ids["mix_plain"], workspace_member_id=member
    )
    for priority, role in ((1, "support"), (2, "Tank")):
        conn.execute(
            "INSERT INTO balancer.custom_game_player_role (custom_game_player_id, role, priority) VALUES (%s, %s, %s)",
            (ids["mix_player"], role, priority),
        )
    ids["tconfig"] = _insert(
        conn,
        "balancer.tournament_config",
        tournament_id=ids["t_a"],
        workspace_id=ids["ws_a"],
        config_json=Json({"role_settings": {"flex": {"impact": 1.3}}}),
    )
    session_id = _insert(conn, "balancer.draft_session", tournament_id=ids["t_a"], workspace_id=ids["ws_a"])
    team = _insert(conn, "balancer.draft_team", session_id=session_id, name="A", draft_position=1)
    ids["captain"] = _insert(
        conn,
        "balancer.draft_player",
        session_id=session_id,
        registration_id=ids["reg_a"],
        is_captain=True,
        captain_role="Tank",
    )
    for overall, role in ((1, "damage"), (2, "flex"), (3, None)):
        ids[f"pick_{overall}"] = _insert(
            conn,
            "balancer.draft_pick",
            session_id=session_id,
            overall_no=overall,
            round_no=1,
            pick_in_round=overall,
            draft_team_id=team,
            target_role=role,
        )
    balance = _insert(conn, "balancer.balance", tournament_id=ids["t_a"], result_json=Json({}))
    bteam = _insert(conn, "balancer.team", balance_id=balance, name="A", balancer_name="A", avg_sr=0, total_sr=0)
    for key, role in (("slot_tank", "Tank"), ("slot_flex", "flex")):
        ids[key] = _insert(conn, "balancer.team_slot", team_id=bteam, role=role, assigned_rank=2000)
    algorithm = _insert(conn, "analytics.algorithms", name="d1b-algo")
    for key, role in (("artifact_tank", "tank"), ("artifact_all", None)):
        ids[key] = _insert(
            conn,
            "analytics.ml_model_artifact",
            algorithm_id=algorithm,
            model_kind="performance",
            role=role,
            version="1",
            storage_uri="s3://x",
            feature_version="1",
        )


def test_ml_artifacts_point_at_their_role_or_none(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    tank = _scalar(conn, "SELECT role_id FROM analytics.ml_model_artifact WHERE id = %s", (ids["artifact_tank"],))
    assert _scalar(conn, "SELECT code FROM catalog.role WHERE id = %s", (tank,)) == "tank"
    assert (
        _scalar(conn, "SELECT role_id FROM analytics.ml_model_artifact WHERE id = %s", (ids["artifact_all"],)) is None
    )


def test_balancer_slots_point_at_module_roles_and_flex_is_open(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    tank = _scalar(conn, "SELECT role_id FROM balancer.team_slot WHERE id = %s", (ids["slot_tank"],))
    assert _scalar(conn, "SELECT code FROM catalog.role WHERE id = %s", (tank,)) == "tank"
    assert _scalar(conn, "SELECT role_id FROM balancer.team_slot WHERE id = %s", (ids["slot_flex"],)) is None


def test_draft_roles_point_at_module_roles_and_flex_is_an_open_slot(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    code = "SELECT r.code FROM catalog.role r WHERE r.id = %s"
    captain = _scalar(conn, "SELECT captain_role_id FROM balancer.draft_player WHERE id = %s", (ids["captain"],))
    assert _scalar(conn, code, (captain,)) == "tank"
    picks = [
        _scalar(conn, "SELECT target_role_id FROM balancer.draft_pick WHERE id = %s", (ids[f"pick_{n}"],))
        for n in (1, 2, 3)
    ]
    assert _scalar(conn, code, (picks[0],)) == "damage"
    assert picks[1:] == [None, None]


_FORMAT = """
    SELECT f.preset_code, f.name, f.starter_min, f.starter_max, f.substitute_min, f.substitute_max, d.mode,
           coalesce((SELECT jsonb_object_agg(r.code, rr.hard_min ORDER BY r.code)
                       FROM roster.format_role_rule rr JOIN catalog.role r ON r.id = rr.role_id
                      WHERE rr.team_format_id = f.id AND rr.hard_min = rr.hard_max), '{{}}'::jsonb)
      FROM roster.team_format f JOIN roster.team_format_dimension d ON d.team_format_id = f.id
     WHERE {owner}
"""


def test_every_tournament_owns_a_copy_of_its_effective_slot_map(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    query = _FORMAT.format(owner="f.tournament_id = %s")
    assert _rows(conn, query, (ids["t_a"],)) == [(None, "Custom roster", 6, 6, 0, 0, "enforced", {"tank": 1})]
    assert _rows(conn, query, (ids["t_b"],)) == [(None, "Custom roster", 6, 6, 0, 0, "off", {})]
    assert _rows(conn, query, (ids["t_c"],)) == [
        ("role_queue_5v5", "5v5 role queue", 5, 5, 0, 0, "enforced", {"damage": 2, "support": 2, "tank": 1})
    ]


def test_a_workspace_default_becomes_that_workspace_s_overwatch_format(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    query = _FORMAT.format(owner="f.workspace_id = %s AND f.tournament_id IS NULL AND f.custom_game_id IS NULL")
    assert _rows(conn, query, (ids["ws_a"],)) == [(None, "Custom roster", 6, 6, 0, 0, "enforced", {"tank": 1})]
    assert _rows(conn, query, (ids["ws_b"],)) == []


def test_every_mix_freezes_its_host_s_shape_or_the_workspace_default(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    query = _FORMAT.format(owner="f.custom_game_id = %s")
    assert _rows(conn, query, (ids["mix_host"],)) == [
        (None, "Custom roster", 6, 6, 0, 0, "enforced", {"damage": 3, "support": 3})
    ]
    assert _rows(conn, query, (ids["mix_plain"],)) == [(None, "Custom roster", 6, 6, 0, 0, "enforced", {"tank": 1})]


def test_flex_weights_move_to_the_open_slot_settings(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _scalar(conn, "SELECT config_json FROM balancer.user_config WHERE user_id = %s", (ids["host"],)) == {
        "role_settings": {"tank": {"mix_weight": 2.0}},
        "open_slot_settings": {"mix_weight": 0.5},
    }
    assert _scalar(conn, "SELECT config_json FROM balancer.tournament_config WHERE id = %s", (ids["tconfig"],)) == {
        "role_settings": {},
        "open_slot_settings": {"impact": 1.3},
    }


def test_a_slot_map_that_cannot_become_a_format_stops_the_revision(legacy_template) -> None:
    tournament = legacy_template["ids"]["t_b"]
    done = _rejected(
        "UPDATE tournament.tournament SET roster_slots_json = %s WHERE id = %s", (Jsonb({"healer": 2}), tournament)
    )
    assert done.returncode != 0
    assert "roster slot maps that cannot become a team format" in done.stderr
    assert f"'source': 'tournament', 'owner_id': {tournament}" in done.stderr


def test_json_null_slot_maps_are_absent_in_preflight_and_transfer(legacy_template) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        conn.execute("UPDATE workspace SET default_roster_slots_json = 'null'::jsonb WHERE id = %s", (ids["ws_b"],))
        conn.execute("UPDATE tournament.tournament SET roster_slots_json = 'null'::jsonb WHERE id = %s", (ids["t_a"],))
        conn.execute(
            "UPDATE balancer.user_config SET role_slots_json = 'null'::jsonb WHERE user_id = %s", (ids["host"],)
        )
        assert _rows(conn, revision.PREFLIGHT[-1][1]) == []
    done = _alembic(REJECTED_DB, TARGET)
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB, autocommit=False) as conn:
        assert _rows(conn, _FORMAT.format(owner="f.tournament_id = %s"), (ids["t_a"],))[0][2:] == (
            6,
            6,
            0,
            0,
            "enforced",
            {"tank": 1},
        )
        assert _rows(conn, _FORMAT.format(owner="f.custom_game_id = %s"), (ids["mix_host"],))[0][2:] == (
            6,
            6,
            0,
            0,
            "enforced",
            {"tank": 1},
        )
        assert _rows(conn, _FORMAT.format(owner="f.tournament_id = %s"), (ids["t_c"],))[0][2:] == (
            5,
            5,
            0,
            0,
            "enforced",
            {"tank": 1, "damage": 2, "support": 2},
        )
        function, create, _, skipped = _statements(RECONCILE_SQL)
        conn.execute(function)
        conn.execute(create)
        assert _rows(conn, skipped) == []
        conn.rollback()


def test_reconcile_lists_every_owner_even_when_all_destination_formats_are_missing(migrated) -> None:
    ids = migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        tx.execute("DELETE FROM roster.team_format")
        function, create, _, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        missing = {(row[1], row[2]) for row in _rows(tx, skipped) if row[0] == "team formats"}
        tx.rollback()
    assert missing == {
        (ids["ws_a"], "workspace"),
        (ids["t_a"], "tournament"),
        (ids["t_b"], "tournament"),
        (ids["t_c"], "tournament"),
        (ids["mix_host"], "mix"),
        (ids["mix_plain"], "mix"),
    }


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE roster.team_format_dimension SET mode = 'off' WHERE team_format_id = %s",
        "UPDATE roster.format_role_rule SET hard_max = hard_min + 1 WHERE team_format_id = %s",
        "UPDATE roster.team_format SET starter_min = starter_min - 1 WHERE id = %s",
        "UPDATE roster.team_format SET starter_max = starter_max + 1 WHERE id = %s",
        "UPDATE roster.team_format SET substitute_max = 1 WHERE id = %s",
        "UPDATE roster.team_format SET substitute_min = 1, substitute_max = 1 WHERE id = %s",
    ],
)
def test_reconcile_rejects_changed_format_semantics(migrated, change) -> None:
    tournament_id = migrated["ids"]["t_a"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        format_id = _scalar(tx, "SELECT id FROM roster.team_format WHERE tournament_id = %s", (tournament_id,))
        tx.execute(change, (format_id,))
        function, create, _, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        assert ("team formats", tournament_id, "tournament") in _rows(tx, skipped)
        tx.rollback()


def test_reconcile_matches_workspace_defaults_by_discipline(migrated) -> None:
    workspace_id = migrated["ids"]["ws_a"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        tx.execute("INSERT INTO catalog.discipline (code, name) VALUES ('other', 'Other')")
        dimension = _insert(
            tx,
            "catalog.role_dimension",
            discipline="other",
            code="player_role",
            name="Role",
            selection_mode="single",
            rated=True,
        )
        role = _insert(tx, "catalog.role", dimension_id=dimension, code="tank", name="Tank")
        tx.execute(
            "DELETE FROM roster.team_format WHERE workspace_id = %s AND tournament_id IS NULL AND custom_game_id IS NULL",
            (workspace_id,),
        )
        format_id = _insert(
            tx,
            "roster.team_format",
            workspace_id=workspace_id,
            discipline="other",
            name="Same counts, different discipline",
            starter_min=6,
            starter_max=6,
        )
        tx.execute(
            "INSERT INTO roster.team_format_dimension (team_format_id, discipline, dimension_id, mode) VALUES (%s, 'other', %s, 'enforced')",
            (format_id, dimension),
        )
        tx.execute(
            "INSERT INTO roster.format_role_rule (team_format_id, dimension_id, role_id, hard_min, hard_max) VALUES (%s, %s, %s, 1, 1)",
            (format_id, dimension, role),
        )
        function, create, _, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        assert ("team formats", workspace_id, "workspace") in _rows(tx, skipped)
        tx.rollback()


_LEAF = """
    SELECT p.name, r.code, m.code, r.workspace_id
      FROM tournament.player p
      LEFT JOIN tournament.player_role pr ON pr.player_id = p.id
      LEFT JOIN catalog.role r ON r.id = pr.role_id
      LEFT JOIN catalog.role m ON m.id = r.parent_role_id
     WHERE p.id = ANY(%s)
     ORDER BY p.name
"""


def test_every_player_holds_one_leaf_role_and_flex_holds_none(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    keys = ["by_slug", "by_label", "off_catalog", "plain", "flex_sub", "no_catalog"]
    assert _rows(conn, _LEAF, ([ids[key] for key in keys],)) == [
        ("by_label", "support_main_heal", "support", ids["ws_a"]),
        ("by_slug", "damage_hitscan", "damage", ids["ws_a"]),
        ("flex_sub", None, None, None),
        ("no_catalog", "damage_projectile", "damage", ids["ws_b"]),
        ("off_catalog", "support_light_heal", "support", ids["ws_a"]),
        ("plain", "tank", None, None),
    ]


def test_registration_roles_point_at_their_leaf(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    rows = _rows(
        conn,
        "SELECT rr.id, r.code, m.code FROM balancer.registration_role rr JOIN catalog.role r ON r.id = rr.role_id"
        " LEFT JOIN catalog.role m ON m.id = r.parent_role_id WHERE rr.id = ANY(%s) ORDER BY rr.id",
        ([ids["reg_a_role"], ids["reg_b_role"]],),
    )
    assert rows == [
        (ids["reg_a_role"], "damage_hitscan", "damage"),
        (ids["reg_b_role"], "support_main_heal", "support"),
    ]
    names = {
        row[0]
        for row in _rows(
            conn, "SELECT conname FROM pg_constraint WHERE conrelid = 'balancer.registration_role'::regclass"
        )
    }
    assert {"uq_registration_role_role", "fk_registration_role_role"} <= names


def _seed_encounter_roster(conn, ids: dict) -> None:
    """A legacy role/sub-role pair, a flex member with a sub-role, and a plain role."""
    rule = _insert(
        conn, "encounter.scoring_rule", workspace_id=ids["ws_a"], preset="wins", game_formula="1", end_formula="1"
    )
    ids["enc"] = _insert(
        conn,
        "encounter.encounter",
        workspace_id=ids["ws_a"],
        discipline="overwatch",
        tournament_id=ids["t_a"],
        scoring_rule_id=rule,
        name="A vs A",
        slot_count=2,
        status="PENDING",
    )
    side = _insert(
        conn,
        "encounter.team",
        encounter_id=ids["enc"],
        tournament_id=ids["t_a"],
        slot=1,
        team_id=ids["team_a"],
        name="A",
    )
    for key, rows in (
        ("by_slug", ("damage", "hitscan")),
        ("flex_sub", ("flex", "main")),
        ("plain", ("tank",)),
    ):
        ids[f"tm_{key}"] = _insert(
            conn,
            "encounter.team_member",
            encounter_id=ids["enc"],
            encounter_team_id=side,
            active=True,
            workspace_member_id=ids[f"member_{key}"],
            display_name_snapshot=key,
        )
        for role in rows:
            conn.execute(
                "INSERT INTO encounter.team_member_role (team_member_id, dimension, role) VALUES (%s, 'player_role', %s)",
                (ids[f"tm_{key}"], role),
            )


def test_an_encounter_roster_holds_one_leaf_per_member_and_keeps_the_legacy_rows(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    rows = _rows(
        conn,
        "SELECT tm.display_name_snapshot, r.code FROM encounter.team_member tm"
        " LEFT JOIN encounter.team_member_role tmr ON tmr.team_member_id = tm.id"
        " LEFT JOIN catalog.role r ON r.id = tmr.role_id WHERE tm.encounter_id = %s ORDER BY 1",
        (ids["enc"],),
    )
    assert rows == [("by_slug", "damage_hitscan"), ("flex_sub", None), ("plain", "tank")]
    assert (
        _scalar(
            conn,
            "SELECT count(*) FROM encounter.team_member_role_legacy WHERE team_member_id = ANY(%s)",
            ([ids["tm_by_slug"], ids["tm_flex_sub"], ids["tm_plain"]],),
        )
        == 5
    )


@pytest.mark.parametrize("role", ("damage", "support"))
def test_flex_marker_preserves_the_known_roster_role(legacy_template, role) -> None:
    member = legacy_template["ids"]["tm_plain"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        conn.execute("DELETE FROM encounter.team_member_role WHERE team_member_id=%s", (member,))
        for value in (role, "flex"):
            conn.execute(
                "INSERT INTO encounter.team_member_role(team_member_id,dimension,role) VALUES(%s,'player_role',%s)",
                (member, value),
            )
        original = _rows(
            conn,
            "SELECT team_member_id,dimension,role FROM encounter.team_member_role WHERE team_member_id=%s ORDER BY role",
            (member,),
        )
    done = _alembic(REJECTED_DB, TARGET)
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        assert _rows(
            conn,
            "SELECT r.code FROM encounter.team_member_role a JOIN catalog.role r ON r.id=a.role_id"
            " WHERE a.team_member_id=%s",
            (member,),
        ) == [(role,)]
        assert (
            _rows(
                conn,
                "SELECT team_member_id,dimension,role FROM encounter.team_member_role_legacy"
                " WHERE team_member_id=%s ORDER BY role",
                (member,),
            )
            == original
        )


def test_a_roster_role_outside_player_role_stops_the_revision(legacy_template) -> None:
    done = _rejected(
        "INSERT INTO encounter.team_member_role (team_member_id, dimension, role) VALUES (%s, 'position', 'mid')",
        (legacy_template["ids"]["tm_plain"],),
    )
    assert done.returncode != 0
    assert "encounter roster roles outside dimension player_role" in done.stderr


@pytest.mark.parametrize("change", ["second_sub", "second_top", "orphan_sub"])
def test_an_ambiguous_roster_leaf_stops_the_revision(legacy_template, change) -> None:
    member = legacy_template["ids"]["tm_by_slug"]
    if change == "orphan_sub":
        done = _rejected(
            "DELETE FROM encounter.team_member_role WHERE team_member_id = %s AND role = 'damage'", (member,)
        )
    else:
        done = _rejected(
            "INSERT INTO encounter.team_member_role (team_member_id, dimension, role) VALUES (%s, 'player_role', %s)",
            (member, "projectile" if change == "second_sub" else "support"),
        )
    assert done.returncode != 0
    assert "encounter roster members whose leaf role is ambiguous" in done.stderr
    assert f"'team_member_id': {member}" in done.stderr


@pytest.mark.parametrize("member_key", ["tm_by_slug", "tm_flex_sub"])
def test_reconcile_rejects_extra_roster_assignments(migrated, member_key) -> None:
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        member = migrated["ids"][member_key]
        tx.execute(
            "INSERT INTO encounter.team_member_role (team_member_id, dimension_id, role_id)"
            " SELECT %s, r.dimension_id, r.id FROM catalog.role r JOIN catalog.role_dimension d ON d.id = r.dimension_id"
            " WHERE d.discipline = 'overwatch' AND d.code = 'player_role' AND r.workspace_id IS NULL AND r.code = 'support'",
            (member,),
        )
        function, create, _, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        assert any(row[0] == "team member roles" and row[1] == member for row in _rows(tx, skipped))
        tx.rollback()


def test_mix_player_roles_point_at_module_roles_in_priority_order(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _rows(
        conn,
        "SELECT r.code, p.priority FROM balancer.custom_game_player_role p JOIN catalog.role r ON r.id = p.role_id"
        " WHERE p.custom_game_player_id = %s ORDER BY p.priority",
        (ids["mix_player"],),
    ) == [("support", 1), ("tank", 2)]


@pytest.mark.parametrize("wrong_scope", ["discipline", "dimension", "workspace"])
def test_mix_role_reconcile_rejects_a_matching_code_outside_the_owners_rated_module(wrong_scope, migrated) -> None:
    ids = migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        role_id, dimension_id = _rows(
            tx,
            "SELECT role_id, dimension_id FROM balancer.custom_game_player_role"
            " WHERE custom_game_player_id = %s AND priority = 1",
            (ids["mix_player"],),
        )[0]
        values = {"dimension_id": dimension_id, "code": "support", "name": "Support"}
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
            values.update(workspace_id=ids["ws_a"], parent_role_id=role_id)
        replacement = _insert(tx, "catalog.role", **values)
        tx.execute(
            "UPDATE balancer.custom_game_player_role SET role_id = %s, dimension_id = %s"
            " WHERE custom_game_player_id = %s AND priority = 1",
            (replacement, values["dimension_id"], ids["mix_player"]),
        )
        function, create, _, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        assert ("mix player roles", ids["mix_player"], "support") in _rows(tx, skipped)
        tx.rollback()


@pytest.mark.parametrize("wrong_scope", ["discipline", "dimension", "workspace"])
def test_draft_role_reconcile_rejects_roles_outside_the_owners_rated_module(wrong_scope, migrated) -> None:
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        player_id, role_id, dimension_id = _rows(
            tx, "SELECT id, captain_role_id, dimension_id FROM balancer.draft_player WHERE captain_role_id IS NOT NULL"
        )[0]
        values = {"dimension_id": dimension_id, "code": "tank", "name": "Tank"}
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
            values.update(workspace_id=migrated["ids"]["ws_a"], parent_role_id=role_id)
        replacement = _insert(tx, "catalog.role", **values)
        tx.execute(
            "UPDATE balancer.draft_player SET captain_role_id = %s, dimension_id = %s WHERE id = %s",
            (replacement, values["dimension_id"], player_id),
        )
        function, create, _, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        assert ("draft roles", player_id, "captain Tank") in _rows(tx, skipped)
        tx.rollback()


@pytest.mark.parametrize("wrong_scope", ["discipline", "dimension", "workspace"])
def test_ml_artifact_reconcile_rejects_roles_outside_the_overwatch_rated_module(wrong_scope, migrated) -> None:
    ids = migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        role_id, dimension_id = _rows(
            tx,
            "SELECT role_id, dimension_id FROM analytics.ml_model_artifact WHERE id = %s",
            (ids["artifact_tank"],),
        )[0]
        values = {"dimension_id": dimension_id, "code": "tank", "name": "Tank"}
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
            values.update(workspace_id=ids["ws_a"], parent_role_id=role_id)
        replacement = _insert(tx, "catalog.role", **values)
        tx.execute(
            "UPDATE analytics.ml_model_artifact SET role_id = %s, dimension_id = %s WHERE id = %s",
            (replacement, values["dimension_id"], ids["artifact_tank"]),
        )
        function, create, _, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        assert ("ml artifacts", ids["artifact_tank"], "tank") in _rows(tx, skipped)
        tx.rollback()
