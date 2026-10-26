"""``enclayer01`` + ``enclayer01b`` against a POPULATED, legacy-shaped database.

The converters are golden-tested on their own (``test_enclayer01_convert.py``)
and the constraints on a fresh schema (``shared/tests``). Neither runs the ~30
backfill statements, the notification SQL, the ``auto_pending`` label or the two
revisions end to end on rows that exist. This does:

1. a template database is upgraded to the revision BEFORE ``enclayer01`` and
   seeded with legacy-shaped rows that cover every converter -- duels (played by
   games, admin-set), a points lobby, pick-ban rooms in every pool mode, links,
   journal rows, notifications;
2. the operator's pre-flight SQL must come back empty on it;
3. ``alembic upgrade head`` runs, and the result is read back row by row;
4. the lobby recompute step and the reconcile SQL run on the migrated rows;
5. a second copy, seeded with one row of every class the pre-flight rejects,
   must stop the revision with those ids.

Needs the ephemeral test Postgres (``docker-compose.test.yml``); skips otherwise.
Databases are created on that server under their own names and dropped after --
the shared ``anak_test`` is never touched.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import pathlib
import re
import subprocess
import sys

import psycopg
import pytest
import sqlalchemy as sa
from psycopg.types.json import Json, Jsonb

from shared.testing.db import MIGRATION_PROOF_SKIP, ensure_test_postgres, migration_proofs_enabled, postgres_env

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PRE_REVISION = "apikeysu01"
TEMPLATE_DB = "enclayer01_legacy_tpl"
MIGRATED_DB = "enclayer01_migrated"
REJECTED_DB = "enclayer01_rejected"
LIVE_DB = "enclayer01_live_named"
RECOMPUTE_DB = "enclayer01_recompute"
ENCLAYER02_DB = "enclayer02_gate"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass/pydantic imports resolve through sys.modules
    spec.loader.exec_module(module)
    return module


revision = _load("enclayer01_revision", BACKEND / "migrations" / "versions" / "enclayer01_encounter_layer.py")
recompute_script = _load("enclayer01_recompute", BACKEND / "scripts" / "enclayer01_recompute_lobbies.py")
RECONCILE_SQL = (BACKEND / "scripts" / "enclayer01_reconcile.sql").read_text(encoding="utf-8")
PREFLIGHT_SQL = (BACKEND / "scripts" / "enclayer01_preflight.sql").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #


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


def _url(dbname: str, *, driver: str = "psycopg") -> str:
    env = postgres_env()
    return f"postgresql+{driver}://{env['user']}:{env['password']}@{env['host']}:{env['port']}/{dbname}"


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


def _rows(conn: psycopg.Connection, sql: str, params=None) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def _scalar(conn: psycopg.Connection, sql: str, params=None):
    return conn.execute(sql, params).fetchone()[0]


def _insert(conn: psycopg.Connection, table: str, **columns) -> int:
    names = ", ".join(f'"{name}"' for name in columns)
    placeholders = ", ".join(f"%({name})s" for name in columns)
    return conn.execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders}) RETURNING id", columns).fetchone()[0]


def _statements(sql: str) -> list[str]:
    """A psql script as plain statements: meta-commands dropped, split on ``;``."""
    text = "\n".join(
        line for line in sql.splitlines() if not line.startswith("\\") and not line.lstrip().startswith("--")
    )
    return [part.strip() for part in re.split(r";\s*\n", text + "\n") if part.strip()]


def _run_checks(conn: psycopg.Connection, queries) -> dict[str, list[tuple]]:
    return {question: _rows(conn, sql) for question, sql in queries}


# --------------------------------------------------------------------------- #
# The legacy seed
# --------------------------------------------------------------------------- #

V2_RULESET = {
    "version": 2,
    "phases": [{"name": "bans", "steps": [{"kind": "ban", "actors": "home"}, {"kind": "ban", "actors": "away"}]}],
}
OTHER_PAYLOAD = {"encounter_id": 1, "home_team_name": "Keep", "away_team_name": "Me"}


def _seed(conn: psycopg.Connection) -> dict[str, int]:
    ids: dict[str, int] = {}
    ids["ws"] = _insert(conn, "workspace", slug="enc-up", name="enc-up")
    members = []
    for index in range(9):
        user = _insert(conn, '"players"."user"', name=f"enc-up-{index}")
        members.append(_insert(conn, "workspace_member", workspace_id=ids["ws"], player_id=user))
    ids["t"] = _insert(conn, "tournament.tournament", workspace_id=ids["ws"], name="T", slug="enc-up-t", status="live")
    ids["t2"] = _insert(
        conn, "tournament.tournament", workspace_id=ids["ws"], name="T2", slug="enc-up-t2", status="live"
    )
    teams = {}
    for letter, (first, second) in zip("ABCD", ((0, 1), (2, 3), (4, 5), (6, 7)), strict=True):
        teams[letter] = _insert(
            conn, "tournament.team", tournament_id=ids["t"], name=f"Team {letter}", balancer_name=letter
        )
        for member, role in ((members[first], "tank"), (members[second], "damage")):
            _insert(
                conn,
                "tournament.player",
                name=f"p{member}",
                rank=2000,
                role=role,
                tournament_id=ids["t"],
                workspace_member_id=member,
                team_id=teams[letter],
            )
    ids["foreign_team"] = _insert(conn, "tournament.team", tournament_id=ids["t2"], name="Foreign", balancer_name="F")
    ids.update({f"team_{letter}": team for letter, team in teams.items()})

    ids["stage_duel"] = _insert(
        conn, "tournament.stage", tournament_id=ids["t"], name="Bracket", stage_type="single_elimination", order=1
    )
    ids["stage_ffa"] = _insert(
        conn,
        "tournament.stage",
        tournament_id=ids["t"],
        name="League",
        stage_type="ffa_league",
        order=2,
        ffa_columns=Jsonb([{"key": "kills", "label": "K", "public": True, "better": "higher"}]),
        ffa_formula="place_pts + kills",
        ffa_placement_points=[10.0, 6.0, 3.0],
    )
    ids["stage_other"] = _insert(
        conn, "tournament.stage", tournament_id=ids["t2"], name="Other", stage_type="single_elimination", order=1
    )
    ids["item_duel"] = _insert(
        conn, "tournament.stage_item", stage_id=ids["stage_duel"], name="Upper", type="single_bracket", order=1
    )

    def encounter(
        name,
        home,
        away,
        *,
        round_,
        status="OPEN",
        result="none",
        scores=(0, 0),
        best_of=3,
        stage="stage_duel",
        format_="duel",
        tournament="t",
    ):
        return _insert(
            conn,
            "tournament.encounter",
            name=name,
            tournament_id=ids[tournament],
            home_team_id=home,
            away_team_id=away,
            home_score=scores[0],
            away_score=scores[1],
            round=round_,
            best_of=best_of,
            status=status,
            result_status=result,
            stage_id=ids[stage] if stage else None,
            stage_item_id=ids["item_duel"] if stage == "stage_duel" else None,
            format=format_,
            confirmed_at=None if result == "none" else "2026-10-01T12:00:00Z",
        )

    ids["e_played"] = encounter(
        "played", teams["A"], teams["B"], round_=1, status="COMPLETED", result="confirmed", scores=(2, 1)
    )
    ids["e_admin"] = encounter(
        "admin set", teams["A"], teams["C"], round_=1, status="COMPLETED", result="confirmed", scores=(2, 0)
    )
    ids["e_slots"] = encounter("slot veto", teams["B"], teams["D"], round_=2)
    ids["e_hero"] = encounter("hero veto", teams["A"], teams["D"], round_=2, best_of=5)
    ids["e_pool"] = encounter("classic veto", teams["C"], teams["D"], round_=3, best_of=1, stage=None)
    ids["e_gone"] = encounter("config deleted", teams["B"], teams["C"], round_=3)
    ids["e_tbd"] = encounter("not yet seated", None, None, round_=4)
    ids["e_lobby"] = encounter(
        "lobby",
        None,
        None,
        round_=1,
        status="COMPLETED",
        result="confirmed",
        best_of=2,
        stage="stage_ffa",
        format_="ffa",
    )
    for slot, letter in enumerate("ABC", start=1):
        _insert(conn, "tournament.encounter_participant", encounter_id=ids["e_lobby"], team_id=teams[letter], slot=slot)

    # ── games of the played series: A wins 1-0, loses 0-1, wins 1-0 ──
    ids["games"] = []
    for position, (home, away) in enumerate(((1, 0), (0, 1), (1, 0)), start=1):
        ids["games"].append(
            _insert(
                conn,
                "tournament.encounter_game",
                encounter_id=ids["e_played"],
                position=position,
                state="confirmed",
                accepted_home_score=home,
                accepted_away_score=away,
                result_source="captain_agreement",
                confirmed_at="2026-10-01T11:00:00Z",
            )
        )
    first = ids["games"][0]
    for side in ("home", "away"):
        ids[f"map_report_{side}"] = _insert(
            conn, "tournament.encounter_map_report", game_id=first, side=side, home_score=1, away_score=0
        )
    for letter in "AB":
        ids[f"captain_{letter}"] = _insert(
            conn,
            "tournament.encounter_captain_report",
            encounter_id=ids["e_played"],
            team_id=teams[letter],
            home_score=2,
            away_score=1,
            closeness=3,
            comment=f"report {letter}",
            custom_fields_json=Json({"mvp": letter}),
        )
    ids["map_code"] = _insert(
        conn, "tournament.encounter_map_code", report_id=ids["captain_A"], map_index=1, code="ABC123"
    )
    _insert(conn, "tournament.encounter_readiness", encounter_id=ids["e_played"], side="home")
    _insert(
        conn,
        "tournament.encounter_room_event",
        encounter_id=ids["e_played"],
        action="ready",
        source="captain",
        side="home",
    )
    _insert(
        conn,
        "tournament.encounter_result_audit",
        encounter_id=ids["e_played"],
        action="game_confirm",
        to_result_status="none",
        away_score_after=0,
        home_score_after=1,
        source="captain_agreement",
        game_id=first,
    )
    ids["audit_confirm"] = _insert(
        conn,
        "tournament.encounter_result_audit",
        encounter_id=ids["e_played"],
        action="confirm",
        from_result_status="none",
        to_result_status="confirmed",
        home_score_before=1,
        away_score_before=0,
        home_score_after=2,
        away_score_after=1,
        adopted_team_id=teams["A"],
        source="captain",
    )
    _insert(
        conn,
        "tournament.encounter_result_audit",
        encounter_id=ids["e_admin"],
        action="import",
        to_result_status="confirmed",
        home_score_after=2,
        away_score_after=0,
        source="import",
    )

    # ── a points lobby: A 15+8, B 15+11, C 4+3 ──
    lobby_games = []
    for position, rows in enumerate(
        (
            {"A": (1, 5), "B": (2, 9), "C": (3, 1)},
            {"A": (2, 2), "B": (1, 1), "C": (3, 0)},
        ),
        start=1,
    ):
        game = _insert(
            conn,
            "tournament.encounter_game",
            encounter_id=ids["e_lobby"],
            position=position,
            state="confirmed",
            result_source="admin",
            confirmed_at="2026-10-01T11:00:00Z",
            format="ffa",
        )
        lobby_games.append(game)
        for letter, (place, kills) in rows.items():
            _insert(
                conn,
                "tournament.encounter_game_result",
                game_id=game,
                encounter_id=ids["e_lobby"],
                team_id=teams[letter],
                placement=place,
                stats=Jsonb({"kills": kills}),
            )
    ids["lobby_games"] = lobby_games
    ids["audit_lobby"] = _insert(
        conn,
        "tournament.encounter_result_audit",
        encounter_id=ids["e_lobby"],
        action="confirm",
        to_result_status="confirmed",
        source="admin",
        ffa_results_json=Jsonb(
            {
                "before": [],
                "after": [
                    {"team_id": teams[letter], "points": points, "games": 2}
                    for letter, points in zip("ABC", (23, 26, 7), strict=True)
                ],
            }
        ),
    )

    # ── pick-ban rooms: slots, hero pool, classic pool, deleted config ──
    slots_cfg = _insert(
        conn,
        "tournament.pick_ban_config",
        tournament_id=ids["t"],
        kind="map",
        stage_id=ids["stage_duel"],
        round=2,
        mode="slots",
        first_ban_rotation="alternate",
        ruleset_json=Json(V2_RULESET),
    )
    for position, items in ((1, (11, 12, 13)), (2, (21, 22)), (3, (31,)), (4, (41,))):
        slot = _insert(
            conn,
            "tournament.pick_ban_config_slot",
            pick_ban_config_id=slots_cfg,
            position=position,
            reserve_item_id=items[0],
        )
        for order, item in enumerate(items):
            _insert(
                conn,
                "tournament.pick_ban_config_slot_item",
                pick_ban_config_slot_id=slot,
                item_id=item,
                sort_order=order,
            )
    hero_cfg = _insert(
        conn,
        "tournament.pick_ban_config",
        tournament_id=ids["t"],
        kind="hero",
        mode="pool",
        first_ban_rotation="result_loser_choice",
        ruleset_json=Json(V2_RULESET),
    )
    for order, item in enumerate((103, 101, 102)):
        _insert(conn, "tournament.pick_ban_config_item", pick_ban_config_id=hero_cfg, item_id=item, sort_order=order)
    pool_cfg = _insert(
        conn,
        "tournament.pick_ban_config",
        tournament_id=ids["t"],
        kind="map",
        mode="pool",
        first_ban_rotation="fixed",
        ruleset_json=Json(V2_RULESET),
    )
    for order, item in enumerate((7, 3, 9)):
        _insert(conn, "tournament.pick_ban_config_item", pick_ban_config_id=pool_cfg, item_id=item, sort_order=order)

    def session(encounter_key, kind, config, **extra):
        return _insert(
            conn,
            "tournament.pick_ban_session",
            encounter_id=ids[encounter_key],
            kind=kind,
            config_id=config,
            seed_source="standings",
            resolved_sequence_json=Json([]),
            ruleset_json=Json(V2_RULESET),
            **extra,
        )

    ids["s_slots"] = session(
        "e_slots",
        "map",
        slots_cfg,
        first_side="home",
        home_seed=1,
        away_seed=2,
        pending_loser_side="away",
        undo_requested_by="home",
    )
    ids["s_hero"] = session("e_hero", "hero", hero_cfg)
    ids["s_pool"] = session("e_pool", "map", pool_cfg)
    ids["s_gone"] = session("e_gone", "hero", None)
    for order, (picked, protected) in enumerate(
        (("home", None), ("away", None), ("decider", "admin"), (None, "home")), start=1
    ):
        _insert(
            conn,
            "tournament.pick_ban_entry",
            session_id=ids["s_slots"],
            item_id=10 + order,
            order=order,
            picked_by=picked,
            protected_by=protected,
        )
    for step, side in enumerate(("home", "away", "system")):
        _insert(
            conn,
            "tournament.pick_ban_submission",
            session_id=ids["s_slots"],
            step_index=step,
            side=side,
            state="locked",
        )

    # ── bracket links ──
    _insert(
        conn,
        "tournament.encounter_link",
        source_encounter_id=ids["e_played"],
        target_encounter_id=ids["e_slots"],
        role="winner",
        target_slot="home",
    )
    _insert(
        conn,
        "tournament.encounter_link",
        source_encounter_id=ids["e_played"],
        target_encounter_id=ids["e_hero"],
        role="loser",
        target_slot="away",
    )

    # ── stored notifications ──
    for kind, payload in (
        (
            "encounter.scheduled",
            {"encounter_id": ids["e_played"], "home_team_name": "Team A", "away_team_name": "Team B"},
        ),
        (
            "encounter.dispute_review",
            {"encounter_id": ids["e_played"], "home_team_name": "Team A", "away_team_name": "Team B"},
        ),
        ("some.other", OTHER_PAYLOAD),
    ):
        ids[f"notification_{kind}"] = _insert(
            conn, "notification", audience="all", kind=kind, payload_json=Jsonb(payload)
        )

    # ── a played match, for the team-delete proof ──
    mode = _insert(conn, "overwatch.gamemode", slug="enc-up", name="enc-up", image_path="x")
    map_id = _insert(conn, "overwatch.map", gamemode_id=mode, name="enc-up", image_path="x")
    ids["match"] = _insert(
        conn,
        "matches.match",
        home_team_id=teams["A"],
        away_team_id=teams["B"],
        home_score=1,
        away_score=0,
        encounter_id=ids["e_played"],
        map_id=map_id,
    )
    return ids


MOVED_TABLES = (
    "tournament.encounter",
    "tournament.encounter_game",
    "tournament.encounter_result_audit",
    "tournament.encounter_room_event",
    "tournament.pick_ban_session",
    "tournament.pick_ban_entry",
    "tournament.pick_ban_submission",
)


def _id_ranges_of(conn: psycopg.Connection, table: str) -> tuple:
    return _rows(conn, f"SELECT min(id), max(id), count(id) FROM {table}")[0]


def _id_ranges(conn: psycopg.Connection) -> dict[str, tuple]:
    return {table: _id_ranges_of(conn, table) for table in MOVED_TABLES}


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def legacy_template():
    ensure_test_postgres()
    if not migration_proofs_enabled():
        pytest.skip(MIGRATION_PROOF_SKIP)
    _recreate(TEMPLATE_DB)
    done = _alembic(TEMPLATE_DB, PRE_REVISION)
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(TEMPLATE_DB) as conn:
        ids = _seed(conn)
        before = _id_ranges(conn)
        preflight = _run_checks(conn, _preflight_queries())
    yield {"ids": ids, "before": before, "preflight": preflight}
    with _connect("postgres") as admin:
        for name in (MIGRATED_DB, REJECTED_DB, LIVE_DB, RECOMPUTE_DB, ENCLAYER02_DB, TEMPLATE_DB):
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _preflight_queries():
    return [*revision.PREFLIGHT, *revision.GUARDS]


@pytest.fixture(scope="module")
def migrated(legacy_template):
    _recreate(MIGRATED_DB, TEMPLATE_DB)
    done = _alembic(MIGRATED_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(MIGRATED_DB) as conn:
        yield {**legacy_template, "conn": conn}


# --------------------------------------------------------------------------- #
# Pre-flight
# --------------------------------------------------------------------------- #


def test_the_preflight_is_silent_on_clean_legacy_data(legacy_template) -> None:
    assert {q: rows for q, rows in legacy_template["preflight"].items() if rows} == {}


def test_the_operators_preflight_file_is_silent_too(legacy_template) -> None:
    with _connect(TEMPLATE_DB) as conn:
        results = [_rows(conn, statement) for statement in _statements(PREFLIGHT_SQL)]
    assert [rows for rows in results if rows] == []


def test_every_class_the_converter_rejects_is_reported_with_its_ids_and_stops_the_revision(legacy_template) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        conn.execute(
            "INSERT INTO tournament.encounter (name, tournament_id, home_score, away_score, round, status, best_of)"
            " VALUES ('x', %(t)s, 0, 0, 1, 'OPEN', 0)",
            {"t": ids["t"]},
        )
        bad_best_of = _scalar(conn, "SELECT id FROM tournament.encounter WHERE name = 'x'")

        def duel(name, home, away, **extra):
            columns = {
                "name": name,
                "tournament_id": ids["t"],
                "home_team_id": home,
                "away_team_id": away,
                "home_score": 0,
                "away_score": 0,
                "round": 9,
                "status": "OPEN",
                **extra,
            }
            return _insert(conn, "tournament.encounter", **columns)

        same_team = duel(
            "invalid lobby sides",
            ids["team_C"],
            ids["team_C"],
            format="ffa",
            stage_id=ids["stage_ffa"],
        )
        foreign_team = duel("foreign team", ids["foreign_team"], None)
        foreign_stage = duel("foreign stage", None, None, stage_id=ids["stage_other"])
        ffa_in_bracket = duel("ffa in a bracket", None, None, stage_id=ids["stage_duel"], format="ffa")
        unseated = duel("unseated pick", ids["team_C"], None)
        session = _insert(
            conn,
            "tournament.pick_ban_session",
            encounter_id=unseated,
            kind="map",
            seed_source="standings",
            resolved_sequence_json=Json([]),
            ruleset_json=Json(V2_RULESET),
        )
        entry = _insert(conn, "tournament.pick_ban_entry", session_id=session, item_id=1, order=1, picked_by="away")
        link_a = duel("link a", None, None)
        link_b = duel("link b", None, None)
        link_foreign = _insert(
            conn,
            "tournament.encounter",
            name="t2",
            tournament_id=ids["t2"],
            home_score=0,
            away_score=0,
            round=1,
            status="OPEN",
        )
        dup_one = _insert(
            conn,
            "tournament.encounter_link",
            source_encounter_id=link_a,
            target_encounter_id=ids["e_tbd"],
            role="winner",
            target_slot="home",
        )
        dup_two = _insert(
            conn,
            "tournament.encounter_link",
            source_encounter_id=link_b,
            target_encounter_id=ids["e_tbd"],
            role="winner",
            target_slot="home",
        )
        cross = _insert(
            conn,
            "tournament.encounter_link",
            source_encounter_id=link_a,
            target_encounter_id=link_foreign,
            role="loser",
            target_slot="away",
        )

        found = _run_checks(conn, revision.GUARDS)

    def ids_of(fragment: str, column: int) -> set[int]:
        (rows,) = [rows for question, rows in found.items() if fragment in question]
        return {row[column] for row in rows}

    assert ids_of("link repeats a target slot", 0) == {dup_one, dup_two, cross}
    assert ids_of("best_of is below 1", 0) == {bad_best_of}
    assert ids_of("non-duel seats the same team", 0) == {same_team}
    assert ids_of("another tournament than its encounter", 0) == {foreign_team}
    assert ids_of("stage of another tournament", 0) == {foreign_stage}
    assert ids_of("pick-ban entry", 0) == {entry}
    assert ids_of("not in an ffa_league stage", 0) == {ffa_in_bracket}

    done = _alembic(REJECTED_DB, "enclayer01b")
    assert done.returncode != 0
    assert "pre-flight failed" in done.stderr
    for fragment, expected in (
        ("link repeats a target slot", dup_one),
        ("best_of is below 1", bad_best_of),
        ("non-duel seats the same team", same_team),
        ("another tournament than its encounter", foreign_team),
        ("stage of another tournament", foreign_stage),
        ("pick-ban entry", entry),
        ("not in an ffa_league stage", ffa_in_bracket),
    ):
        line = next(line for line in done.stderr.splitlines() if fragment in line)
        assert str(expected) in line, f"{fragment}: id {expected} missing from {line}"


def _spare_member_on(conn: psycopg.Connection, ids: dict[str, int], **rows: bool) -> int:
    """Seed the one member no team of the seed uses onto the given teams (letter=is_substitution)."""
    member = _scalar(conn, "SELECT max(id) FROM workspace_member WHERE workspace_id = %s", (ids["ws"],))
    for letter, is_substitution in rows.items():
        _insert(
            conn,
            "tournament.player",
            name="spare",
            rank=2000,
            role="damage",
            tournament_id=ids["t"],
            workspace_member_id=member,
            team_id=ids[f"team_{letter}"],
            is_substitution=is_substitution,
        )
    return member


def test_a_regular_seat_beats_a_substitute_row_of_the_same_encounter(legacy_template) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        # Regular of team A, registered as a substitute on its opponent D: they sit in A's encounters as a regular.
        member = _spare_member_on(conn, ids, A=False, D=True)
        assert not any(_run_checks(conn, _preflight_queries()).values())
    done = _alembic(REJECTED_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]

    def snapshots(encounter: str) -> list[tuple]:
        with _connect(REJECTED_DB) as conn:
            return _rows(
                conn,
                "SELECT t.team_id, tm.is_substitute,"
                " (SELECT count(*) FROM encounter.team_member_role r WHERE r.team_member_id = tm.id)"
                " FROM encounter.team_member tm JOIN encounter.team t ON t.id = tm.encounter_team_id"
                " WHERE t.encounter_id = %s AND tm.workspace_member_id = %s",
                (ids[encounter], member),
            )

    # A vs D: one snapshot, on the regular side, role included.
    assert snapshots("e_hero") == [(ids["team_A"], False, 1)]
    # Without the regular seat in the encounter the substitute row stays.
    assert snapshots("e_slots") == [(ids["team_D"], True, 1)]
    assert snapshots("e_pool") == [(ids["team_D"], True, 1)]


@pytest.mark.parametrize("flags", [{"A": False, "D": False}, {"A": True, "D": True}], ids=["two-regulars", "two-subs"])
def test_ambiguous_roster_seats_are_audited_without_asserting_participation(legacy_template, flags) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        member = _spare_member_on(conn, ids, **flags)
        conn.execute(
            "UPDATE tournament.encounter SET status='COMPLETED',result_status='confirmed',home_score=2,away_score=0"
            " WHERE id=%s",
            (ids["e_hero"],),
        )
        registrations = _scalar(
            conn,
            "SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM tournament.player p WHERE workspace_member_id=%s",
            (member,),
        )
        assert not any(_run_checks(conn, _preflight_queries()).values())
    done = _alembic(REJECTED_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        assert (
            _scalar(
                conn,
                "SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM tournament.player p WHERE workspace_member_id=%s",
                (member,),
            )
            == registrations
        )
        assert (
            _rows(
                conn,
                "SELECT encounter_team_id FROM encounter.team_member WHERE encounter_id=%s AND workspace_member_id=%s",
                (ids["e_hero"], member),
            )
            == []
        )
        assert _rows(
            conn,
            "SELECT slot,score,placement FROM encounter.team WHERE encounter_id=%s ORDER BY slot",
            (ids["e_hero"],),
        ) == [(1, 2.0, 1), (2, 0.0, 2)]
        assert _rows(
            conn,
            "SELECT home_team_id,away_team_id,home_score,away_score,result_status::text,result_source"
            " FROM encounter.encounter WHERE id=%s",
            (ids["e_hero"],),
        ) == [(ids["team_A"], ids["team_D"], 2, 0, "confirmed", "import")]
        seats = _rows(
            conn,
            "SELECT id,slot FROM encounter.team WHERE encounter_id=%s ORDER BY slot",
            (ids["e_hero"],),
        )
        assert _rows(
            conn,
            "SELECT source,workspace_id,before_json,after_json FROM public.audit_log"
            " WHERE action='encounter.history_unresolved' AND entity_type='encounter'"
            " AND entity_id=%s AND reason='ambiguous_roster_seat'",
            (ids["e_hero"],),
        ) == [
            (
                "system",
                ids["ws"],
                {
                    "workspace_member_id": member,
                    "registrations": [
                        {"encounter_team_id": seat, "slot": slot, "registration": registration}
                        for (seat, slot), registration in zip(seats, registrations, strict=True)
                    ],
                },
                {"encounter_team_ids": []},
            )
        ]
        # A single seat is still unambiguous, even for an all-substitute registration.
        assert _rows(
            conn,
            "SELECT t.team_id,tm.rank,tm.is_substitute FROM encounter.team_member tm"
            " JOIN encounter.team t ON t.id=tm.encounter_team_id"
            " WHERE tm.encounter_id=%s AND tm.workspace_member_id=%s",
            (ids["e_slots"], member),
        ) == [(ids["team_D"], 2000, flags["D"])]
        assert (
            _scalar(
                conn,
                "SELECT indisunique FROM pg_index WHERE indexrelid='encounter.uq_team_member_active_member'::regclass",
            )
            is True
        )


@pytest.mark.parametrize(
    "role,rank,is_substitution",
    [("support", 2000, False), ("tank", 3100, False), ("support", 3100, True)],
    ids=["role-only", "rank-only", "all-substitutes"],
)
def test_disputed_role_or_rank_keeps_registrations_but_no_asserted_role_or_rank(
    legacy_template,
    role,
    rank,
    is_substitution,
) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        original = _scalar(
            conn,
            "SELECT to_jsonb(p) FROM tournament.player p WHERE team_id=%s AND role='tank'",
            (ids["team_A"],),
        )
        conn.execute("UPDATE tournament.player SET is_substitution=%s WHERE id=%s", (is_substitution, original["id"]))
        _insert(
            conn,
            "tournament.player",
            name="disputed substitute",
            rank=rank,
            role=role,
            sub_role="other",
            tournament_id=ids["t"],
            workspace_member_id=original["workspace_member_id"],
            team_id=ids["team_A"],
            is_substitution=True,
        )
        registrations = _scalar(
            conn,
            "SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM tournament.player p"
            " WHERE team_id=%s AND workspace_member_id=%s",
            (ids["team_A"], original["workspace_member_id"]),
        )
    done = _alembic(REJECTED_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        assert (
            _scalar(
                conn,
                "SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM tournament.player p"
                " WHERE team_id=%s AND workspace_member_id=%s",
                (ids["team_A"], original["workspace_member_id"]),
            )
            == registrations
        )
        snapshots = _rows(
            conn,
            "SELECT tm.rank,tm.is_substitute,tm.display_name_snapshot,"
            " (SELECT count(*) FROM encounter.team_member_role r WHERE r.team_member_id=tm.id)"
            " FROM encounter.team_member tm JOIN encounter.team t ON t.id=tm.encounter_team_id"
            " WHERE t.team_id=%s AND tm.workspace_member_id=%s",
            (ids["team_A"], original["workspace_member_id"]),
        )
        assert snapshots and all(row == (None, is_substitution, original["name"], 0) for row in snapshots)
        assert _rows(
            conn,
            "SELECT source,workspace_id,before_json,after_json FROM public.audit_log"
            " WHERE action='encounter.history_unresolved' AND entity_type='team'"
            " AND entity_id=%s AND reason='conflicting_roster_role_rank'",
            (ids["team_A"],),
        ) == [
            (
                "system",
                ids["ws"],
                {
                    "workspace_member_id": original["workspace_member_id"],
                    "registrations": registrations,
                },
                {"rank": None, "roles": []},
            )
        ]
        # Existing official results and the other member's resolved roster remain exact.
        assert _rows(
            conn,
            "SELECT slot,score,placement FROM encounter.team WHERE encounter_id=%s ORDER BY slot",
            (ids["e_played"],),
        ) == [(1, 2.0, 1), (2, 1.0, 2)]
        assert _rows(
            conn,
            "SELECT tm.rank,r.role FROM encounter.team_member tm"
            " JOIN encounter.team t ON t.id=tm.encounter_team_id"
            " JOIN encounter.team_member_role r ON r.team_member_id=tm.id"
            " WHERE t.encounter_id=%s AND t.team_id=%s",
            (ids["e_played"], ids["team_A"]),
        ) == [(2000, "damage")]


def test_agreeing_registration_duplicates_keep_the_existing_deterministic_projection(legacy_template) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        original = _scalar(
            conn,
            "SELECT to_jsonb(p) FROM tournament.player p WHERE team_id=%s AND role='tank'",
            (ids["team_A"],),
        )
        conn.execute("UPDATE tournament.player SET is_substitution=true WHERE id=%s", (original["id"],))
        _insert(
            conn,
            "tournament.player",
            name="later registration",
            rank=2000,
            role="tank",
            sub_role="later",
            tournament_id=ids["t"],
            workspace_member_id=original["workspace_member_id"],
            team_id=ids["team_A"],
            is_substitution=False,
        )
        registrations = _scalar(
            conn,
            "SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM tournament.player p"
            " WHERE team_id=%s AND workspace_member_id=%s",
            (ids["team_A"], original["workspace_member_id"]),
        )
    done = _alembic(REJECTED_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        assert (
            _scalar(
                conn,
                "SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM tournament.player p"
                " WHERE team_id=%s AND workspace_member_id=%s",
                (ids["team_A"], original["workspace_member_id"]),
            )
            == registrations
        )
        assert _rows(
            conn,
            "SELECT tm.display_name_snapshot,tm.rank,tm.is_substitute,r.role"
            " FROM encounter.team_member tm JOIN encounter.team t ON t.id=tm.encounter_team_id"
            " JOIN encounter.team_member_role r ON r.team_member_id=tm.id"
            " WHERE t.encounter_id=%s AND t.team_id=%s AND tm.workspace_member_id=%s",
            (ids["e_played"], ids["team_A"], original["workspace_member_id"]),
        ) == [(original["name"], 2000, True, "tank")]
        assert _rows(
            conn,
            "SELECT source,workspace_id,before_json,after_json FROM public.audit_log"
            " WHERE action='encounter.history_unresolved' AND entity_type='team' AND entity_id=%s"
            " AND reason='conflicting_roster_metadata'",
            (ids["team_A"],),
        ) == [
            (
                "system",
                ids["ws"],
                {
                    "workspace_member_id": original["workspace_member_id"],
                    "registrations": registrations,
                },
                {"snapshot_player_id": original["id"]},
            )
        ]


def test_self_duel_keeps_both_results_but_only_one_known_source_team(legacy_template) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        encounter = _insert(
            conn,
            "tournament.encounter",
            name="historical self-duel",
            tournament_id=ids["t"],
            home_team_id=ids["team_C"],
            away_team_id=ids["team_C"],
            home_score=1,
            away_score=3,
            round=6,
            best_of=5,
            status="COMPLETED",
            result_status="confirmed",
        )
        source = _scalar(conn, "SELECT to_jsonb(e) FROM tournament.encounter e WHERE id=%s", (encounter,))
        teams_before = _scalar(conn, "SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM tournament.team t")
    done = _alembic(REJECTED_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        assert _rows(
            conn,
            "SELECT slot,team_id,name,score,placement FROM encounter.team WHERE encounter_id=%s ORDER BY slot",
            (encounter,),
        ) == [(1, ids["team_C"], "Team C", 1.0, 2), (2, None, "Unknown opponent", 3.0, 1)]
        native = _scalar(conn, "SELECT to_jsonb(e) FROM encounter.encounter e WHERE id=%s", (encounter,))
        renamed = {"current_map_index": "current_game_position"}
        assert {key: native[renamed.get(key, key)] for key in source} == source
        assert native["result_source"] == "import"
        assert _scalar(conn, "SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM tournament.team t") == teams_before
        assert _scalar(conn, "SELECT count(*) FROM encounter.game WHERE encounter_id=%s", (encounter,)) == 0
        assert (
            _scalar(
                conn,
                "SELECT count(*) FROM encounter.team_member tm JOIN encounter.team t ON t.id=tm.encounter_team_id"
                " WHERE t.encounter_id=%s AND t.slot=2",
                (encounter,),
            )
            == 0
        )
        assert _rows(
            conn,
            "SELECT source,workspace_id,before_json,after_json FROM public.audit_log"
            " WHERE action='encounter.history_unresolved' AND entity_type='encounter'"
            " AND entity_id=%s AND reason='same_team_both_sides'",
            (encounter,),
        ) == [("system", ids["ws"], source, {"home_team_id": ids["team_C"], "away_team_id": None})]


def test_ambiguous_replay_codes_stay_in_their_reports_without_official_game_links(legacy_template) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        for position in (1, 2, 5):
            _insert(
                conn, "tournament.encounter_game", encounter_id=ids["e_played"], position=position, state="cancelled"
            )
        for captain, position, code in (
            ("B", 1, "BBB111"),
            ("A", 2, "AAA222"),
            ("B", 2, "BBB222"),
            ("A", 3, "AAA333"),
            ("A", 4, "AAA444"),
            ("B", 4, "BBB444"),
            ("A", 5, "AAA555"),
            ("B", 5, "BBB555"),
        ):
            _insert(
                conn,
                "tournament.encounter_map_code",
                report_id=ids[f"captain_{captain}"],
                map_index=position,
                code=code,
            )
        codes = _scalar(conn, "SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM tournament.encounter_map_code c")
        reports = _scalar(conn, "SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM tournament.encounter_captain_report r")
        games = _rows(
            conn,
            "SELECT id,state::text,accepted_home_score,accepted_away_score"
            " FROM tournament.encounter_game WHERE encounter_id=%s ORDER BY id",
            (ids["e_played"],),
        )
    done = _alembic(REJECTED_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        assert _scalar(conn, "SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM tournament.encounter_map_code c") == codes
        assert (
            _scalar(conn, "SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM tournament.encounter_captain_report r")
            == reports
        )
        assert (
            _rows(
                conn,
                "SELECT id,state::text,accepted_home_score,accepted_away_score"
                " FROM encounter.game WHERE encounter_id=%s ORDER BY id",
                (ids["e_played"],),
            )
            == games
        )
        for letter in "AB":
            assert _scalar(
                conn,
                "SELECT r.custom_fields_json FROM encounter.team_report r"
                " JOIN encounter.team t ON t.id=r.encounter_team_id WHERE r.encounter_id=%s AND t.team_id=%s",
                (ids["e_played"], ids[f"team_{letter}"]),
            ) == {
                "mvp": letter,
                "historical_replay_codes": [
                    {
                        **{key: code[key] for key in ("id", "report_id", "map_index", "code")},
                        "reason": {
                            1: "cancelled_and_live_position",
                            2: "cancelled_and_live_position",
                            4: "no_live_game_at_position",
                            5: "no_live_game_at_position",
                        }[code["map_index"]],
                    }
                    for code in codes
                    if code["report_id"] == ids[f"captain_{letter}"] and code["map_index"] != 3
                ],
            }
        assert _rows(
            conn,
            "SELECT g.position,t.slot,gt.replay_code FROM encounter.game_team gt"
            " JOIN encounter.game g ON g.id=gt.game_id JOIN encounter.team t ON t.id=gt.encounter_team_id"
            " WHERE g.encounter_id=%s AND gt.replay_code IS NOT NULL",
            (ids["e_played"],),
        ) == [(3, 1, "AAA333")]
        assert _rows(
            conn,
            "SELECT g.position,t.slot,gt.score,gt.placement FROM encounter.game_team gt"
            " JOIN encounter.game g ON g.id=gt.game_id JOIN encounter.team t ON t.id=gt.encounter_team_id"
            " WHERE g.encounter_id=%s AND g.state='confirmed' ORDER BY g.position,t.slot",
            (ids["e_played"],),
        ) == [(1, 1, 1, 1), (1, 2, 0, 2), (2, 1, 0, 2), (2, 2, 1, 1), (3, 1, 1, 1), (3, 2, 0, 2)]
        assert (
            _scalar(
                conn, "SELECT count(*) FROM encounter.game WHERE encounter_id=%s AND position=4", (ids["e_played"],)
            )
            == 0
        )


@pytest.mark.parametrize("custom_fields", [{"historical_replay_codes": ["original"]}, ["not", "an", "object"]])
@pytest.mark.parametrize("position", [1, 4, 5], ids=["cancelled-and-live", "no-game", "cancelled-only"])
def test_unbound_replay_audit_refuses_to_overwrite_existing_custom_fields(
    legacy_template,
    custom_fields,
    position,
) -> None:
    ids = legacy_template["ids"]
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        if position != 4:
            _insert(
                conn, "tournament.encounter_game", encounter_id=ids["e_played"], position=position, state="cancelled"
            )
        conn.execute("UPDATE tournament.encounter_map_code SET map_index=%s WHERE id=%s", (position, ids["map_code"]))
        conn.execute(
            "UPDATE tournament.encounter_captain_report SET custom_fields_json=%s WHERE id=%s",
            (Json(custom_fields), ids["captain_A"]),
        )
    done = _alembic(REJECTED_DB, "enclayer01b")
    assert done.returncode != 0
    assert "pre-flight failed" in done.stderr
    with _connect(REJECTED_DB) as conn:
        assert (
            _scalar(
                conn,
                "SELECT custom_fields_json FROM tournament.encounter_captain_report WHERE id=%s",
                (ids["captain_A"],),
            )
            == custom_fields
        )
        assert _scalar(conn, "SELECT to_regclass('encounter.team_report')") is None


def _earlier_history_copy(ids):
    """Represent exactly the earlier enclayer01 native output, without changing any source row after transfer."""
    _recreate(REJECTED_DB, TEMPLATE_DB)
    with _connect(REJECTED_DB) as conn:
        original = _scalar(
            conn,
            "SELECT to_jsonb(p) FROM tournament.player p WHERE team_id=%s AND role='tank'",
            (ids["team_A"],),
        )
        _insert(
            conn,
            "tournament.player",
            name="alternate historical handle",
            rank=original["rank"],
            role=original["role"],
            tournament_id=ids["t"],
            workspace_member_id=original["workspace_member_id"],
            team_id=ids["team_A"],
            is_substitution=True,
        )
        for position in (1, 5):
            _insert(
                conn, "tournament.encounter_game", encounter_id=ids["e_played"], position=position, state="cancelled"
            )
        for position, code in ((4, "ABSENT"), (5, "CANCEL")):
            _insert(conn, "tournament.encounter_map_code", report_id=ids["captain_A"], map_index=position, code=code)
        sources = {
            table: _scalar(conn, f"SELECT jsonb_agg(to_jsonb(s) ORDER BY id) FROM tournament.{table} s")
            for table in ("player", "encounter_captain_report", "encounter_map_code")
        }
    done = _alembic(REJECTED_DB, "enclayer01")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        native_report = _scalar(
            conn,
            "SELECT r.id FROM encounter.team_report r JOIN encounter.team t ON t.id=r.encounter_team_id"
            " WHERE r.encounter_id=%s AND t.team_id=%s",
            (ids["e_played"], ids["team_A"]),
        )
        fields = {
            "mvp": "A",
            "historical_replay_codes": [
                {
                    **{key: code[key] for key in ("id", "report_id", "map_index", "code")},
                    "reason": {
                        1: "cancelled_and_live_position",
                        4: "no_live_game_at_position",
                        5: "no_live_game_at_position",
                    }[code["map_index"]],
                }
                for code in sources["encounter_map_code"]
                if code["report_id"] == ids["captain_A"]
            ],
        }
        metadata_audit = {
            "before_json": {
                "workspace_member_id": original["workspace_member_id"],
                "registrations": [
                    player
                    for player in sources["player"]
                    if player["team_id"] == ids["team_A"]
                    and player["workspace_member_id"] == original["workspace_member_id"]
                ],
            },
            "after_json": {"snapshot_player_id": original["id"]},
        }
        # The original primary already retained cancelled/live codes, but not no-live codes or metadata-only audits.
        previous = {
            **fields,
            "historical_replay_codes": [
                code for code in fields["historical_replay_codes"] if code["reason"] == "cancelled_and_live_position"
            ],
        }
        conn.execute(
            "UPDATE encounter.team_report SET custom_fields_json=%s WHERE id=%s", (Json(previous), native_report)
        )
        conn.execute(
            "DELETE FROM public.audit_log WHERE reason='conflicting_roster_metadata' AND entity_id=%s", (ids["team_A"],)
        )
    return original, sources, native_report, fields, metadata_audit


def test_forward_history_completion_is_exact_target_bound_and_idempotent(legacy_template) -> None:
    ids = legacy_template["ids"]
    original, sources, native_report, expected_fields, metadata_audit = _earlier_history_copy(ids)
    done = _alembic(REJECTED_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(REJECTED_DB) as conn:
        for table, expected in sources.items():
            assert _scalar(conn, f"SELECT jsonb_agg(to_jsonb(s) ORDER BY id) FROM tournament.{table} s") == expected
        assert (
            _scalar(conn, "SELECT custom_fields_json FROM encounter.team_report WHERE id=%s", (native_report,))
            == expected_fields
        )
        assert _rows(
            conn,
            "SELECT before_json,after_json FROM public.audit_log WHERE reason='conflicting_roster_metadata'"
            " AND entity_id=%s",
            (ids["team_A"],),
        ) == [(metadata_audit["before_json"], metadata_audit["after_json"])]
        assert _rows(
            conn,
            "SELECT tm.display_name_snapshot,tm.rank,tm.is_substitute,r.role"
            " FROM encounter.team_member tm JOIN encounter.team t ON t.id=tm.encounter_team_id"
            " JOIN encounter.team_member_role r ON r.team_member_id=tm.id"
            " WHERE t.encounter_id=%s AND t.team_id=%s AND tm.workspace_member_id=%s",
            (ids["e_played"], ids["team_A"], original["workspace_member_id"]),
        ) == [(original["name"], original["rank"], False, "tank")]
        assert _rows(
            conn,
            "SELECT slot,score,placement FROM encounter.team WHERE encounter_id=%s ORDER BY slot",
            (ids["e_played"],),
        ) == [(1, 2.0, 1), (2, 1.0, 2)]
        before = {
            table: _scalar(conn, f"SELECT jsonb_agg(to_jsonb(n) ORDER BY id) FROM {table} n")
            for table in ("encounter.team_report", "public.audit_log")
        }
    engine = sa.create_engine(_url(REJECTED_DB))
    try:
        with engine.begin() as conn:
            revision.complete_historical_evidence(conn)
            revision.complete_historical_evidence(conn)
    finally:
        engine.dispose()
    with _connect(REJECTED_DB) as conn:
        for table, expected in before.items():
            assert _scalar(conn, f"SELECT jsonb_agg(to_jsonb(n) ORDER BY id) FROM {table} n") == expected


@pytest.mark.parametrize("changed", ["reserved-array", "report-comment", "roster-snapshot", "existing-audit"])
def test_forward_history_completion_refuses_unexpected_native_metadata_atomically(legacy_template, changed) -> None:
    ids = legacy_template["ids"]
    original, sources, native_report, _, metadata_audit = _earlier_history_copy(ids)
    with _connect(REJECTED_DB) as conn:
        if changed == "reserved-array":
            conn.execute(
                "UPDATE encounter.team_report SET custom_fields_json=%s WHERE id=%s",
                (Json({"mvp": "A", "historical_replay_codes": [{"code": "not source"}]}), native_report),
            )
        elif changed == "report-comment":
            conn.execute("UPDATE encounter.team_report SET comment='native edit' WHERE id=%s", (native_report,))
        elif changed == "roster-snapshot":
            conn.execute(
                "UPDATE encounter.team_member SET display_name_snapshot='native edit'"
                " WHERE workspace_member_id=%s AND encounter_id=%s",
                (original["workspace_member_id"], ids["e_played"]),
            )
        else:
            _insert(
                conn,
                "public.audit_log",
                workspace_id=ids["ws"],
                actor_label="enclayer01",
                source="system",
                action="encounter.history_unresolved",
                entity_type="team",
                entity_id=ids["team_A"],
                reason="conflicting_roster_metadata",
                before_json=Jsonb(metadata_audit["before_json"]),
                after_json=Jsonb({"snapshot_player_id": 0}),
            )
        before = {
            table: _scalar(conn, f"SELECT jsonb_agg(to_jsonb(n) ORDER BY id) FROM {table} n")
            for table in ("encounter.team_report", "public.audit_log", "encounter.team_member")
        }
    done = _alembic(REJECTED_DB, "enclayer01b")
    assert done.returncode != 0
    assert "history completion refuses" in done.stderr
    with _connect(REJECTED_DB) as conn:
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == "enclayer01"
        for table, expected in before.items():
            assert _scalar(conn, f"SELECT jsonb_agg(to_jsonb(n) ORDER BY id) FROM {table} n") == expected
        for table, expected in sources.items():
            assert _scalar(conn, f"SELECT jsonb_agg(to_jsonb(s) ORDER BY id) FROM tournament.{table} s") == expected


# --------------------------------------------------------------------------- #
# The upgrade
# --------------------------------------------------------------------------- #


def test_the_chain_ends_at_enclayer01b_with_every_constraint_validated(migrated) -> None:
    conn = migrated["conn"]
    assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == "enclayer01b"
    assert _rows(conn, "SELECT conrelid::regclass::text, conname FROM pg_constraint WHERE NOT convalidated") == []


def test_ids_survive_the_move(migrated) -> None:
    conn = migrated["conn"]
    moved_to = {
        "tournament.encounter": "encounter.encounter",
        "tournament.encounter_game": "encounter.game",
        "tournament.encounter_result_audit": "encounter.result_audit",
        "tournament.encounter_room_event": "encounter.room_event",
        "tournament.pick_ban_session": "encounter.pick_ban_session",
        "tournament.pick_ban_entry": "encounter.pick_ban_entry",
        "tournament.pick_ban_submission": "encounter.pick_ban_submission",
    }
    after = {table: _id_ranges_of(conn, moved_to[table]) for table in MOVED_TABLES}
    assert after == migrated["before"]


def test_the_audit_label_added_for_the_pending_hold_exists(migrated) -> None:
    labels = _scalar(
        migrated["conn"],
        "SELECT array_agg(e.enumlabel::text) FROM pg_enum e WHERE e.enumtypid = 'encounter.encounterresultauditaction'::regtype",
    )
    assert "auto_pending" in labels


def test_seats_slots_and_placements_come_from_the_sides(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    played = _rows(
        conn,
        "SELECT slot, team_id, score, placement, active FROM encounter.team WHERE encounter_id = %s ORDER BY slot",
        (ids["e_played"],),
    )
    assert played == [(1, ids["team_A"], 2.0, 1, True), (2, ids["team_B"], 1.0, 2, True)]
    # Nothing official yet: no place until there is a result.
    open_ = _rows(
        conn, "SELECT slot, placement FROM encounter.team WHERE encounter_id = %s ORDER BY slot", (ids["e_slots"],)
    )
    assert open_ == [(1, None), (2, None)]
    # An empty seat gets no row; the encounter still holds two.
    assert _scalar(conn, "SELECT count(*) FROM encounter.team WHERE encounter_id = %s", (ids["e_tbd"],)) == 0
    assert _scalar(conn, "SELECT slot_count FROM encounter.encounter WHERE id = %s", (ids["e_tbd"],)) == 2
    lobby = _rows(
        conn, "SELECT slot, team_id FROM encounter.team WHERE encounter_id = %s ORDER BY slot", (ids["e_lobby"],)
    )
    assert lobby == [(1, ids["team_A"]), (2, ids["team_B"]), (3, ids["team_C"])]
    assert _scalar(conn, "SELECT slot_count FROM encounter.encounter WHERE id = %s", (ids["e_lobby"],)) == 3


def test_rosters_are_snapshotted_with_their_roles(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    rows = _rows(
        conn,
        "SELECT tm.workspace_member_id, r.dimension, r.role FROM encounter.team_member tm"
        " JOIN encounter.team t ON t.id = tm.encounter_team_id"
        " JOIN encounter.team_member_role r ON r.team_member_id = tm.id"
        " WHERE t.encounter_id = %s AND t.slot = 1 ORDER BY tm.workspace_member_id",
        (ids["e_played"],),
    )
    assert [(dimension, role) for _, dimension, role in rows] == [("player_role", "tank"), ("player_role", "damage")]


def test_result_sources(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    sources = dict(_rows(conn, "SELECT id, result_source FROM encounter.encounter WHERE result_status = 'confirmed'"))
    assert sources[ids["e_played"]] == "games"  # stored 2-1 IS the games' 2-1
    assert sources[ids["e_admin"]] == "import"  # somebody's number, no games behind it
    assert sources[ids["e_lobby"]] == "games"  # a lobby is always its games
    assert _scalar(conn, "SELECT result_source FROM encounter.encounter WHERE id = %s", (ids["e_slots"],)) is None


def test_games_claims_reports_and_replay_codes(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    first = ids["games"][0]
    scores = _rows(
        conn,
        "SELECT t.slot, gt.score, gt.placement, gt.replay_code FROM encounter.game_team gt"
        " JOIN encounter.team t ON t.id = gt.encounter_team_id WHERE gt.game_id = %s ORDER BY t.slot",
        (first,),
    )
    assert scores == [(1, 1, 1, "ABC123"), (2, 0, 2, None)]
    assert _scalar(conn, "SELECT count(*) FROM encounter.game_claim WHERE game_id = %s", (first,)) == 2
    assert _scalar(conn, "SELECT count(*) FROM encounter.game_claim_result WHERE game_id = %s", (first,)) == 4
    assert _scalar(conn, "SELECT count(*) FROM encounter.team_report WHERE encounter_id = %s", (ids["e_played"],)) == 2
    assert (
        _scalar(conn, "SELECT count(*) FROM encounter.team_report_result WHERE encounter_id = %s", (ids["e_played"],))
        == 4
    )
    assert _scalar(conn, "SELECT count(*) FROM encounter.readiness WHERE encounter_id = %s", (ids["e_played"],)) == 1
    assert (
        _scalar(
            conn,
            "SELECT count(*) FROM encounter.room_event WHERE encounter_id = %s AND encounter_team_id IS NOT NULL",
            (ids["e_played"],),
        )
        == 1
    )


def test_the_journal_is_numbered_and_speaks_participations(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    rows = _rows(
        conn,
        'SELECT result_version, snapshot_scope, jsonb_array_length("after") FROM encounter.result_audit WHERE encounter_id = %s ORDER BY id',
        (ids["e_played"],),
    )
    assert rows == [(1, "game", 2), (2, "encounter", 2)]
    assert _scalar(conn, "SELECT result_version FROM encounter.encounter WHERE id = %s", (ids["e_played"],)) == 2
    adopted = _scalar(conn, "SELECT adopted_team_id FROM encounter.result_audit WHERE id = %s", (ids["audit_confirm"],))
    assert adopted == _scalar(
        conn, "SELECT id FROM encounter.team WHERE encounter_id = %s AND slot = 1", (ids["e_played"],)
    )
    # The lobby totals row keeps its legacy keys, keyed by participation, as an encounter snapshot.
    scope, after = _rows(
        conn, 'SELECT snapshot_scope, "after" FROM encounter.result_audit WHERE id = %s', (ids["audit_lobby"],)
    )[0]
    assert scope == "encounter" and len(after) == 3 and {"encounter_team_id", "points", "games"} <= set(after[0])


def test_pick_ban_rooms_carry_the_pool_the_room_reads(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    pools = {
        key: _scalar(conn, "SELECT pool_json::jsonb FROM encounter.pick_ban_session WHERE id = %s", (ids[key],))
        for key in ("s_slots", "s_hero", "s_pool", "s_gone")
    }
    assert pools["s_slots"] == {
        "mode": "slots",
        "rotation": "alternate",
        "progressive": True,
        "items": [],
        "slots": [[11, 12, 13], [21, 22], [31]],  # best_of 3 cuts the fourth slot
    }
    assert pools["s_hero"] == {
        "mode": "pool",
        "rotation": "result_loser_choice",
        "progressive": True,
        "items": [103, 101, 102],
        "slots": [],
    }
    assert pools["s_pool"] == {
        "mode": "pool",
        "rotation": "fixed",
        "progressive": False,
        "items": [7, 3, 9],
        "slots": [],
    }
    assert pools["s_gone"] == {"mode": "pool", "rotation": "fixed", "progressive": True, "items": [], "slots": []}


def test_pick_ban_sides_become_participations_and_the_ruleset_speaks_slots(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    first, pending, undo = _rows(
        conn,
        "SELECT first_team_id, pending_chooser_team_id, undo_requested_by_team_id FROM encounter.pick_ban_session WHERE id = %s",
        (ids["s_slots"],),
    )[0]
    seats = dict(_rows(conn, "SELECT slot, id FROM encounter.team WHERE encounter_id = %s", (ids["e_slots"],)))
    assert (first, pending, undo) == (seats[1], seats[2], seats[1])
    kinds = _rows(
        conn, "SELECT picked_by_kind::text, protected_by_kind::text FROM encounter.pick_ban_entry ORDER BY id"
    )
    assert kinds == [("team", None), ("team", None), ("decider", "admin"), (None, "team")]
    assert _scalar(conn, "SELECT count(*) FROM encounter.pick_ban_submission WHERE encounter_team_id IS NOT NULL") == 2
    actors = _scalar(
        conn,
        "SELECT ruleset_json::jsonb #>> '{phases,0,steps,0,actors}' FROM encounter.pick_ban_session WHERE id = %s",
        (ids["s_slots"],),
    )
    assert actors == "slot:1"
    assert _scalar(conn, "SELECT seed FROM encounter.team WHERE encounter_id = %s AND slot = 1", (ids["e_slots"],)) == 1


def test_links_and_bracket_positions(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    links = _rows(conn, "SELECT source_position, target_slot, tournament_id FROM tournament.encounter_link ORDER BY id")
    assert links == [(1, 1, ids["t"]), (2, 2, ids["t"])]
    assert _scalar(conn, "SELECT count(*) FROM tournament.bracket_encounter") == _scalar(
        conn, "SELECT count(*) FROM encounter.encounter"
    )


def test_stored_notifications_say_team_names(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    for kind in ("encounter.scheduled", "encounter.dispute_review"):
        payload = _scalar(conn, "SELECT payload_json FROM notification WHERE id = %s", (ids[f"notification_{kind}"],))
        assert payload == {"encounter_id": ids["e_played"], "team_names": ["Team A", "Team B"]}
    # Another kind is not this migration's business.
    assert (
        _scalar(conn, "SELECT payload_json FROM notification WHERE id = %s", (ids["notification_some.other"],))
        == OTHER_PAYLOAD
    )


def test_the_scoring_rules_follow_the_stages(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    preset = lambda key: _scalar(  # noqa: E731
        conn,
        "SELECT r.preset FROM encounter.encounter e JOIN encounter.scoring_rule r ON r.id = e.scoring_rule_id WHERE e.id = %s",
        (ids[key],),
    )
    assert (preset("e_played"), preset("e_pool"), preset("e_lobby")) == ("wins", "wins", "points")


# --------------------------------------------------------------------------- #
# Post-upgrade steps
# --------------------------------------------------------------------------- #


def _run_recompute(dry_run: bool) -> int:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    async def go() -> int:
        engine = create_async_engine(_url(RECOMPUTE_DB), poolclass=NullPool)
        try:
            return await recompute_script.recompute(dry_run, engine)
        finally:
            await engine.dispose()

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    return asyncio.run(go(), loop_factory=loop_factory)


def test_the_lobby_recompute_fills_standings_dry_then_for_real_then_does_nothing(legacy_template) -> None:
    ids = legacy_template["ids"]
    # Its own database: the script reflects the head, and taking the shared ``migrated`` database there would hand
    # the enclayer01b-era reconcile SQL (and every later case on it) a schema it was never written for.
    _recreate(RECOMPUTE_DB, TEMPLATE_DB)
    done = _alembic(RECOMPUTE_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(RECOMPUTE_DB) as conn:
        # This legacy match belongs to the fixture's first game; make that binding
        # explicit before the current-head statistics preflight.
        conn.execute(
            "UPDATE encounter.game SET map_id = (SELECT map_id FROM matches.match WHERE id = %s) WHERE id = %s",
            (ids["match"], ids["games"][0]),
        )
        conn.execute("UPDATE matches.match SET map_index = 1 WHERE id = %s", (ids["match"],))
    # The script is a post-upgrade one-shot and the ORM it uses always reflects the head, so bring the database there
    # first; this scratch copy's legacy rows are fixtures, so legacy01 may drop them.
    done = _alembic(RECOMPUTE_DB, "head", OWT_APPLY_LEGACY_DROP="1")
    assert done.returncode == 0, done.stderr[-3000:]
    conn = _connect(RECOMPUTE_DB)
    standings = "SELECT t.slot, t.score, t.placement FROM encounter.team t WHERE t.encounter_id = %s ORDER BY t.slot"
    assert _rows(conn, standings, (ids["e_lobby"],)) == [(1, 0.0, None), (2, 0.0, None), (3, 0.0, None)]

    # Dry run: reports the work, writes nothing.
    assert _run_recompute(True) == 3
    assert _rows(conn, standings, (ids["e_lobby"],)) == [(1, 0.0, None), (2, 0.0, None), (3, 0.0, None)]

    # Real run: A 10+5 and 6+2, B 6+9 and 10+1, C 3+1 and 3+0.
    assert _run_recompute(False) == 3
    assert _rows(conn, standings, (ids["e_lobby"],)) == [(1, 23.0, 2), (2, 26.0, 1), (3, 7.0, 3)]
    # Series are not lobbies: their seats keep what the migration wrote.
    assert _rows(conn, standings, (ids["e_played"],)) == [(1, 2.0, 1), (2, 1.0, 2)]

    assert _run_recompute(False) == 0
    conn.close()


def test_the_reconcile_report_is_clean_on_a_faithful_migration(migrated) -> None:
    conn = migrated["conn"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        create, summary, skipped = _statements(RECONCILE_SQL)
        tx.execute(create)
        report = _rows(tx, summary)
        assert [row for row in report if row[3] != "ok"] == []
        classes = {row[0]: row[1:3] for row in report}
        assert classes["duel seats"] == (12, 12)  # six seated duels, two seats each; the TBD one has none
        assert classes["lobby seats"] == (3, 3)
        assert classes["map reports -> claims"] == (2, 2)
        assert classes["captain reports -> team reports"] == (2, 2)
        assert classes["replay codes"] == (1, 1)
        assert _rows(tx, skipped) == []
    assert conn


def test_the_reconcile_report_names_every_row_the_migration_could_not_carry(migrated) -> None:
    ids = migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        # A legacy report from a side that holds no seat, and a replay code for a position with no live game.
        orphan_game = _insert(tx, "encounter.game", encounter_id=ids["e_tbd"], position=1)
        report = _insert(
            tx, "tournament.encounter_map_report", game_id=orphan_game, side="away", home_score=1, away_score=0
        )
        code = _insert(tx, "tournament.encounter_map_code", report_id=ids["captain_B"], map_index=2, code="ZZZ999")
        # Two rows of one member in one team that agree on role and rank but not on name.
        twin = _insert(
            tx,
            "tournament.player",
            name="twin",
            rank=2000,
            role="tank",
            tournament_id=ids["t"],
            workspace_member_id=_scalar(
                tx,
                "SELECT workspace_member_id FROM tournament.player WHERE team_id = %s AND role = 'tank'",
                (ids["team_A"],),
            ),
            team_id=ids["team_A"],
        )
        stray = _insert(
            tx,
            "encounter.pick_ban_entry",
            session_id=ids["s_slots"],
            encounter_id=_scalar(
                tx, "SELECT encounter_id FROM encounter.pick_ban_session WHERE id = %s", (ids["s_slots"],)
            ),
            item_id=99,
            order=99,
            team_id=ids["team_A"],
        )
        create, summary, skipped = _statements(RECONCILE_SQL)
        tx.execute(create)
        statuses = {row[0]: row[3] for row in _rows(tx, summary)}
        listed = {(row[0], row[1]) for row in _rows(tx, skipped)}
        tx.rollback()
    assert statuses["map reports -> claims"] == "MISMATCH"
    assert statuses["replay codes"] == "MISMATCH"
    assert statuses["roster rows collapsed by the snapshot"] == "MISMATCH"
    assert statuses["pick-ban entry teams"] == "MISMATCH"
    assert ("map reports -> claims", report) in listed
    assert ("replay codes", code) in listed
    assert ("roster rows collapsed by the snapshot", twin) in listed  # the discarded twin, not the row kept
    assert ("pick-ban entry teams", stray) in listed


def test_a_v1_write_at_the_same_key_does_not_stand_in_for_a_row_the_migration_skipped(migrated) -> None:
    ids = migrated["ids"]
    long_ago = "2026-01-01T00:00:00Z"
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        seat = {
            slot: _scalar(
                tx, "SELECT id FROM encounter.team WHERE encounter_id = %s AND slot = %s", (ids["e_played"], slot)
            )
            for slot in (1, 2)
        }
        # Legacy rows the migration never carried: a second game's home report, the away side's readiness,
        # and a replay code for a position B's seat has no code at.
        report = _insert(
            tx,
            "tournament.encounter_map_report",
            game_id=ids["games"][1],
            side="home",
            home_score=0,
            away_score=1,
            created_at=long_ago,
        )
        readiness = _insert(
            tx, "tournament.encounter_readiness", encounter_id=ids["e_played"], side="away", created_at=long_ago
        )
        code = _insert(tx, "tournament.encounter_map_code", report_id=ids["captain_B"], map_index=2, code="ZZZ999")
        create, _summary, skipped = _statements(RECONCILE_SQL)
        tx.execute(create)
        assert {("map reports -> claims", report), ("readiness", readiness), ("replay codes", code)} <= {
            (row[0], row[1]) for row in _rows(tx, skipped)
        }

        # V1 now writes its own claim, readiness and replay code at those very keys.
        tx.execute(
            "INSERT INTO encounter.game_claim (encounter_id, game_id, claimant_team_id, basis_version)"
            " VALUES (%s, %s, %s, 1)",
            (ids["e_played"], ids["games"][1], seat[1]),
        )
        tx.execute(
            "INSERT INTO encounter.readiness (encounter_id, encounter_team_id) VALUES (%s, %s)",
            (ids["e_played"], seat[2]),
        )
        tx.execute(
            "UPDATE encounter.game_team SET replay_code = 'V1CODE' WHERE game_id = %s AND encounter_team_id = %s",
            (
                ids["games"][1],
                _scalar(
                    tx,
                    "SELECT id FROM encounter.team WHERE encounter_id = %s AND team_id = %s",
                    (ids["e_played"], ids["team_B"]),
                ),
            ),
        )
        still_listed = {(row[0], row[1]) for row in _rows(tx, skipped)}
        tx.rollback()
    assert ("map reports -> claims", report) in still_listed
    assert ("readiness", readiness) in still_listed
    assert ("replay codes", code) in still_listed


def test_deleting_a_team_after_the_upgrade_keeps_the_encounters_it_played(migrated) -> None:
    conn, ids = migrated["conn"], migrated["ids"]
    with _connect(MIGRATED_DB, autocommit=False) as tx:
        # Team C is home/away of migrated encounters whose legacy side columns still name it.
        assert (
            _scalar(
                tx,
                "SELECT count(*) FROM encounter.encounter WHERE home_team_id = %s OR away_team_id = %s",
                (ids["team_C"], ids["team_C"]),
            )
            == 3
        )
        tx.execute("DELETE FROM tournament.team WHERE id = %s", (ids["team_C"],))
        tx.commit()
        assert (
            _scalar(
                tx,
                "SELECT count(*) FROM encounter.encounter WHERE id = ANY(%s)",
                ([ids["e_admin"], ids["e_pool"], ids["e_gone"]],),
            )
            == 3
        )
        assert _scalar(tx, "SELECT count(*) FROM matches.match WHERE id = %s", (ids["match"],)) == 1
        assert _scalar(tx, "SELECT count(*) FROM encounter.team WHERE team_id IS NULL AND name = 'Team C'") == 4
    assert conn  # the module connection stays open for the tests that follow


# --------------------------------------------------------------------------- #
# The live database is not the chain's database
# --------------------------------------------------------------------------- #

#: The real dev database (a pg_dump restored for the rehearsal) names these
#: differently from a database built by running the chain, and the revision used
#: to trust the chain's names: the first rename failed with "relation
#: ix_tournament_pick_ban_session_encounter_id does not exist" and the FK drops
#: after it would have failed the same way. ``LIVE_NAMES`` gives a copy of the
#: seeded template the live names before the upgrade.
LIVE_NAMES = (
    # an index the live database already has under its final name
    "ALTER INDEX tournament.ix_tournament_pick_ban_session_encounter_id RENAME TO ix_pick_ban_session_encounter_id",
    "ALTER INDEX tournament.ix_tournament_pick_ban_entry_session_id RENAME TO ix_pick_ban_entry_session_id",
    "ALTER INDEX tournament.ix_tournament_pick_ban_entry_item_id RENAME TO ix_pick_ban_entry_item_id",
    # indexes and a check constraint that are already (or still) under a name the revision never heard of
    "ALTER INDEX tournament.ix_tournament_encounter_game_encounter_id RENAME TO ix_game_encounter_id",
    "ALTER INDEX tournament.ix_tournament_encounter_game_map_id RENAME TO some_hand_made_index_on_map",
    "ALTER INDEX tournament.uq_encounter_game_encounter_position RENAME TO some_hand_made_unique_position",
    "ALTER TABLE tournament.encounter_game RENAME CONSTRAINT ck_encounter_game_position TO ck_game_position",
    # foreign keys the matches.* tables got from the rename of match_assists / match_kill_feed / match_statistics
    "ALTER TABLE matches.statistics RENAME CONSTRAINT statistics_team_id_fkey TO match_statistics_team_id_fkey",
    "ALTER TABLE matches.kill_feed RENAME CONSTRAINT kill_feed_killer_team_id_fkey TO match_kill_feed_killer_team_id_fkey",
    "ALTER TABLE matches.kill_feed RENAME CONSTRAINT kill_feed_victim_team_id_fkey TO match_kill_feed_victim_team_id_fkey",
    "ALTER TABLE matches.event RENAME CONSTRAINT assists_team_id_fkey TO match_assists_team_id_fkey",
    "ALTER TABLE matches.event RENAME CONSTRAINT assists_related_team_id_fkey TO match_assists_related_team_id_fkey",
    # the link table's foreign keys
    "ALTER TABLE tournament.encounter_link RENAME CONSTRAINT encounter_link_source_encounter_id_fkey TO fk_encounter_link_source",
    "ALTER TABLE tournament.encounter_link RENAME CONSTRAINT encounter_link_target_encounter_id_fkey TO fk_encounter_link_target",
    # the result audit's game key, and the pick-ban keys, under names of their own
    "ALTER TABLE tournament.encounter_result_audit RENAME CONSTRAINT fk_tournament_encounter_result_audit_game_id TO fk_audit_game_by_hand",
    "ALTER TABLE tournament.pick_ban_entry RENAME CONSTRAINT pick_ban_entry_session_id_fkey TO fk_entry_session_by_hand",
    "ALTER TABLE tournament.pick_ban_submission RENAME CONSTRAINT pick_ban_submission_session_id_fkey TO fk_submission_session_by_hand",
    "ALTER TABLE tournament.encounter RENAME CONSTRAINT encounter_tournament_id_fkey TO fk_encounter_tournament_by_hand",
    "ALTER TABLE tournament.encounter RENAME CONSTRAINT encounter_home_team_id_fkey TO fk_encounter_home_by_hand",
    "ALTER TABLE tournament.encounter RENAME CONSTRAINT encounter_away_team_id_fkey TO fk_encounter_away_by_hand",
    "ALTER TABLE tournament.encounter_result_audit RENAME CONSTRAINT encounter_result_audit_adopted_team_id_fkey TO fk_audit_adopted_by_hand",
)


@pytest.fixture(scope="module")
def live_named(legacy_template):
    _recreate(LIVE_DB, TEMPLATE_DB)
    with _connect(LIVE_DB) as conn:
        for statement in LIVE_NAMES:
            conn.execute(statement)
    done = _alembic(LIVE_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(LIVE_DB) as conn:
        yield conn


def test_a_live_named_database_upgrades_to_the_head_with_every_constraint_validated(live_named) -> None:
    assert _scalar(live_named, "SELECT version_num FROM public.alembic_version") == "enclayer01b"
    assert _rows(live_named, "SELECT conrelid::regclass::text, conname FROM pg_constraint WHERE NOT convalidated") == []


def test_indexes_end_under_their_final_names_whatever_they_were_called(live_named) -> None:
    names = {name for (name,) in _rows(live_named, "SELECT indexname FROM pg_indexes WHERE schemaname = 'encounter'")}
    assert {
        "ix_game_encounter_id",
        "ix_game_map_id",
        "uq_game_encounter_position",
        "ix_result_audit_game_id",
        "ix_pick_ban_session_encounter_id",
        "ix_pick_ban_entry_session_id",
        "ix_pick_ban_entry_item_id",
        "ix_pick_ban_submission_session_id",
    } <= names
    assert not names & {
        "some_hand_made_index_on_map",
        "some_hand_made_unique_position",
        "ix_tournament_encounter_game_encounter_id",
        "ix_tournament_encounter_game_map_id",
        "ix_tournament_encounter_result_audit_game_id",
        "ix_tournament_pick_ban_submission_session_id",
    }


def test_the_foreign_keys_the_revision_replaces_are_gone_under_every_name(live_named) -> None:
    gone = _rows(
        live_named,
        "SELECT conname FROM pg_constraint WHERE conname LIKE '%by_hand' OR conname IN"
        " ('fk_encounter_link_source', 'fk_encounter_link_target')",
    )
    assert gone == []
    assert (
        _scalar(live_named, "SELECT count(*) FROM pg_constraint WHERE conname IN ('fk_link_source', 'fk_link_target')")
        == 2
    )


def test_the_match_team_keys_keep_their_live_names_and_come_back_deferred_and_validated(live_named) -> None:
    rows = _rows(
        live_named,
        "SELECT conrelid::regclass::text, conname, condeferrable, convalidated FROM pg_constraint"
        " WHERE contype = 'f' AND confrelid = 'tournament.team'::regclass AND connamespace = 'matches'::regnamespace"
        " ORDER BY 1, 2",
    )
    assert [(table, name) for table, name, *_ in rows] == [
        ("matches.event", "match_assists_related_team_id_fkey"),
        ("matches.event", "match_assists_team_id_fkey"),
        ("matches.kill_feed", "match_kill_feed_killer_team_id_fkey"),
        ("matches.kill_feed", "match_kill_feed_victim_team_id_fkey"),
        ("matches.match", "match_away_team_id_fkey"),
        ("matches.match", "match_home_team_id_fkey"),
        ("matches.statistics", "match_statistics_team_id_fkey"),
    ]
    assert all(deferrable and validated for _, _, deferrable, validated in rows)


# --------------------------------------------------------------------------- #
# enclayer02: the gated contract
# --------------------------------------------------------------------------- #


def _columns(conn: psycopg.Connection, schema: str, table: str) -> set[str]:
    return {
        name
        for (name,) in _rows(
            conn,
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
            (schema, table),
        )
    }


def _contract_copy() -> None:
    _recreate(ENCLAYER02_DB, TEMPLATE_DB)
    done = _alembic(ENCLAYER02_DB, "enclayer01b")
    assert done.returncode == 0, done.stderr[-3000:]


def test_enclayer02_without_the_flag_is_a_stamp(legacy_template) -> None:
    _contract_copy()
    done = _alembic(ENCLAYER02_DB, "enclayer02")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(ENCLAYER02_DB) as conn:
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == "enclayer02"
        assert {"home_team_id", "format"} <= _columns(conn, "encounter", "encounter")
        assert _scalar(conn, "SELECT to_regclass('tournament.encounter_map_report') IS NOT NULL")


def test_enclayer02_with_the_flag_drops_the_legacy_shape(legacy_template) -> None:
    _contract_copy()
    done = _alembic(ENCLAYER02_DB, "enclayer02", OWT_APPLY_ENCOUNTER_LAYER_DROP="1")
    assert done.returncode == 0, done.stderr[-3000:]
    with _connect(ENCLAYER02_DB) as conn:
        legacy = {
            "format",
            "home_team_id",
            "away_team_id",
            "home_score",
            "away_score",
            "stage_id",
            "stage_item_id",
            "round",
        }
        assert not legacy & _columns(conn, "encounter", "encounter")
        assert not {"format", "accepted_home_score", "accepted_away_score"} & _columns(conn, "encounter", "game")
        assert not {"picked_by", "protected_by", "team_id"} & _columns(conn, "encounter", "pick_ban_entry")
        assert not {"first_side", "home_seed", "away_seed", "config_id"} & _columns(
            conn, "encounter", "pick_ban_session"
        )
        assert not {"home_score_before", "home_score_after", "ffa_results_json"} & _columns(
            conn, "encounter", "result_audit"
        )
        assert "side" not in _columns(conn, "encounter", "room_event")
        assert not {"role", "legacy_target_slot"} & _columns(conn, "tournament", "encounter_link")
        assert not {"ffa_columns", "ffa_formula", "ffa_placement_points", "split_lower_bracket"} & _columns(
            conn, "tournament", "stage"
        )
        for table in ("participant", "game_result", "map_report", "captain_report", "map_code", "readiness"):
            assert _scalar(conn, "SELECT to_regclass(%s) IS NULL", (f"tournament.encounter_{table}",))
        assert (
            _scalar(
                conn,
                "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace"
                " WHERE n.nspname = 'tournament' AND t.typname IN ('encounterlinkrole', 'encounterlinkslot',"
                " 'pickbanside', 'firstbanrotation', 'firstpickrule', 'mappickside', 'mappoolentrystatus',"
                " 'mapvetomode', 'mapvetosessionstatus', 'vetoseedsource')",
            )
            == 0
        )


def test_enclayer02_refuses_while_the_reconcile_lists_a_skipped_row(legacy_template) -> None:
    ids = legacy_template["ids"]
    _contract_copy()
    with _connect(ENCLAYER02_DB) as conn:
        orphan_game = _insert(conn, "encounter.game", encounter_id=ids["e_tbd"], position=1)
        report = _insert(
            conn, "tournament.encounter_map_report", game_id=orphan_game, side="away", home_score=1, away_score=0
        )
    done = _alembic(ENCLAYER02_DB, "enclayer02", OWT_APPLY_ENCOUNTER_LAYER_DROP="1")
    assert done.returncode != 0
    assert "map reports -> claims" in done.stderr
    assert str(report) in done.stderr
    with _connect(ENCLAYER02_DB) as conn:
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == "enclayer01b"


def _clone_session(conn: psycopg.Connection, session_id: int, **overrides) -> int:
    """A second room of the same encounter: every column copied from ``session_id`` bar the overrides."""
    types = dict(
        _rows(
            conn,
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a"
            " WHERE a.attrelid = 'encounter.pick_ban_session'::regclass AND a.attnum > 0 AND NOT a.attisdropped",
        )
    )
    columns = sorted(set(types) - {"id"})
    names = ", ".join(f'"{c}"' for c in columns)
    values = ", ".join(f"CAST(%({c})s AS {types[c]})" if c in overrides else f'"{c}"' for c in columns)
    return conn.execute(
        f"INSERT INTO encounter.pick_ban_session ({names})"
        f" SELECT {values} FROM encounter.pick_ban_session WHERE id = %(source)s RETURNING id",
        {**overrides, "source": session_id},
    ).fetchone()[0]


def test_enclayer02_refuses_while_two_rooms_of_one_encounter_disagree_on_the_seeds(legacy_template) -> None:
    """The seeds became the seat's, taken from the lowest-id room; the other room's would be lost silently."""
    ids = legacy_template["ids"]
    _contract_copy()
    with _connect(ENCLAYER02_DB) as conn:
        other = _clone_session(conn, ids["s_slots"], kind="hero", home_seed=3, away_seed=4)
    done = _alembic(ENCLAYER02_DB, "enclayer02", OWT_APPLY_ENCOUNTER_LAYER_DROP="1")
    assert done.returncode != 0
    assert "pick-ban seeds" in done.stderr
    assert f"pick-ban seeds {ids['s_slots']}" in done.stderr and f"pick-ban seeds {other}" in done.stderr
    with _connect(ENCLAYER02_DB) as conn:
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == "enclayer01b"
        assert "home_seed" in _columns(conn, "encounter", "pick_ban_session")


@pytest.mark.parametrize(
    ("lose", "listed"),
    [
        (
            "UPDATE encounter.pick_ban_session SET pending_chooser_team_id = NULL WHERE id = %s",
            "pick-ban pending chooser",
        ),
        (
            "UPDATE encounter.pick_ban_session SET undo_requested_by_team_id = NULL WHERE id = %s",
            "pick-ban undo requester",
        ),
        (
            "UPDATE encounter.team SET seed = NULL WHERE slot = 1 AND encounter_id ="
            " (SELECT encounter_id FROM encounter.pick_ban_session WHERE id = %s)",
            "pick-ban seeds",
        ),
    ],
    ids=["pending-chooser", "undo-requester", "seed"],
)
def test_enclayer02_refuses_while_a_converted_pick_ban_actor_or_seed_is_missing(legacy_template, lose, listed) -> None:
    ids = legacy_template["ids"]
    _contract_copy()
    with _connect(ENCLAYER02_DB) as conn:
        conn.execute(lose, (ids["s_slots"],))
    done = _alembic(ENCLAYER02_DB, "enclayer02", OWT_APPLY_ENCOUNTER_LAYER_DROP="1")
    assert done.returncode != 0
    assert f"{listed} {ids['s_slots']}" in done.stderr
    with _connect(ENCLAYER02_DB) as conn:
        assert _scalar(conn, "SELECT version_num FROM public.alembic_version") == "enclayer01b"
