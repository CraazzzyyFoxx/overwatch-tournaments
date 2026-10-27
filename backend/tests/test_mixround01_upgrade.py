"""``mixround01`` against a POPULATED database with ``casual.*`` history.

A template database is upgraded to ``enclayer02`` (the revision before ``mixround01``), seeded with legacy mix
rounds covering every rule of the move, checked by the operator's pre-flight, upgraded to ``mixround01`` and read
back. A second copy seeded with the rows the pre-flight rejects must stop the revision with their ids.
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

from shared.testing.db import (
    BEFORE_LEGACY_DROP,
    MIGRATION_PROOF_SKIP,
    ensure_test_postgres,
    migration_proofs_enabled,
    postgres_env,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PRE_REVISION = "enclayer02"
TARGET = "mixround01"
TEMPLATE_DB = "mixround01_legacy_tpl"
MIGRATED_DB = "mixround01_migrated"
REJECTED_DB = "mixround01_rejected"
ORDERING_DB = "mixround01_ordering"
COLLIDING_DB = "mixround01_colliding"
WINS_END = "games >= best_of or max_wins * 2 > best_of"

_spec = importlib.util.spec_from_file_location(
    "mixround01_revision", BACKEND / "migrations" / "versions" / "mixround01_mix_rounds.py"
)
assert _spec is not None and _spec.loader is not None
revision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(revision)
RECONCILE_SQL = (BACKEND / "scripts" / "mixround01_reconcile.sql").read_text(encoding="utf-8")


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


def _round(conn, ids, key, *, mix, lobby, first, second, scores, recorder=None, points=None, map_id=None, busy=(), at):
    """One legacy round: ``first``/``second`` are ``(member key | None, role | None, rank, delta)`` seats."""
    match = _insert(
        conn,
        "casual.match",
        custom_game_id=ids[mix],
        lobby_index=lobby,
        map_id=map_id,
        recorded_by=recorder,
        points_per_win_applied=points,
        created_at=at,
    )
    ids[key] = match
    for side, name, seats, score in (("home", f"{key}-A", first, scores[0]), ("away", f"{key}-B", second, scores[1])):
        team = _insert(conn, "casual.team", match_id=match, side=side, name=name, score=score)
        for index, (member, role, rank, delta) in enumerate(seats):
            ids[f"{key}-{side}-{index}"] = _insert(
                conn,
                "casual.player",
                team_id=team,
                workspace_member_id=ids[member] if member else None,
                display_name_snapshot=f"{member or 'gone'}@{key}",
                role=role,
                rank=rank,
                rank_delta_applied=delta,
            )
    for member in busy:
        conn.execute(
            "INSERT INTO casual.match_busy_player (match_id, workspace_member_id) VALUES (%s, %s)", (match, ids[member])
        )


def _seed(conn) -> dict:
    ids: dict = {"ws": _insert(conn, "workspace", slug="mixr-up", name="mixr-up")}
    for index in range(6):
        user = _insert(conn, "players.user", name=f"mixr-{index}")
        ids[f"u{index}"] = user
        ids[f"m{index}"] = _insert(conn, "workspace_member", workspace_id=ids["ws"], player_id=user)
    ids["host"] = _insert(
        conn, "auth.user", email="host@mixr", username="mixr-host", is_active=True, is_superuser=False, is_verified=True
    )
    conn.execute("UPDATE players.user SET auth_user_id = %s WHERE id = %s", (ids["host"], ids["u0"]))
    ids["stranger"] = _insert(
        conn, "auth.user", email="x@mixr", username="mixr-x", is_active=True, is_superuser=False, is_verified=True
    )
    gamemode = _insert(conn, "overwatch.gamemode", name="Control", slug="control-mixr", image_path="x")
    ids["map"] = _insert(conn, "overwatch.map", name="Busan-mixr", gamemode_id=gamemode, image_path="x")
    ids["cg"] = _insert(conn, "balancer.custom_game", workspace_id=ids["ws"], name="Friday", host_user_id=ids["host"])
    ids["cg_empty"] = _insert(conn, "balancer.custom_game", workspace_id=ids["ws"], name="Never played")
    # r1: lobby A, points mode, first side wins 1:0, map + linked recorder, member 4 busy next door.
    _round(
        conn,
        ids,
        "r1",
        mix="cg",
        lobby=0,
        first=[("m0", "tank", 2400, None), ("m1", "damage", 2500, None)],
        second=[("m2", "tank", 2300, None), ("m3", None, 2200, None)],
        scores=(1, 0),
        recorder=ids["host"],
        points=25,
        map_id=ids["map"],
        busy=("m4",),
        at="2026-09-01T20:00:00Z",
    )
    # r2: lobby B, ranker deltas, a 0:0 draw, an unlinked recorder.
    _round(
        conn,
        ids,
        "r2",
        mix="cg",
        lobby=1,
        first=[("m4", "support", 2600, 12)],
        second=[("m5", "support", 2600, -12)],
        scores=(0, 0),
        recorder=ids["stranger"],
        at="2026-09-01T20:05:00Z",
    )
    # r3: lobby A again, legacy 3:2 scoreline, a departed member's seat, a busy row colliding with a seat.
    _round(
        conn,
        ids,
        "r3",
        mix="cg",
        lobby=0,
        first=[("m0", "tank", 2425, None), (None, "damage", 2100, None)],
        second=[("m2", "tank", 2275, None)],
        scores=(3, 2),
        busy=("m4", "m2"),
        at="2026-09-01T20:30:00Z",
    )
    _tournament_seat(conn, ids)
    return ids


def _tournament_seat(conn, ids) -> None:
    """A tournament seat on the V1 shape: role + sub-role are two ``player_role`` rows. It sits ahead of the mix seats
    and shares member, name and rank with a legacy seat, so the reconcile meets it before the mix seat it vouches for."""
    tournament = _insert(conn, "tournament.tournament", workspace_id=ids["ws"], name="T", slug="mixr-t", status="live")
    rule = _insert(
        conn, "encounter.scoring_rule", workspace_id=ids["ws"], preset="wins", game_formula="1", end_formula="1"
    )
    encounter = _insert(
        conn,
        "encounter.encounter",
        workspace_id=ids["ws"],
        discipline="overwatch",
        tournament_id=tournament,
        scoring_rule_id=rule,
        name="T1",
        slot_count=2,
        status="PENDING",
    )
    team = _insert(conn, "encounter.team", encounter_id=encounter, tournament_id=tournament, slot=1, name="T-A")
    ids["tournament-seat"] = _insert(
        conn,
        "encounter.team_member",
        encounter_id=encounter,
        encounter_team_id=team,
        active=True,
        workspace_member_id=ids["m0"],
        display_name_snapshot="m0@r1",
        rank=2400,
    )
    for role in ("tank", "flex"):
        conn.execute(
            "INSERT INTO encounter.team_member_role (team_member_id, dimension, role) VALUES (%s, 'player_role', %s)",
            (ids["tournament-seat"], role),
        )


@pytest.fixture(scope="module")
def legacy_template():
    ensure_test_postgres()
    if not migration_proofs_enabled():
        pytest.skip(MIGRATION_PROOF_SKIP)
    _recreate(TEMPLATE_DB)
    # As the release runs it: enclayer02 with its flag, so mixround01 is tested on the contracted V1 shape.
    done = _alembic(TEMPLATE_DB, PRE_REVISION, OWT_APPLY_ENCOUNTER_LAYER_DROP="1")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(TEMPLATE_DB) as conn:
        ids = _seed(conn)
        preflight = {question: _rows(conn, sql) for question, sql in revision.PREFLIGHT}
        dropped_seats = _scalar(conn, revision.SEATS_WITHOUT_MEMBER)
    yield {"ids": ids, "preflight": preflight, "dropped_seats": dropped_seats}
    with _connect("postgres") as admin:
        for name in (MIGRATED_DB, REJECTED_DB, ORDERING_DB, COLLIDING_DB, TEMPLATE_DB):
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="module")
def migrated(legacy_template):
    _recreate(MIGRATED_DB, TEMPLATE_DB)
    done = _alembic(MIGRATED_DB, TARGET)
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(MIGRATED_DB) as conn:
        yield {**legacy_template, "conn": conn}


def _encounter_of(conn, match_id: int) -> int:
    """The legacy round's encounter: same mix, lobby and time (the reconcile key)."""
    return _scalar(
        conn,
        "SELECT e.id FROM encounter.encounter e JOIN balancer.custom_game_round r ON r.encounter_id = e.id"
        " JOIN casual.match m ON m.custom_game_id = e.custom_game_id AND m.lobby_index = r.lobby_index"
        " AND m.created_at = e.created_at WHERE m.id = %s",
        (match_id,),
    )


def test_the_preflight_is_silent_on_clean_legacy_data(legacy_template) -> None:
    assert {q: rows for q, rows in legacy_template["preflight"].items() if rows} == {}
    assert legacy_template["dropped_seats"] == 1


def test_a_member_on_two_seats_and_a_one_sided_round_stop_the_revision(legacy_template) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        twice = _insert(conn, "casual.match", custom_game_id=ids["cg"], lobby_index=0)
        first = _insert(conn, "casual.team", match_id=twice, side="home", name="A", score=1)
        second = _insert(conn, "casual.team", match_id=twice, side="away", name="B", score=0)
        for team in (first, second):
            _insert(
                conn, "casual.player", team_id=team, workspace_member_id=ids["m1"], display_name_snapshot="m1", rank=1
            )
        lonely = _insert(conn, "casual.match", custom_game_id=ids["cg"], lobby_index=0)
        _insert(conn, "casual.team", match_id=lonely, side="home", name="A", score=1)
    done = _alembic(REJECTED_DB, TARGET)
    assert done.returncode != 0
    assert "one workspace member sits on two seats of one round" in done.stderr and str(twice) in done.stderr
    assert "round does not have exactly two teams" in done.stderr and str(lonely) in done.stderr


def test_a_rejected_preflight_rolls_back_enclayer02_too(legacy_template) -> None:
    """An upgrade run is one transaction: the pre-flight runs before any ``autocommit_block`` commits the drop."""
    _recreate(ORDERING_DB)
    done = _alembic(ORDERING_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(ORDERING_DB) as conn:
        workspace = _insert(conn, "workspace", slug="mixr-order", name="mixr-order")
        user = _insert(conn, "players.user", name="mixr-order")
        member = _insert(conn, "workspace_member", workspace_id=workspace, player_id=user)
        game = _insert(conn, "balancer.custom_game", workspace_id=workspace, name="Friday")
        match = _insert(conn, "casual.match", custom_game_id=game, lobby_index=0)
        for side in ("home", "away"):
            team = _insert(conn, "casual.team", match_id=match, side=side, name=side, score=0)
            _insert(conn, "casual.player", team_id=team, workspace_member_id=member, display_name_snapshot="m", rank=1)
    done = _alembic(ORDERING_DB, BEFORE_LEGACY_DROP, OWT_APPLY_ENCOUNTER_LAYER_DROP="1")
    assert done.returncode != 0
    assert "one workspace member sits on two seats of one round" in done.stderr
    with _connect(ORDERING_DB) as conn:
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == "enclayer01b"
        assert (
            _scalar(
                conn,
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_schema = 'encounter' AND table_name = 'encounter' AND column_name = 'home_team_id'",
            )
            == 1
        )


def test_rounds_become_completed_host_encounters_of_their_mix(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    encounter = _encounter_of(conn, ids["r1"])
    row = _rows(
        conn,
        "SELECT tournament_id, custom_game_id, workspace_id, discipline, slot_count, best_of, name, status::text,"
        " result_status::text, result_source, result_version FROM encounter.encounter WHERE id = %s",
        (encounter,),
    )[0]
    assert row == (None, ids["cg"], ids["ws"], "overwatch", 2, 1, "r1-A vs r1-B", "COMPLETED", "confirmed", "host", 1)
    assert _rows(
        conn,
        "SELECT slot, name, score, placement, tournament_id, team_id FROM encounter.team"
        " WHERE encounter_id = %s ORDER BY slot",
        (encounter,),
    ) == [(1, "r1-A", 1.0, 1, None, None), (2, "r1-B", 0.0, 2, None, None)]
    assert _rows(
        conn,
        "SELECT position, map_id, state::text, result_source::text FROM encounter.game WHERE encounter_id = %s",
        (encounter,),
    ) == [(1, ids["map"], "confirmed", "host")]


def test_a_legacy_scoreline_is_one_won_game_and_a_draw_shares_first_place(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    r3 = _encounter_of(conn, ids["r3"])
    assert _rows(
        conn,
        "SELECT t.score, t.placement, gt.score FROM encounter.team t JOIN encounter.game_team gt"
        " ON gt.encounter_team_id = t.id WHERE t.encounter_id = %s ORDER BY t.slot",
        (r3,),
    ) == [(1.0, 1, 3), (0.0, 2, 2)]
    r2 = _encounter_of(conn, ids["r2"])
    assert _rows(conn, "SELECT score, placement FROM encounter.team WHERE encounter_id = %s ORDER BY slot", (r2,)) == [
        (0.0, 1),
        (0.0, 1),
    ]


def test_seats_roles_and_rank_deltas_are_carried(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    r1, r2 = _encounter_of(conn, ids["r1"]), _encounter_of(conn, ids["r2"])
    seats = _rows(
        conn,
        "SELECT t.slot, tm.workspace_member_id, tm.rank, r.role FROM encounter.team_member tm"
        " JOIN encounter.team t ON t.id = tm.encounter_team_id LEFT JOIN encounter.team_member_role r"
        " ON r.team_member_id = tm.id WHERE tm.encounter_id = %s ORDER BY t.slot, tm.workspace_member_id",
        (r1,),
    )
    assert seats == [
        (1, ids["m0"], 2400, "tank"),
        (1, ids["m1"], 2500, "damage"),
        (2, ids["m2"], 2300, "tank"),
        (2, ids["m3"], 2200, None),
    ]
    assert _rows(
        conn,
        "SELECT workspace_member_id, busy, rank_delta_applied FROM balancer.custom_game_round_member"
        " WHERE encounter_id = %s ORDER BY workspace_member_id",
        (r2,),
    ) == [(ids["m4"], False, 12), (ids["m5"], False, -12)]


def test_a_member_less_seat_and_a_busy_row_under_a_seat_are_dropped(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    r3 = _encounter_of(conn, ids["r3"])
    assert _scalar(conn, "SELECT count(*) FROM encounter.team_member WHERE encounter_id = %s", (r3,)) == 2
    assert _rows(
        conn,
        "SELECT workspace_member_id, busy FROM balancer.custom_game_round_member WHERE encounter_id = %s"
        " ORDER BY workspace_member_id",
        (r3,),
    ) == [(ids["m0"], False), (ids["m2"], False), (ids["m4"], True)]


def test_points_recorder_and_journal_are_carried(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    r1, r2 = _encounter_of(conn, ids["r1"]), _encounter_of(conn, ids["r2"])
    assert (
        _scalar(conn, "SELECT points_per_win_applied FROM balancer.custom_game_round WHERE encounter_id = %s", (r1,))
        == 25
    )
    audit = _rows(
        conn,
        "SELECT result_version, actor_user_id, action::text, source, snapshot_scope,"
        ' jsonb_array_length("after") FROM encounter.result_audit WHERE encounter_id = %s',
        (r1,),
    )
    assert audit == [(1, ids["u0"], "confirm", "host", "encounter", 2)]
    assert _scalar(conn, "SELECT actor_user_id FROM encounter.result_audit WHERE encounter_id = %s", (r2,)) is None


def test_encounter_ids_follow_the_recording_order(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    order = [_encounter_of(conn, ids[key]) for key in ("r1", "r2", "r3")]
    assert order == sorted(order)


def test_every_mix_has_its_own_wins_rule(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    rules = _rows(
        conn,
        "SELECT g.id, r.workspace_id, r.preset, r.end_formula FROM balancer.custom_game g"
        " JOIN encounter.scoring_rule r ON r.id = g.scoring_rule_id WHERE g.workspace_id = %s ORDER BY g.id",
        (ids["ws"],),
    )
    assert rules == [(ids["cg"], ids["ws"], "wins", WINS_END), (ids["cg_empty"], ids["ws"], "wins", WINS_END)]
    assert (
        _scalar(
            conn,
            "SELECT count(DISTINCT scoring_rule_id) FROM balancer.custom_game WHERE workspace_id = %s",
            (ids["ws"],),
        )
        == 2
    )


def test_the_reconcile_report_lists_exactly_what_the_move_dropped(migrated) -> None:
    ids = migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        create, summary, skipped = _statements(RECONCILE_SQL)
        tx.execute(create)
        statuses = {row[0]: row[3] for row in _rows(tx, summary)}
        listed = {(row[0], row[1]) for row in _rows(tx, skipped)}
        tx.rollback()
    assert listed == {("seats", ids["r3-home-1"]), ("busy players", ids["r3"]), ("rounds", ids["r2"])}
    assert statuses == {"rounds": "MISMATCH", "seats": "MISMATCH", "busy players": "MISMATCH", "sides": "ok"}


def test_the_reconcile_survives_a_tournament_seat_with_two_player_roles(migrated) -> None:
    """The seed's tournament seat carries role + sub-role (two ``player_role`` rows), as V1 writes them."""
    ids = migrated["ids"]
    assert (
        _scalar(
            migrated["conn"],
            "SELECT count(*) FROM encounter.team_member_role WHERE team_member_id = %s AND dimension = 'player_role'",
            (ids["tournament-seat"],),
        )
        == 2
    )
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        create, summary, skipped = _statements(RECONCILE_SQL)
        tx.execute(create)
        assert {row[3] for row in _rows(tx, summary) if row[0] == "sides"} == {"ok"}
        assert {(row[0], row[1]) for row in _rows(tx, skipped)} == {
            ("seats", ids["r3-home-1"]),
            ("busy players", ids["r3"]),
            ("rounds", ids["r2"]),
        }
        tx.rollback()


def _listed_rounds(tx) -> set[int]:
    create, _summary, skipped = _statements(RECONCILE_SQL)
    tx.execute(create)
    return {row[1] for row in _rows(tx, skipped) if row[0] == "rounds"}


def test_the_reconcile_key_is_counted_when_two_rounds_share_it(legacy_template) -> None:
    """Two rounds recorded in one transaction share ``created_at``: a lone survivor must not vouch for both."""
    ids = dict(legacy_template["ids"])
    _recreate(COLLIDING_DB, TEMPLATE_DB)
    with _connect(COLLIDING_DB) as conn:
        for key, member in (("c1", "m0"), ("c2", "m1")):
            _round(
                conn,
                ids,
                key,
                mix="cg_empty",
                lobby=0,
                first=[(member, "tank", 2400, None)],
                second=[("m5", None, 2300, None)],
                scores=(1, 0),
                at="2026-09-02T10:00:00Z",
            )
    done = _alembic(COLLIDING_DB, TARGET)
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(COLLIDING_DB, autocommit=False) as tx:
        assert _listed_rounds(tx).isdisjoint({ids["c1"], ids["c2"]})
        tx.execute("DROP VIEW mixround01_reconcile")
        tx.execute("DELETE FROM encounter.encounter WHERE name = 'c1-A vs c1-B'")
        assert {ids["c1"], ids["c2"]} <= _listed_rounds(tx)
        tx.rollback()


def test_the_reconcile_lists_content_swapped_between_two_rounds_of_one_key(legacy_template) -> None:
    """Both encounters are kept, so the count holds; each round is checked against its own encounter only."""
    ids = dict(legacy_template["ids"])
    _recreate(COLLIDING_DB, TEMPLATE_DB)
    with _connect(COLLIDING_DB) as conn:
        for key, member in (("c1", "m0"), ("c2", "m1")):
            _round(
                conn,
                ids,
                key,
                mix="cg_empty",
                lobby=0,
                first=[(member, "tank", 2400, None)],
                second=[("m5", None, 2300, None)],
                scores=(1, 0),
                at="2026-09-02T10:00:00Z",
            )
    done = _alembic(COLLIDING_DB, TARGET)
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(COLLIDING_DB, autocommit=False) as tx:
        create, _summary, skipped = _statements(RECONCILE_SQL)
        tx.execute(create)
        before = {tuple(row) for row in _rows(tx, skipped)}
        # Exchange the first team's name and its member between the two encounters; nothing is deleted.
        tx.execute(
            "UPDATE encounter.team SET name = CASE name WHEN 'c1-A' THEN 'c2-A' ELSE 'c1-A' END"
            " WHERE name IN ('c1-A', 'c2-A')"
        )
        tx.execute(
            "UPDATE encounter.team_member SET display_name_snapshot = CASE display_name_snapshot"
            " WHEN 'm0@c1' THEN 'm1@c2' ELSE 'm0@c1' END,"
            " workspace_member_id = CASE workspace_member_id WHEN %(m0)s THEN %(m1)s ELSE %(m0)s END"
            " WHERE display_name_snapshot IN ('m0@c1', 'm1@c2')",
            {"m0": ids["m0"], "m1": ids["m1"]},
        )
        tx.execute(
            "UPDATE balancer.custom_game_round_member SET workspace_member_id = CASE workspace_member_id"
            " WHEN %(m0)s THEN %(m1)s ELSE %(m0)s END"
            " WHERE workspace_member_id IN (%(m0)s, %(m1)s) AND encounter_id IN"
            " (SELECT encounter_id FROM encounter.team WHERE name IN ('c1-A', 'c2-A'))",
            {"m0": ids["m0"], "m1": ids["m1"]},
        )
        tx.execute("DROP VIEW mixround01_reconcile")
        tx.execute(create)
        new = {tuple(row) for row in _rows(tx, skipped)} - before
        tx.rollback()
    assert {(cls, detail) for cls, _id, detail in new if cls == "sides"} == {
        ("sides", f"round {ids[key]} home") for key in ("c1", "c2")
    }
    assert {(cls, legacy_id) for cls, legacy_id, _detail in new if cls == "seats"} == {
        ("seats", ids["c1-home-0"]),
        ("seats", ids["c2-home-0"]),
    }


def test_the_reconcile_report_lists_a_journal_actor_that_is_not_the_recorder(migrated) -> None:
    ids = migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        tx.execute(
            "UPDATE encounter.result_audit SET actor_user_id = %s WHERE encounter_id = %s",
            (ids["u1"], _encounter_of(tx, ids["r1"])),
        )
        assert ids["r1"] in _listed_rounds(tx)
        tx.rollback()


def test_the_chain_ends_at_mixround01_with_every_constraint_validated(migrated) -> None:
    conn = migrated["conn"]
    assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == TARGET
    assert _rows(conn, "SELECT conrelid::regclass::text, conname FROM pg_constraint WHERE NOT convalidated") == []
