"""``discipline01`` against a POPULATED database with the ``overwatch`` catalog.

A template database is upgraded to ``mixround01`` (the revision before ``discipline01``; ``enclayer02`` with its flag,
as the release runs it), seeded with a legacy catalog, checked by the operator's pre-flight, upgraded to
``discipline01`` and read back. A copy whose map names collide after slugify must stop the revision with their ids.
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
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg import sql
from psycopg.types.json import Json, Jsonb

from shared.testing.db import MIGRATION_PROOF_SKIP, ensure_test_postgres, migration_proofs_enabled, postgres_env

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PRE_REVISION = "mixround01"
# The reconcile covers the whole release chain, run in one upgrade head.
TARGET = "discipline01c"
TEMPLATE_DB = "discipline01_legacy_tpl"
MIGRATED_DB = "discipline01_migrated"
REJECTED_DB = "discipline01_rejected"
#: Exercise both a row above its sequence and an issued (but absent) id above every row.
EXPLICIT_HERO_ID = 1200
ID_FLOOR = 2000
DANGLING_ID = 850  # below every new id, names no map

_spec = importlib.util.spec_from_file_location(
    "discipline01_revision", BACKEND / "migrations" / "versions" / "discipline01_catalog.py"
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


def _rows(conn, sql: str, params=None) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def _scalar(conn, sql: str, params=None):
    return conn.execute(sql, params).fetchone()[0]


def _insert(conn, table: str, **columns) -> int:
    names = ", ".join(f'"{name}"' for name in columns)
    placeholders = ", ".join(f"%({name})s" for name in columns)
    return conn.execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders}) RETURNING id", columns).fetchone()[0]


def _statements(sql: str) -> list[str]:
    text = "\n".join(
        line for line in sql.splitlines() if not line.startswith("\\") and not line.lstrip().startswith("--")
    )
    return [part.strip() for part in re.split(r";\s*\n", text + "\n") if part.strip()]


def _seed(conn) -> dict:
    ids: dict = {}
    # Leave a deleted map behind the surviving rows.
    conn.execute("SELECT setval(pg_get_serial_sequence('overwatch.map', 'id'), 900, true)")
    ids["control"] = _insert(
        conn,
        "overwatch.gamemode",
        slug="control-d1",
        name="Control D1",
        image_path="https://cdn/control.png",
        description="Best of three",
        aliases=Jsonb(["Контроль"]),
    )
    ids["push"] = _insert(conn, "overwatch.gamemode", slug="push-d1", name="Push D1", image_path="", aliases=Jsonb([]))
    ids["ilios"] = _insert(
        conn,
        "overwatch.map",
        gamemode_id=ids["control"],
        name="Ilios D1",
        image_path="https://cdn/ilios.jpg",
        in_competitive=True,
        aliases=Jsonb(["Илиос"]),
    )
    ids["kings"] = _insert(
        conn,
        "overwatch.map",
        gamemode_id=ids["push"],
        name="King's Row D1",
        image_path="https://cdn/kings.jpg",
        in_competitive=False,
        aliases=Jsonb([]),
    )
    ids["colosseo"] = _insert(
        conn,
        "overwatch.map",
        gamemode_id=ids["push"],
        name="Колизей",
        image_path="",
        in_competitive=True,
        aliases=Jsonb([]),
    )
    ids["ana"] = _insert(
        conn,
        "overwatch.hero",
        slug="ana-d1",
        name="Ana D1",
        image_path="https://cdn/ana.png",
        type="support",
        color="#718ab3",
        aliases=Jsonb(["Ана"]),
    )
    ids["rein"] = _insert(
        conn,
        "overwatch.hero",
        id=EXPLICIT_HERO_ID,
        slug="reinhardt-d1",
        name="Reinhardt D1",
        image_path="https://cdn/rein.png",
        type="tank",
        aliases=Jsonb([]),
    )
    ids["miss_open"] = _insert(
        conn,
        "overwatch.catalog_alias_miss",
        entity_type="hero",
        raw_name="Анна",
        occurrences=3,
    )
    ids["miss_closed"] = _insert(
        conn,
        "overwatch.catalog_alias_miss",
        entity_type="gamemode",
        raw_name="Захват",
        occurrences=1,
        resolved_at="2026-10-01T00:00:00Z",
    )
    conn.execute("SELECT setval(pg_get_serial_sequence('overwatch.gamemode', 'id'), %s, true)", (ID_FLOOR,))
    _seed_map_references(conn, ids)
    _seed_hero_references(conn, ids)
    return ids


def _rename_legacy_objects(conn) -> None:
    """A restored database need not have any chain-generated constraint/index/sequence names."""
    tables = (
        "encounter.game",
        "balancer.custom_game_lobby",
        "matches.match",
        "casual.match",
        "matches.statistics",
        "matches.event",
        "matches.kill_feed",
        "balancer.registration_role_hero",
        "achievements.rule",
    )
    for table in tables:
        names = _rows(
            conn,
            "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype IN ('f', 'p', 'u')"
            " ORDER BY conname",
            (table,),
        )
        for index, (name,) in enumerate(names):
            conn.execute(
                sql.SQL("ALTER TABLE {} RENAME CONSTRAINT {} TO {}").format(
                    sql.Identifier(*table.split(".")),
                    sql.Identifier(name),
                    sql.Identifier(f"restored_{table.replace('.', '_')}_{index}"),
                )
            )
    conn.execute('ALTER INDEX balancer.ix_balancer_registration_role_hero_role_id RENAME TO "restored_role_lookup"')
    for table in ("overwatch.hero", "overwatch.map", "overwatch.gamemode", "balancer.registration_role_hero"):
        sequence = _scalar(conn, "SELECT pg_get_serial_sequence(%s, 'id')", (table,))
        conn.execute(
            sql.SQL("ALTER SEQUENCE {} RENAME TO {}").format(
                sql.SQL(sequence), sql.Identifier(f"restored_{table.split('.')[1]}_serial")
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
        preflight = {question: _rows(conn, sql) for question, sql in revision.PREFLIGHT}
        dangling = _scalar(conn, revision.DANGLING_PICK_BAN_IDS)
        _rename_legacy_objects(conn)
    yield {"ids": ids, "preflight": preflight, "dangling": dangling}
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


def _entity_of(conn, legacy_kind: str, legacy_id: int) -> int:
    return _scalar(
        conn,
        "SELECT entity_id FROM catalog.entity_legacy WHERE legacy_kind = %s AND legacy_id = %s",
        (legacy_kind, legacy_id),
    )


_ENTITY = "SELECT discipline, kind, slug, name, image_path, parent_id, attrs, aliases, active FROM catalog.entity WHERE id = %s"


def test_the_preflight_is_silent_on_clean_legacy_data(legacy_template) -> None:
    assert {q: rows for q, rows in legacy_template["preflight"].items() if rows} == {}


def test_maps_colliding_after_slugify_stop_the_revision(legacy_template) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        twin = _insert(
            conn, "overwatch.map", gamemode_id=ids["control"], name="ILIOS  d1!", image_path="", aliases=Jsonb([])
        )
    done = _alembic(REJECTED_DB, TARGET)
    assert done.returncode != 0
    assert "maps whose names collide after slugify" in done.stderr
    assert str(ids["ilios"]) in done.stderr and str(twin) in done.stderr


@pytest.mark.parametrize(
    ("legacy_kind", "column", "field", "character", "limit", "id_key"),
    [
        ("hero", "slug", "slug", "h", 64, "ana"),
        ("gamemode", "slug", "slug", "g", 64, "control"),
        ("map", "name", "slug", "m", 64, "ilios"),
        ("hero", "name", "name", "英", 128, "ana"),
        ("gamemode", "name", "name", "模", 128, "control"),
        ("map", "name", "name", "К", 128, "colosseo"),
    ],
)
def test_overlong_catalog_values_stop_before_copy_and_are_listed(
    legacy_template, legacy_kind, column, field, character, limit, id_key
) -> None:
    legacy_id = legacy_template["ids"][id_key]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        conn.execute(
            f"UPDATE overwatch.{legacy_kind} SET {column} = %s WHERE id = %s",
            (character * limit, legacy_id),
        )
        assert {q: _rows(conn, sql) for q, sql in revision.PREFLIGHT if _rows(conn, sql)} == {}
        conn.execute(
            f"UPDATE overwatch.{legacy_kind} SET {column} = %s WHERE id = %s",
            (character * (limit + 1), legacy_id),
        )
    done = _alembic(REJECTED_DB, TARGET)
    assert done.returncode != 0
    assert "catalog values too long" in done.stderr
    assert f"'legacy_kind': '{legacy_kind}'" in done.stderr
    assert f"'legacy_id': {legacy_id}" in done.stderr
    assert f"'field': '{field}'" in done.stderr
    assert f"'value_length': {limit + 1}" in done.stderr
    with _connect(REJECTED_DB) as conn:
        query = dict(revision.PREFLIGHT)["catalog values too long"]
        assert _rows(conn, query) == [(legacy_kind, legacy_id, field, limit + 1)]
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == PRE_REVISION
        assert _scalar(conn, "SELECT to_regclass('catalog.entity')") is None
        assert _scalar(
            conn, f"SELECT {column} FROM overwatch.{legacy_kind} WHERE id = %s", (legacy_id,)
        ) == character * (limit + 1)


def test_gamemodes_become_modes(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _rows(conn, _ENTITY, (_entity_of(conn, "gamemode", ids["control"]),)) == [
        (
            "overwatch",
            "mode",
            "control-d1",
            "Control D1",
            "https://cdn/control.png",
            None,
            {"description": "Best of three"},
            ["Контроль"],
            True,
        )
    ]
    assert _rows(conn, _ENTITY, (_entity_of(conn, "gamemode", ids["push"]),)) == [
        ("overwatch", "mode", "push-d1", "Push D1", "", None, {}, [], True)
    ]


def test_heroes_become_characters_with_their_class_and_color(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _rows(conn, _ENTITY, (_entity_of(conn, "hero", ids["ana"]),)) == [
        (
            "overwatch",
            "character",
            "ana-d1",
            "Ana D1",
            "https://cdn/ana.png",
            None,
            {"class": "support", "color": "#718ab3"},
            ["Ана"],
            True,
        )
    ]
    assert _rows(conn, "SELECT attrs FROM catalog.entity WHERE id = %s", (_entity_of(conn, "hero", ids["rein"]),)) == [
        ({"class": "tank", "color": "#ffffff"},)
    ]


def test_maps_get_a_slug_their_mode_as_parent_and_the_competitive_flag(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    control, push = _entity_of(conn, "gamemode", ids["control"]), _entity_of(conn, "gamemode", ids["push"])
    assert _rows(conn, _ENTITY, (_entity_of(conn, "map", ids["ilios"]),)) == [
        (
            "overwatch",
            "map",
            "ilios-d1",
            "Ilios D1",
            "https://cdn/ilios.jpg",
            control,
            {"in_competitive": True},
            ["Илиос"],
            True,
        )
    ]
    kings = _rows(
        conn,
        "SELECT slug, parent_id, attrs FROM catalog.entity WHERE id = %s",
        (_entity_of(conn, "map", ids["kings"]),),
    )
    assert kings == [("king-s-row-d1", push, {"in_competitive": False})]
    assert (
        _scalar(conn, "SELECT slug FROM catalog.entity WHERE id = %s", (_entity_of(conn, "map", ids["colosseo"]),))
        == "map"
    )


def test_new_ids_start_above_every_id_overwatch_ever_issued(migrated) -> None:
    conn = migrated["conn"]
    assert _scalar(conn, "SELECT min(id) FROM catalog.entity") > ID_FLOOR
    assert _scalar(conn, "SELECT count(*) FROM catalog.entity_legacy") == 7
    assert _scalar(conn, "SELECT count(DISTINCT entity_id) FROM catalog.entity_legacy") == 7
    assert _entity_of(conn, "hero", EXPLICIT_HERO_ID) > ID_FLOOR


def test_a_row_above_its_sequence_is_also_an_id_floor(legacy_template) -> None:
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        assert _scalar(conn, "SELECT max(id) FROM overwatch.hero") == EXPLICIT_HERO_ID
        assert (
            _scalar(conn, "SELECT pg_sequence_last_value(pg_get_serial_sequence('overwatch.hero', 'id')::regclass)")
            < EXPLICIT_HERO_ID
        )
        conn.execute("SELECT setval(pg_get_serial_sequence('overwatch.gamemode', 'id'), 1000, true)")
    done = _alembic(REJECTED_DB, TARGET)
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        assert _scalar(conn, "SELECT min(id) FROM catalog.entity") > EXPLICIT_HERO_ID


def test_absent_casual_match_is_skipped_and_surviving_map_code_is_rewritten(legacy_template) -> None:
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        conn.execute("DROP TABLE casual.match CASCADE")
        conn.execute(
            "CREATE TABLE tournament.encounter_map_code (id BIGSERIAL PRIMARY KEY,"
            " map_id BIGINT CONSTRAINT restored_map_reference REFERENCES overwatch.map(id))"
        )
        code = _insert(conn, "tournament.encounter_map_code", map_id=legacy_template["ids"]["ilios"])
    done = _alembic(REJECTED_DB, TARGET)
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        assert _scalar(conn, "SELECT map_id FROM tournament.encounter_map_code WHERE id = %s", (code,)) == _entity_of(
            conn, "map", legacy_template["ids"]["ilios"]
        )


@pytest.mark.parametrize("matches", (0, 2))
def test_a_missing_or_ambiguous_foreign_key_stops_instead_of_guessing(legacy_template, matches) -> None:
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        if matches == 0:
            name = _scalar(
                conn,
                "SELECT c.conname FROM pg_constraint c JOIN pg_attribute a"
                " ON a.attrelid = c.conrelid AND c.conkey = ARRAY[a.attnum]"
                " WHERE c.conrelid = 'encounter.game'::regclass AND c.contype = 'f' AND a.attname = 'map_id'",
            )
            conn.execute(sql.SQL("ALTER TABLE encounter.game DROP CONSTRAINT {}").format(sql.Identifier(name)))
        else:
            conn.execute("ALTER TABLE encounter.game ADD FOREIGN KEY (map_id) REFERENCES overwatch.map(id)")
    done = _alembic(REJECTED_DB, TARGET)
    assert done.returncode != 0
    assert "expected exactly one f on encounter.game('map_id',)" in done.stderr
    with _connect(REJECTED_DB) as conn:
        assert _scalar(conn, "SELECT to_regclass('catalog.entity')") is None
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == PRE_REVISION


def test_upgrade_restores_deferral_for_the_following_revision(legacy_template) -> None:
    _recreate(REJECTED_DB, TEMPLATE_DB)
    engine = sa.create_engine(_url(REJECTED_DB))
    try:
        with engine.connect() as conn, conn.begin() as tx:
            conn.exec_driver_sql("CREATE TABLE deferral_probe (value INTEGER UNIQUE DEFERRABLE INITIALLY DEFERRED)")
            conn.exec_driver_sql("INSERT INTO deferral_probe VALUES (1)")
            with Operations.context(MigrationContext.configure(conn)):
                revision.upgrade()
            conn.exec_driver_sql("INSERT INTO deferral_probe VALUES (1)")
            conn.exec_driver_sql("DELETE FROM deferral_probe")
            conn.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
            tx.rollback()
    finally:
        engine.dispose()


def test_one_invocation_upgrades_the_predecessor_through_discipline01(legacy_template) -> None:
    _recreate(REJECTED_DB)
    done = _alembic(REJECTED_DB, "enclayer02", OWT_APPLY_ENCOUNTER_LAYER_DROP="1")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        mode = _insert(conn, "overwatch.gamemode", slug="single", name="Single", image_path="")
        map_id = _insert(conn, "overwatch.map", name="Single map", gamemode_id=mode, image_path="")
        workspace = _insert(conn, "workspace", slug="single", name="Single")
        mix = _insert(conn, "balancer.custom_game", workspace_id=workspace, name="Single")
        match = _insert(conn, "casual.match", custom_game_id=mix, lobby_index=0, map_id=map_id)
        _insert(conn, "casual.team", match_id=match, side="home", name="A", score=1)
        _insert(conn, "casual.team", match_id=match, side="away", name="B", score=0)
    done = _alembic(REJECTED_DB, TARGET)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "enclayer02 -> mixround01" in done.stderr and "mixround01 -> discipline01" in done.stderr
    with _connect(REJECTED_DB) as conn:
        assert _rows(conn, "SELECT map_id, map_kind FROM encounter.game") == [(_entity_of(conn, "map", map_id), "map")]
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == TARGET


def test_alias_misses_move_with_their_kind(migrated) -> None:
    conn = migrated["conn"]
    rows = _rows(
        conn,
        "SELECT discipline, kind, raw_name, occurrences, resolved_at IS NOT NULL, last_ingest_job_id"
        " FROM catalog.alias_miss WHERE raw_name IN ('Анна', 'Захват')",
    )
    assert set(rows) == {
        ("overwatch", "mode", "Захват", 1, True, None),
        ("overwatch", "character", "Анна", 3, False, None),
    }


def test_league_of_legends_is_a_known_discipline(migrated) -> None:
    assert _rows(migrated["conn"], "SELECT name FROM catalog.discipline WHERE code = 'lol'") == [("League of Legends",)]


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
    assert {"heroes", "gamemodes", "maps", "alias misses", "pick-ban ids"} <= set(statuses)


def test_the_chain_ends_at_discipline01_with_every_constraint_validated(migrated) -> None:
    conn = migrated["conn"]
    assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == TARGET
    assert _rows(conn, "SELECT conrelid::regclass::text, conname FROM pg_constraint WHERE NOT convalidated") == []


def _seed_map_references(conn, ids: dict) -> None:
    """Every kind of map reference: a game, a mix lobby, the legacy stats and mix rows, and a whole map pick-ban."""
    ilios, kings, colosseo = ids["ilios"], ids["kings"], ids["colosseo"]
    ids["ws"] = _insert(conn, "workspace", slug="disc01-up", name="disc01-up")
    ids["rule"] = _insert(
        conn, "encounter.scoring_rule", workspace_id=ids["ws"], preset="wins", game_formula="1", end_formula="1"
    )
    ids["t"] = _insert(conn, "tournament.tournament", workspace_id=ids["ws"], name="T", slug="disc01-t", status="live")
    ids["team_a"] = _insert(conn, "tournament.team", tournament_id=ids["t"], name="A", balancer_name="A")
    ids["team_b"] = _insert(conn, "tournament.team", tournament_id=ids["t"], name="B", balancer_name="B")
    ids["enc"] = _insert(
        conn,
        "encounter.encounter",
        workspace_id=ids["ws"],
        discipline="overwatch",
        tournament_id=ids["t"],
        scoring_rule_id=ids["rule"],
        name="A vs B",
        slot_count=2,
        status="PENDING",
    )
    ids["game"] = _insert(conn, "encounter.game", encounter_id=ids["enc"], position=1, map_id=ilios)
    ids["game_unmapped"] = _insert(conn, "encounter.game", encounter_id=ids["enc"], position=2)
    ids["mix"] = _insert(
        conn, "balancer.custom_game", workspace_id=ids["ws"], name="Friday", scoring_rule_id=ids["rule"]
    )
    conn.execute(
        "INSERT INTO balancer.custom_game_lobby (custom_game_id, lobby_index, next_map_id) VALUES (%s, 0, %s)",
        (ids["mix"], kings),
    )
    ids["match"] = _insert(
        conn,
        "matches.match",
        home_team_id=ids["team_a"],
        away_team_id=ids["team_b"],
        home_score=2,
        away_score=1,
        encounter_id=ids["enc"],
        map_id=ilios,
    )
    ids["casual"] = _insert(conn, "casual.match", custom_game_id=ids["mix"], lobby_index=0, map_id=kings)
    not_kings = {"type": "not", "child": {"type": "item_in", "params": {"item_ids": [kings]}}}
    ruleset = {"version": 2, "phases": [{"id": "p", "pool_filter": not_kings, "steps": []}]}
    ids["config"] = _insert(
        conn, "tournament.pick_ban_config", tournament_id=ids["t"], kind="map", mode="slots", ruleset_json=Json(ruleset)
    )
    ids["config_item"] = _insert(
        conn, "tournament.pick_ban_config_item", pick_ban_config_id=ids["config"], item_id=ilios
    )
    ids["config_dangling"] = _insert(
        conn, "tournament.pick_ban_config_item", pick_ban_config_id=ids["config"], item_id=DANGLING_ID
    )
    ids["slot"] = _insert(
        conn, "tournament.pick_ban_config_slot", pick_ban_config_id=ids["config"], position=1, reserve_item_id=kings
    )
    ids["slot_item"] = _insert(
        conn, "tournament.pick_ban_config_slot_item", pick_ban_config_slot_id=ids["slot"], item_id=colosseo
    )
    sequence = [
        {"index": 0, "action": "ban", "eligible": {"type": "item_in", "params": {"item_ids": [ilios]}}},
        {"index": 1, "action": "side_pick", "eligible": {}},
    ]
    ids["session"] = _insert(
        conn,
        "encounter.pick_ban_session",
        encounter_id=ids["enc"],
        kind="map",
        seed_source="bracket_slot",
        pool_json=Json({"mode": "slots", "rotation": "fixed", "items": [ilios], "slots": [[ilios, colosseo]]}),
        slot_reserves_json=Json({"1": kings}),
        ruleset_json=Json(ruleset),
        resolved_sequence_json=Json(sequence),
    )
    ids["entry"] = _insert(
        conn, "encounter.pick_ban_entry", session_id=ids["session"], encounter_id=ids["enc"], item_id=ilios, order=0
    )
    for key, step, item in (("sub_ban", 0, ilios), ("sub_side", 1, ilios)):
        ids[key] = _insert(
            conn,
            "encounter.pick_ban_submission",
            session_id=ids["session"],
            encounter_id=ids["enc"],
            step_index=step,
            state="locked",
            items_json=Json([{"item_id": item, "target_player_id": None}]),
        )
    for key, action, data in (
        (
            "ev_acted",
            "acted",
            {"step_index": 0, "round": 1, "action": "ban", "item_id": ilios, "target_player_id": None},
        ),
        ("ev_auto", "step_auto_resolved", {"step_index": 0, "round": 1, "action": "ban", "item_ids": [ilios]}),
        (
            "ev_draft",
            "draft_locked",
            {"step_index": 0, "round": 1, "items": [{"item_id": ilios, "target_player_id": None}]},
        ),
        # A side_pick names a side index; the legacy map id stands in for one so that a rewrite would show.
        (
            "ev_side",
            "acted",
            {"step_index": 1, "round": 1, "action": "side_pick", "item_id": ilios, "target_player_id": None},
        ),
    ):
        ids[key] = _insert(
            conn,
            "encounter.room_event",
            encounter_id=ids["enc"],
            kind="map",
            action=action,
            source="captain",
            data=Json(data),
        )


def test_the_preflight_counts_the_pick_ban_id_it_cannot_map(legacy_template) -> None:
    assert legacy_template["dangling"] == 1


def test_games_lobbies_and_legacy_rows_point_at_the_map_entities(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    ilios, kings = _entity_of(conn, "map", ids["ilios"]), _entity_of(conn, "map", ids["kings"])
    assert _rows(
        conn,
        "SELECT map_id, map_kind FROM encounter.game WHERE id IN (%s, %s) ORDER BY position",
        (ids["game"], ids["game_unmapped"]),
    ) == [(ilios, "map"), (None, "map")]
    assert _rows(
        conn,
        "SELECT next_map_id, next_map_kind FROM balancer.custom_game_lobby WHERE custom_game_id = %s",
        (ids["mix"],),
    ) == [(kings, "map")]
    assert _scalar(conn, "SELECT map_id FROM matches.match WHERE id = %s", (ids["match"],)) == ilios
    assert _scalar(conn, "SELECT map_id FROM casual.match WHERE id = %s", (ids["casual"],)) == kings


def test_pick_ban_config_columns_and_rules_are_rewritten(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    ilios, kings, colosseo = (_entity_of(conn, "map", ids[key]) for key in ("ilios", "kings", "colosseo"))
    assert (
        _scalar(conn, "SELECT item_id FROM tournament.pick_ban_config_item WHERE id = %s", (ids["config_item"],))
        == ilios
    )
    assert (
        _scalar(conn, "SELECT item_id FROM tournament.pick_ban_config_item WHERE id = %s", (ids["config_dangling"],))
        == DANGLING_ID
    )
    assert (
        _scalar(conn, "SELECT reserve_item_id FROM tournament.pick_ban_config_slot WHERE id = %s", (ids["slot"],))
        == kings
    )
    assert (
        _scalar(conn, "SELECT item_id FROM tournament.pick_ban_config_slot_item WHERE id = %s", (ids["slot_item"],))
        == colosseo
    )
    ruleset = _scalar(conn, "SELECT ruleset_json FROM tournament.pick_ban_config WHERE id = %s", (ids["config"],))
    assert ruleset["phases"][0]["pool_filter"]["child"]["params"]["item_ids"] == [kings]


def test_a_session_snapshot_and_its_board_are_rewritten(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    ilios, kings, colosseo = (_entity_of(conn, "map", ids[key]) for key in ("ilios", "kings", "colosseo"))
    pool, reserves, ruleset, sequence = _rows(
        conn,
        "SELECT pool_json, slot_reserves_json, ruleset_json, resolved_sequence_json FROM encounter.pick_ban_session WHERE id = %s",
        (ids["session"],),
    )[0]
    assert (pool["items"], pool["slots"], pool["mode"]) == ([ilios], [[ilios, colosseo]], "slots")
    assert reserves == {"1": kings}
    assert ruleset["phases"][0]["pool_filter"]["child"]["params"]["item_ids"] == [kings]
    assert sequence[0]["eligible"]["params"]["item_ids"] == [ilios]
    assert _scalar(conn, "SELECT item_id FROM encounter.pick_ban_entry WHERE id = %s", (ids["entry"],)) == ilios


def test_submissions_and_the_room_journal_are_rewritten_except_side_picks(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    ilios = _entity_of(conn, "map", ids["ilios"])
    legacy = ids["ilios"]
    items = dict(
        _rows(conn, "SELECT id, items_json FROM encounter.pick_ban_submission WHERE session_id = %s", (ids["session"],))
    )
    assert items[ids["sub_ban"]] == [{"item_id": ilios, "target_player_id": None}]
    assert items[ids["sub_side"]] == [{"item_id": legacy, "target_player_id": None}]
    data = dict(_rows(conn, "SELECT id, data FROM encounter.room_event WHERE encounter_id = %s", (ids["enc"],)))
    assert data[ids["ev_acted"]]["item_id"] == ilios
    assert data[ids["ev_auto"]]["item_ids"] == [ilios]
    assert data[ids["ev_draft"]]["items"] == [{"item_id": ilios, "target_player_id": None}]
    assert data[ids["ev_side"]]["item_id"] == legacy


def test_the_hero_stats_view_joins_the_catalog_and_waits_for_its_refresh(migrated) -> None:
    conn = migrated["conn"]
    definition = _scalar(conn, "SELECT pg_get_viewdef('matches.mv_hero_global_stats'::regclass)")
    assert "catalog.entity" in definition and "overwatch." not in definition
    assert (
        _scalar(conn, "SELECT relispopulated FROM pg_class WHERE oid = 'matches.mv_hero_global_stats'::regclass")
        is False
    )
    assert _scalar(conn, "SELECT count(*) FROM pg_indexes WHERE indexname = 'ix_mv_hero_global_stats_name_hero'") == 1


def test_no_reference_outside_the_legacy_schema_points_at_the_old_catalog(migrated) -> None:
    rows = _rows(
        migrated["conn"],
        "SELECT conrelid::regclass::text, conname FROM pg_constraint WHERE contype = 'f'"
        " AND confrelid IN ('overwatch.map'::regclass, 'overwatch.gamemode'::regclass, 'overwatch.hero'::regclass)"
        " AND conrelid::regclass::text NOT LIKE 'overwatch.%'",
    )
    assert rows == []


def test_the_reconcile_lists_a_soft_id_left_in_legacy_space(migrated) -> None:
    ids = migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        tx.execute(
            "UPDATE tournament.pick_ban_config_item SET item_id = %s WHERE id = %s", (ids["ilios"], ids["config_item"])
        )
        function, create, summary, skipped = _statements(RECONCILE_SQL)
        tx.execute(function)
        tx.execute(create)
        statuses = {row[0]: row[3] for row in _rows(tx, summary)}
        listed = _rows(tx, skipped)
        tx.rollback()
    assert statuses["pick-ban ids"] == "MISMATCH"
    assert [(cls, legacy_id) for cls, legacy_id, _detail in listed] == [("pick-ban ids", ids["config_item"])]


def _seed_hero_references(conn, ids: dict) -> None:
    """Every kind of hero reference: legacy stats, a registration's top hero, an achievement, a hero pick-ban."""
    ana, rein = ids["ana"], ids["rein"]
    ids["user"] = _insert(conn, "players.user", name="disc01-player")
    common = {"match_id": ids["match"], "round": 0, "team_id": ids["team_a"], "user_id": ids["user"]}
    ids["stat_hero"] = _insert(conn, "matches.statistics", **common, hero_id=ana, name="HeroTimePlayed", value=120.0)
    ids["stat_all"] = _insert(conn, "matches.statistics", **common, name="HeroTimePlayed", value=120.0)
    ids["event"] = _insert(
        conn,
        "matches.event",
        match_id=ids["match"],
        time=1.0,
        round=1,
        team_id=ids["team_a"],
        user_id=ids["user"],
        hero_id=ana,
        related_team_id=ids["team_b"],
        related_user_id=ids["user"],
        related_hero_id=rein,
        name="OffensiveAssist",
    )
    ids["kill"] = _insert(
        conn,
        "matches.kill_feed",
        match_id=ids["match"],
        time=2.0,
        round=1,
        fight=1,
        killer_id=ids["user"],
        killer_hero_id=ana,
        killer_team_id=ids["team_a"],
        victim_id=ids["user"],
        victim_team_id=ids["team_b"],
        victim_hero_id=rein,
        damage=10.0,
        is_critical_hit=False,
        is_environmental=False,
    )
    registration = _insert(conn, "balancer.registration", tournament_id=ids["t"])
    role = _insert(conn, "balancer.registration_role", registration_id=registration, role="support")
    ids["top_hero"] = _insert(conn, "balancer.registration_role_hero", role_id=role, hero_id=ana, priority=1)
    rule = {
        "workspace_id": ids["ws"],
        "description_ru": "-",
        "description_en": "-",
        "category": "hero",
        "scope": "global",
        "grain": "user",
    }
    ids["rule_hero"] = _insert(conn, "achievements.rule", **rule, slug="d1-ana", name="Ana", hero_id=ana)
    ids["rule_plain"] = _insert(conn, "achievements.rule", **rule, slug="d1-plain", name="Plain")
    ruleset = {
        "version": 2,
        "phases": [{"id": "p", "pool_filter": {"type": "item_in", "params": {"item_ids": [rein]}}, "steps": []}],
    }
    ids["hero_config"] = _insert(
        conn, "tournament.pick_ban_config", tournament_id=ids["t"], kind="hero", ruleset_json=Json(ruleset)
    )
    ids["hero_config_item"] = _insert(
        conn, "tournament.pick_ban_config_item", pick_ban_config_id=ids["hero_config"], item_id=ana
    )
    ids["hero_session"] = _insert(
        conn,
        "encounter.pick_ban_session",
        encounter_id=ids["enc"],
        kind="hero",
        seed_source="bracket_slot",
        pool_json=Json({"mode": "pool", "rotation": "fixed", "items": [ana, rein], "slots": []}),
        ruleset_json=Json(ruleset),
        resolved_sequence_json=Json([{"index": 0, "action": "ban", "eligible": {}}]),
    )
    ids["hero_entry"] = _insert(
        conn, "encounter.pick_ban_entry", session_id=ids["hero_session"], encounter_id=ids["enc"], item_id=ana, order=0
    )
    ids["hero_sub"] = _insert(
        conn,
        "encounter.pick_ban_submission",
        session_id=ids["hero_session"],
        encounter_id=ids["enc"],
        step_index=0,
        state="locked",
        items_json=Json([{"item_id": rein, "target_player_id": None}]),
    )
    ids["hero_event"] = _insert(
        conn,
        "encounter.room_event",
        encounter_id=ids["enc"],
        kind="hero",
        action="acted",
        source="captain",
        data=Json({"step_index": 0, "round": 1, "action": "ban", "item_id": rein, "target_player_id": None}),
    )


def test_stats_rows_name_the_character_entities(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    ana, rein = _entity_of(conn, "hero", ids["ana"]), _entity_of(conn, "hero", ids["rein"])
    assert _scalar(conn, "SELECT hero_id FROM matches.statistics WHERE id = %s", (ids["stat_hero"],)) == ana
    assert _scalar(conn, "SELECT hero_id FROM matches.statistics WHERE id = %s", (ids["stat_all"],)) is None
    assert _rows(conn, "SELECT hero_id, related_hero_id FROM matches.event WHERE id = %s", (ids["event"],)) == [
        (ana, rein)
    ]
    assert _rows(
        conn, "SELECT killer_hero_id, victim_hero_id FROM matches.kill_feed WHERE id = %s", (ids["kill"],)
    ) == [(ana, rein)]


def test_top_heroes_live_in_registration_role_entity(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _rows(
        conn,
        "SELECT entity_id, entity_kind, priority FROM balancer.registration_role_entity WHERE id = %s",
        (ids["top_hero"],),
    ) == [(_entity_of(conn, "hero", ids["ana"]), "character", 1)]
    names = {
        row[0]
        for row in _rows(
            conn, "SELECT conname FROM pg_constraint WHERE conrelid = 'balancer.registration_role_entity'::regclass"
        )
    }
    assert {
        "uq_reg_role_entity_role_priority",
        "uq_reg_role_entity_role_entity",
        "fk_registration_role_entity_entity",
    } <= names
    assert _scalar(conn, "SELECT to_regclass('balancer.registration_role_hero')") is None


def test_achievement_rules_get_a_discipline_and_an_entity(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    assert _rows(
        conn,
        "SELECT id, discipline, entity_id, entity_kind FROM achievements.rule WHERE id IN (%s, %s) ORDER BY id",
        (ids["rule_hero"], ids["rule_plain"]),
    ) == [
        (ids["rule_hero"], "overwatch", _entity_of(conn, "hero", ids["ana"]), "character"),
        (ids["rule_plain"], "overwatch", None, "character"),
    ]


def test_hero_pick_ban_ids_are_rewritten(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    ana, rein = _entity_of(conn, "hero", ids["ana"]), _entity_of(conn, "hero", ids["rein"])
    assert (
        _scalar(conn, "SELECT item_id FROM tournament.pick_ban_config_item WHERE id = %s", (ids["hero_config_item"],))
        == ana
    )
    ruleset = _scalar(conn, "SELECT ruleset_json FROM tournament.pick_ban_config WHERE id = %s", (ids["hero_config"],))
    assert ruleset["phases"][0]["pool_filter"]["params"]["item_ids"] == [rein]
    assert _scalar(conn, "SELECT pool_json FROM encounter.pick_ban_session WHERE id = %s", (ids["hero_session"],))[
        "items"
    ] == [ana, rein]
    assert _scalar(conn, "SELECT item_id FROM encounter.pick_ban_entry WHERE id = %s", (ids["hero_entry"],)) == ana
    assert _scalar(conn, "SELECT items_json FROM encounter.pick_ban_submission WHERE id = %s", (ids["hero_sub"],)) == [
        {"item_id": rein, "target_player_id": None}
    ]
    assert _scalar(conn, "SELECT data FROM encounter.room_event WHERE id = %s", (ids["hero_event"],))["item_id"] == rein
