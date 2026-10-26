"""Populated stats01 transfer, refusal, transactional rollback and exact proofs.

These tests create only uniquely owned local databases through stats_parity;
no worker executes them and no test resets the shared test database.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from scripts import stats01_reconcile as reconcile
from shared.services.stats_evidence import EvidenceError
from shared.testing.db import MIGRATION_PROOF_SKIP, migration_proofs_enabled
from shared.testing.stats_parity import legacy_database, seed_legacy, upgrade_database

BACKEND = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("stats01_revision", BACKEND / "migrations/versions/stats01_stats.py")
assert _spec is not None and _spec.loader is not None
revision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(revision)


@pytest.fixture(scope="module")
def stats01_legacy_template():
    # Every stats01 fixture (and the lifecycle receipt / preflight SQL modules) builds on this template.
    if not migration_proofs_enabled():
        pytest.skip(MIGRATION_PROOF_SKIP)
    with legacy_database() as url:
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                ids = seed_legacy(conn)
        finally:
            engine.dispose()
        yield url, ids


@pytest.fixture
def stats01_legacy_database(stats01_legacy_template):
    template, ids = stats01_legacy_template
    with legacy_database(template_url=template) as url:
        yield url, dict(ids)


@pytest.fixture(scope="module")
def stats01_native_template(stats01_legacy_template):
    template, ids = stats01_legacy_template
    with legacy_database(template_url=template) as url:
        result = upgrade_database(url, "stats01")
        assert result.returncode == 0, result.stdout + result.stderr
        yield url, ids


@pytest.fixture
def stats01_database(stats01_native_template):
    """Fresh committed native clone; shared with the lifecycle receipt tests."""
    template, ids = stats01_native_template
    with legacy_database(template_url=template) as url:
        yield url, dict(ids)


def prepare_proof(conn):
    for statement in revision.RECONCILE_SETUP:
        conn.execute(sa.text(statement))
    conn.execute(sa.text(revision.RECONCILE_VIEW))


def mismatches(conn):
    return conn.execute(
        sa.text("SELECT class,direction,row FROM stats01_reconcile ORDER BY class,direction,row::text")
    ).all()


def classifications(conn):
    for statement in revision.PREFLIGHT_SETUP:
        conn.execute(sa.text(statement))
    return {
        name: conn.execute(sa.text(f"SELECT id,reason FROM ({query}) p ORDER BY id,reason")).all()
        for name, query in revision.PREFLIGHT
    }


# Each corruption is committed in its own isolated legacy clone. No mocked SQL
# results: both the preflight and real Alembic process see the actual bad rows.
REFUSALS = (
    ("2_missing_member", "UPDATE matches.event SET user_id=:player_no_member WHERE match_id=:match"),
    ("3_team_binding", "UPDATE matches.match SET home_team_id=away_team_id WHERE id=:match"),
    (
        "3_team_binding",
        "UPDATE matches.event SET related_user_id=NULL,related_team_id=:team_other_home WHERE match_id=:match",
    ),
    (
        "3_team_binding",
        "UPDATE matches.event SET related_user_id=:player_event_only,related_team_id=NULL WHERE match_id=:match",
    ),
    (
        "3_team_binding",
        "UPDATE encounter.team SET team_id=NULL WHERE encounter_id=:encounter AND team_id=:team_away",
    ),
    (
        "3_team_binding",
        "INSERT INTO encounter.team(encounter_id,tournament_id,team_id,slot,name,active) "
        "SELECT encounter_id,tournament_id,team_id,slot,'Replaced participation',false FROM encounter.team "
        "WHERE encounter_id=:encounter AND team_id=:team_away",
    ),
    (
        "4_duplicate_facts",
        "INSERT INTO matches.statistics(match_id,round,team_id,user_id,hero_id,name,value) SELECT match_id,round,team_id,user_id,hero_id,name,value FROM matches.statistics WHERE match_id=:match LIMIT 1",
    ),
    ("5_player_teams", "UPDATE matches.event SET user_id=:player,team_id=:team_away WHERE match_id=:match"),
    ("6_ownership", "UPDATE matches.match SET source='captain_report' WHERE id=:match"),
    ("6_ownership", "UPDATE matches.match SET code='not-carried' WHERE id=:match"),
    ("6_ownership", "UPDATE matches.match SET map_id=:hero WHERE id=:match"),
    ("6_ownership", "UPDATE matches.statistics SET hero_id=:map WHERE match_id=:match AND hero_id IS NOT NULL"),
    ("6_ownership", "UPDATE matches.match SET log_record_id=:record_other WHERE id=:match"),
    ("6_ownership", "UPDATE log_processing.record SET attached_encounter_id=:encounter_other WHERE id=:record"),
    (
        "7_baselines",
        "UPDATE catalog.role SET code='unresolved_source_role' WHERE id=(SELECT r.id FROM catalog.role r JOIN catalog.role_dimension d ON d.id=r.dimension_id JOIN matches.stat_baselines b ON lower(b.role::text)=r.code WHERE b.id=:baseline AND d.discipline='overwatch' AND r.workspace_id IS NULL)",
    ),
    ("8_raw_provenance", "UPDATE log_processing.record SET content_hash='not-a-sha256' WHERE id=:record"),
    ("8_raw_provenance", "UPDATE log_processing.record SET filename='../escape' WHERE id=:record"),
    ("8_raw_provenance", "UPDATE log_processing.record SET filename='/absolute' WHERE id=:record"),
    ("8_raw_provenance", "UPDATE log_processing.record SET filename='logs/' WHERE id=:record"),
    ("8_raw_provenance", "UPDATE matches.match SET log_name='different-object' WHERE id=:match"),
    ("9_representability", "UPDATE matches.statistics SET round=-1 WHERE match_id=:match"),
    ("9_representability", "UPDATE matches.event SET round=32768 WHERE match_id=:match"),
    ("9_representability", "UPDATE matches.statistics SET value='NaN'::float8 WHERE match_id=:match"),
    ("9_representability", "UPDATE matches.kill_feed SET time='Infinity'::float8 WHERE match_id=:match"),
    ("9_representability", "UPDATE matches.kill_feed SET damage='-Infinity'::float8 WHERE match_id=:match"),
    (
        "9_representability",
        "UPDATE tournament.player SET name=repeat('H',256) WHERE id=:roster_tournament_member_event_only",
    ),
    ("10_dependencies", "UPDATE catalog.alias_miss SET last_ingest_job_id=9223372036854775807 WHERE id=:alias_miss"),
    ("10_dependencies", "UPDATE achievements.rule SET depends_on='{}'::json WHERE id=:rule"),
    ("10_dependencies", "UPDATE achievements.rule SET depends_on='[\"matches.unknown\"]'::json WHERE id=:rule"),
    (
        "10_dependencies",
        "UPDATE event_outbox SET payload_json=jsonb_set(payload_json::jsonb,'{changed_tables}','[1]'::jsonb) WHERE id=:outbox",
    ),
    ("10_dependencies", "CREATE TABLE public.unreviewed_reference(id bigint REFERENCES matches.match(id))"),
    ("10_dependencies", "CREATE VIEW public.unreviewed_view AS SELECT id FROM matches.match"),
)


@pytest.mark.parametrize(
    "mutations",
    (
        ("UPDATE encounter.game SET state='cancelled' WHERE encounter_id=:encounter",),
        ("UPDATE matches.match SET map_index=1,map_id=:map WHERE id=:match_no_raw",),
        ("UPDATE matches.match SET map_index=1,map_id=:map_other WHERE id=:match",),
        ("DELETE FROM encounter.game_claim WHERE game_id=:game", "DELETE FROM encounter.game_team WHERE game_id=:game"),
    ),
)
def test_uncertain_game_claims_preserve_complete_history(stats01_legacy_database, mutations):
    url, ids = stats01_legacy_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            for statement in mutations:
                conn.execute(sa.text(statement), ids)
            games = conn.scalar(sa.text("SELECT count(*) FROM encounter.game"))
            source = conn.execute(sa.text("SELECT id,encounter_id,map_index FROM matches.match ORDER BY id")).all()
            facts = conn.scalar(sa.text("SELECT count(*) FROM matches.statistics"))
            events = conn.scalar(
                sa.text("SELECT (SELECT count(*) FROM matches.event)+(SELECT count(*) FROM matches.kill_feed)")
            )
        result = upgrade_database(url, "stats01a")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT count(*) FROM encounter.game")) == games
            assert (
                conn.execute(sa.text("SELECT id,encounter_id,source_map_index FROM stats.match ORDER BY id")).all()
                == source
            )
            assert (
                conn.scalar(sa.text("SELECT count(*) FROM stats.fact WHERE workspace_member_id IS NOT NULL")) == facts
            )
            assert conn.scalar(sa.text("SELECT count(*) FROM stats.event")) == events
            assert conn.scalar(sa.text("SELECT encounter_game_id FROM stats.match WHERE id=:match"), ids) is None
            prepare_proof(conn)
            assert mismatches(conn) == []
    finally:
        engine.dispose()


def test_null_hashes_and_recordless_references_are_native_unverified_provenance(stats01_legacy_database):
    url, ids = stats01_legacy_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE log_processing.record SET content_hash=NULL WHERE id=:record"), ids)
            conn.execute(sa.text("UPDATE matches.match SET log_record_id=NULL WHERE id=:match"), ids)
            records = conn.execute(
                sa.text(
                    "SELECT id,content_hash,created_at,updated_at,attempts,started_at,finished_at FROM log_processing.record ORDER BY id"
                )
            ).all()
            max_record = conn.scalar(sa.text("SELECT max(id) FROM log_processing.record"))
        result = upgrade_database(url, "stats01a")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.connect() as conn:
            assert (
                conn.execute(
                    sa.text(
                        "SELECT id,content_hash,created_at,updated_at,attempts,started_at,finished_at FROM stats.ingest_job WHERE source_kind<>'historical_reference' ORDER BY id"
                    )
                ).all()
                == records
            )
            job = (
                conn.execute(
                    sa.text(
                        "SELECT j.* FROM stats.ingest_job j JOIN stats.match m ON m.ingest_job_id=j.id WHERE m.id=:match"
                    ),
                    ids,
                )
                .mappings()
                .one()
            )
            assert job["id"] == max_record + 1
            assert job["external_id"] == f"legacy:matches.match:{ids['match']}"
            assert job["source_kind"] == "historical_reference"
            assert job["content_hash"] is None and job["raw_status"] == "unverified"
            assert job["uploader_user_id"] is None and job["attempts"] == 0
            assert job["started_at"] is None and job["finished_at"] is None and job["updated_at"] is None
            assert job["created_at"] == conn.scalar(
                sa.text("SELECT min(created_at) FROM audit_log WHERE action='stats.initial_transfer'")
            )
            assert job["created_at"] != conn.scalar(
                sa.text("SELECT created_at FROM matches.match WHERE id=:match"), ids
            )
            assert conn.scalar(sa.text("SELECT count(*) FROM stats.ingest_job WHERE raw_status<>'unverified'")) == 0
            prepare_proof(conn)
            assert mismatches(conn) == []
        repeated = upgrade_database(url, "stats01a")
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    finally:
        engine.dispose()


@pytest.mark.parametrize("expected_class,mutation", REFUSALS)
def test_preflight_refuses_without_any_committed_cutover(stats01_legacy_database, expected_class, mutation):
    url, ids = stats01_legacy_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(mutation), ids)
        with engine.connect() as conn:
            assert classifications(conn)[expected_class]
        result = upgrade_database(url, "stats01")
        assert result.returncode != 0
        assert expected_class in result.stdout + result.stderr
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT to_regnamespace('stats')")) is None
            assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == "discipline01c"
            assert conn.scalar(sa.text("SELECT count(*) FROM audit_log WHERE action='stats.initial_transfer'")) == 0
    finally:
        engine.dispose()


def test_populated_copy_preserves_orientation_members_and_event_multiplicity(stats01_database):
    url, ids = stats01_database
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            prepare_proof(conn)
            assert mismatches(conn) == []
            assert all(r.status == "ok" for r in conn.execute(sa.text(revision.RECONCILE_SUMMARY)))
            observed = conn.execute(
                sa.text(
                    "SELECT encounter_team_id,source_position FROM stats.match_team WHERE match_id=:match_reversed ORDER BY source_position"
                ),
                ids,
            ).all()
            assert observed == [(ids["encounter_team_away"], 1), (ids["encounter_team_home"], 2)]
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT count(*) FROM stats.match_player WHERE match_id=:match AND workspace_member_id=:member_event_only"
                    ),
                    ids,
                )
                == 1
            )
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT count(*) FROM stats.match_player WHERE match_id=:match_other AND workspace_member_id=:member_other"
                    ),
                    ids,
                )
                == 1
            )
            assert conn.scalar(sa.text("SELECT count(*) FROM stats.segment WHERE segment=0")) == 0
            assert conn.scalar(sa.text("SELECT ingest_job_id FROM stats.match WHERE id=:match_no_raw"), ids) is None
            assert conn.scalar(
                sa.text("SELECT relispopulated FROM pg_class WHERE oid='stats.mv_entity_global_stats'::regclass")
            )
            assert conn.scalar(sa.text("SELECT count(*) FROM stats.event WHERE data IS NULL")) == conn.scalar(
                sa.text("SELECT count(*) FROM matches.event")
            )
            assert conn.scalar(
                sa.text("SELECT count(*) FROM stats.fact WHERE workspace_member_id IS NOT NULL")
            ) == conn.scalar(sa.text("SELECT count(*) FROM matches.statistics"))
            assert conn.scalar(sa.text("SELECT to_regclass('log_processing.discord_channel')")) is None
            for table in ("match", "ingest_job", "event", "stat_baseline"):
                next_id = conn.scalar(sa.text(f"SELECT nextval(pg_get_serial_sequence('stats.{table}','id'))"))
                assert next_id > conn.scalar(sa.text(f"SELECT coalesce(max(id),0) FROM stats.{table}"))
        repeated = upgrade_database(url, "stats01")
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "column,delta,expected_classes",
    [
        ("avg", 5e-13, {"mv", "mv_derivation"}),
        ("avg", 2e-12, {"mv", "mv_derivation"}),
        ("best_value", 5e-13, {"mv", "mv_derivation"}),
    ],
    ids=("sub_tolerance_avg", "larger_avg", "best_value"),
)
def test_mv_canonical_average_never_waives_native_derivation(
    stats01_database, tmp_path, column, delta, expected_classes
):
    url, _ = stats01_database
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("ALTER MATERIALIZED VIEW stats.mv_entity_global_stats RENAME TO original_mv"))
            projection = [
                f"{name}+{delta!r} AS {name}" if name == column else name
                for name in ("discipline", "stat_id", "entity_id", "best_value", "avg", "metadata")
            ]
            conn.execute(
                sa.text(
                    f"CREATE MATERIALIZED VIEW stats.mv_entity_global_stats AS SELECT {','.join(projection)} FROM stats.original_mv"
                )
            )
            prepare_proof(conn)
            assert {row[0] for row in mismatches(conn)} == expected_classes
        with reconcile.readonly_snapshot(engine, revision) as conn:
            with pytest.raises(EvidenceError):
                reconcile.capture_receipt(conn, tmp_path / "receipt", revision)
        assert not (tmp_path / "receipt" / "manifest.json").exists()
    finally:
        engine.dispose()


def test_restored_catalog_names_and_stale_legacy_mv_are_not_authority(stats01_legacy_database):
    url, ids = stats01_legacy_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("REFRESH MATERIALIZED VIEW matches.mv_hero_global_stats"))
            conn.execute(
                sa.text(
                    "UPDATE matches.statistics SET value=value+17 WHERE match_id=:match AND name::text='Eliminations'"
                ),
                ids,
            )
            quote = conn.dialect.identifier_preparer.quote
            rows = conn.execute(
                sa.text(
                    "SELECT conrelid::regclass::text AS relation,conname,oid FROM pg_constraint WHERE contype='f' AND conrelid IN ('achievements.evaluation_result'::regclass,'achievements.override'::regclass,'log_processing.discord_channel'::regclass)"
                )
            ).all()
            for row in rows:
                conn.execute(
                    sa.text(
                        f"ALTER TABLE {row.relation} RENAME CONSTRAINT {quote(row.conname)} TO {quote('restored_fk_' + str(row.oid))}"
                    )
                )
            indexes = conn.execute(
                sa.text(
                    "SELECT c.relname,c.oid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE i.indrelid='log_processing.discord_channel'::regclass AND i.indisunique AND NOT EXISTS(SELECT 1 FROM pg_constraint k WHERE k.conindid=i.indexrelid)"
                )
            ).all()
            for row in indexes:
                conn.execute(
                    sa.text(
                        f"ALTER INDEX log_processing.{quote(row.relname)} RENAME TO {quote('restored_index_' + str(row.oid))}"
                    )
                )
        result = upgrade_database(url, "stats01")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.connect() as conn:
            prepare_proof(conn)
            assert mismatches(conn) == []
    finally:
        engine.dispose()


CORRUPTIONS = (
    (
        "facts",
        "UPDATE stats.fact SET value=value+1 WHERE match_id=:match AND workspace_member_id=:member AND segment=0 AND entity_id IS NULL",
    ),
    (
        "players",
        "UPDATE stats.match_player SET handle_snapshot=handle_snapshot||'changed' WHERE match_id=:match AND workspace_member_id=:member",
    ),
    (
        "players",
        "UPDATE stats.match_player SET encounter_team_id=:encounter_team_away WHERE match_id=:match AND workspace_member_id=:member",
    ),
    ("matches", "UPDATE stats.match SET created_at=created_at+interval '1 second' WHERE id=:match"),
    (
        "jobs",
        "UPDATE stats.ingest_job SET finished_at=coalesce(finished_at,created_at)+interval '1 second' WHERE id=:record",
    ),
    (
        "events",
        "UPDATE stats.event SET data=jsonb_set(data,'{damage}','123456'::jsonb) WHERE match_id=:match AND data IS NOT NULL",
    ),
    (
        "events",
        "DELETE FROM stats.event WHERE id=(SELECT min(id) FROM stats.event WHERE match_id=:match AND data IS NULL)",
    ),
    (
        "events",
        "INSERT INTO stats.event(match_id,segment,t,type_id,actor_member_id,actor_team_id,target_member_id,target_team_id,entity_id,related_entity_id,entity_kind,data) SELECT match_id,segment,t,type_id,actor_member_id,actor_team_id,target_member_id,target_team_id,entity_id,related_entity_id,entity_kind,data FROM stats.event WHERE match_id=:match AND data IS NULL LIMIT 1",
    ),
    ("teams", "UPDATE stats.match_team SET source_position=source_position+10 WHERE match_id=:match"),
    ("segments", "UPDATE stats.segment SET attrs=jsonb_build_object('changed',true) WHERE match_id=:match"),
    ("baselines", "UPDATE stats.stat_baseline SET meta=jsonb_build_object('changed',true) WHERE id=:baseline"),
    ("channel", "UPDATE stats.discord_channel SET channel_name='tampered-before-capture' WHERE id=:channel"),
    ("alias_ref", "UPDATE catalog.alias_miss SET last_ingest_job_id=NULL WHERE id=:alias_miss"),
    ("evaluation_ref", "UPDATE achievements.evaluation_result SET match_id=NULL WHERE id=:evaluation_result"),
    ("override_ref", "UPDATE achievements.override SET match_id=NULL WHERE id=:override"),
    ("rule_dependency", "UPDATE achievements.rule SET depends_on='[]'::json WHERE id=:rule"),
    (
        "outbox_dependency",
        "UPDATE event_outbox SET payload_json=jsonb_set(payload_json::jsonb,'{changed_tables}','[]'::jsonb) WHERE id=:outbox",
    ),
    (
        "oracle_integrity",
        "DELETE FROM audit_log WHERE action='stats.initial_transfer' AND after_json->'stats01_oracle'->>'kind'='manifest'",
    ),
    (
        "oracle_integrity",
        "DELETE FROM audit_log WHERE id=(SELECT min(id) FROM audit_log WHERE action='stats.initial_transfer' AND after_json->'stats01_oracle'->>'kind'='chunk')",
    ),
    (
        "oracle_integrity",
        "UPDATE audit_log SET after_json=jsonb_set(after_json,'{stats01_oracle,sha256}',to_jsonb(repeat('0',64))) WHERE action='stats.initial_transfer' AND after_json->'stats01_oracle'->>'kind'='chunk'",
    ),
)


@pytest.mark.parametrize("expected_class,mutation", CORRUPTIONS)
def test_exact_proof_detects_corruption_before_initial_capture(stats01_database, expected_class, mutation):
    url, ids = stats01_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(mutation), ids)
        with engine.connect() as conn:
            prepare_proof(conn)
            assert expected_class in {row[0] for row in mismatches(conn)}
    finally:
        engine.dispose()


def test_late_failure_rolls_back_transfer_channel_repoints_and_oracle(stats01_legacy_database, monkeypatch):
    url, ids = stats01_legacy_database
    engine = sa.create_engine(url)
    original = revision._assert_reconciled

    def fail_after_proof():
        original()
        raise RuntimeError("injected after full proof")

    monkeypatch.setattr(revision, "_assert_reconciled", fail_after_proof)
    try:
        with pytest.raises(RuntimeError, match="injected after full proof"):
            with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
                revision.upgrade()
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT to_regnamespace('stats')")) is None
            assert (
                conn.scalar(sa.text("SELECT count(*) FROM log_processing.discord_channel WHERE id=:channel"), ids) == 1
            )
            assert conn.scalar(sa.text("SELECT count(*) FROM audit_log WHERE action='stats.initial_transfer'")) == 0
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_constraint WHERE conrelid='achievements.override'::regclass AND confrelid='matches.match'::regclass"
                    )
                )
                == 1
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "owner,key", (("stats.match", "match"), ("encounter.encounter", "encounter"), ("workspace", "workspace"))
)
def test_owner_delete_cascades_all_native_observations(stats01_database, owner, key):
    url, ids = stats01_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(f"DELETE FROM {owner} WHERE id=:id"), {"id": ids[key]})
            conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
            for table in ("match_team", "match_player", "fact", "event", "segment"):
                assert conn.scalar(sa.text(f"SELECT count(*) FROM stats.{table} WHERE match_id=:match"), ids) == 0
    finally:
        engine.dispose()


def test_member_alone_cannot_erase_played_history_and_event_fks_are_deferred(stats01_database):
    url, ids = stats01_database
    engine = sa.create_engine(url)
    try:
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as conn:
                conn.execute(sa.text("DELETE FROM workspace_member WHERE id=:member"), ids)
                conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
        with engine.begin() as conn:
            saved = (
                conn.execute(
                    sa.text(
                        "DELETE FROM stats.match_player WHERE match_id=:match AND workspace_member_id=:member_event_only RETURNING match_id,encounter_team_id,workspace_member_id,handle_snapshot,observed_role_id"
                    ),
                    ids,
                )
                .mappings()
                .one()
            )
            conn.execute(
                sa.text(
                    "INSERT INTO stats.match_player(match_id,encounter_team_id,workspace_member_id,handle_snapshot,observed_role_id) VALUES(:match_id,:encounter_team_id,:workspace_member_id,:handle_snapshot,:observed_role_id)"
                ),
                dict(saved),
            )
            conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
    finally:
        engine.dispose()


def test_partial_stats_schema_refused_not_resumed(stats01_legacy_database):
    url, _ = stats01_legacy_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE SCHEMA stats"))
        result = upgrade_database(url, "stats01")
        assert result.returncode != 0
        assert "partial stats schema" in result.stdout + result.stderr
    finally:
        engine.dispose()


def test_empty_inplace_classes_still_have_complete_oracle_manifest(stats01_legacy_database):
    url, _ = stats01_legacy_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            for table in (
                "achievements.evaluation_result",
                "achievements.override",
                "achievements.rule",
                "event_outbox",
                "catalog.alias_miss",
                "log_processing.discord_channel",
            ):
                conn.execute(sa.text(f"DELETE FROM {table}"))
        result = upgrade_database(url, "stats01")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.connect() as conn:
            prepare_proof(conn)
            assert mismatches(conn) == []
            manifest = conn.execute(sa.text("SELECT class,count,chunks FROM stats01_oracle_manifest")).all()
            assert {row[0] for row in manifest} == {name for name, _, _ in revision.INPLACE_CLASSES}
            assert all(row[1:] == (0, 0) for row in manifest)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "table,column", (("matches.statistics", "name"), ("matches.event", "name"), ("matches.kill_feed", "ability"))
)
def test_unknown_frozen_enum_member_is_refused(stats01_legacy_database, table, column):
    url, ids = stats01_legacy_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            enum_type = conn.scalar(
                sa.text(
                    "SELECT atttypid::regtype::text FROM pg_attribute WHERE attrelid=to_regclass(:table) AND attname=:column"
                ),
                {"table": table, "column": column},
            )
            conn.execute(sa.text(f"ALTER TYPE {enum_type} ADD VALUE 'Stats01Unmapped'"))
        with engine.begin() as conn:
            conn.execute(sa.text(f"UPDATE {table} SET {column}='Stats01Unmapped' WHERE match_id=:match"), ids)
        with engine.connect() as conn:
            assert classifications(conn)["9_representability"]
        result = upgrade_database(url, "stats01")
        assert result.returncode != 0
        assert "9_representability" in result.stdout + result.stderr
    finally:
        engine.dispose()


@pytest.mark.parametrize("identity", ("site_only", "nonprimary", "wrong_provider", "blank_primary"))
def test_missing_handle_is_refused_without_inventing_identity(stats01_legacy_database, identity):
    from test_stats01_preflight_sql import operator_results

    url, ids = stats01_legacy_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE tournament.player SET name='' WHERE id=:roster_tournament_member_event_only"), ids
            )
            # The unrelated site name remains nonempty; it is never handle evidence.
            mutations = {
                "site_only": "DELETE FROM players.social_account WHERE user_id=:player_event_only",
                "nonprimary": "UPDATE players.social_account SET is_primary=false WHERE user_id=:player_event_only",
                "wrong_provider": "UPDATE players.social_account SET provider='riot' WHERE user_id=:player_event_only",
                "blank_primary": "UPDATE players.social_account SET username=' ' WHERE user_id=:player_event_only",
            }
            conn.execute(sa.text(mutations[identity]), ids)
        with engine.connect() as conn:
            assert classifications(conn)["9_representability"] == [(ids["player_event_only"], "unusable_handle")]
        summary, details, _ = operator_results(url, "stats01_preflight.sql")
        assert next(row for row in summary if row["class"] == "9_representability")["offending"] == 1
        assert {"class": "9_representability", "id": ids["player_event_only"], "reason": "unusable_handle"} in details
        result = upgrade_database(url, "stats01")
        assert result.returncode != 0
        assert "unusable_handle" in result.stdout + result.stderr
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT to_regnamespace('stats')")) is None
            assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == "discipline01c"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "mutation",
    (
        "UPDATE tournament.player SET tournament_id=:tournament_hidden WHERE id=:roster_tournament_member_event_only",
        "UPDATE tournament.player SET team_id=:team_away WHERE id=:roster_tournament_member_event_only",
        "UPDATE tournament.player SET workspace_member_id=:member WHERE id=:roster_tournament_member_event_only",
        "UPDATE tournament.player SET name=' ' WHERE id=:roster_tournament_member_event_only",
    ),
    ids=("wrong_tournament", "wrong_team", "wrong_member", "blank_roster"),
)
def test_event_only_handle_falls_back_only_when_its_scoped_roster_is_absent(stats01_legacy_database, mutation):
    url, ids = stats01_legacy_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(mutation), ids)
        with engine.connect() as conn:
            assert not any(classifications(conn).values())
        result = upgrade_database(url, "stats01")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.connect() as conn:
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT handle_snapshot FROM stats.match_player WHERE match_id=:match AND workspace_member_id=:member_event_only"
                    ),
                    ids,
                )
                == "P4Substitute#1234"
            )
            prepare_proof(conn)
            assert mismatches(conn) == []
    finally:
        engine.dispose()


def test_receipt_lookups_observe_the_snapshot_not_connection_preparation(stats01_database):
    url, ids = stats01_database
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    writer = sa.create_engine(url, poolclass=sa.pool.NullPool)

    @sa.event.listens_for(engine, "commit")
    def after_preparation(conn):
        conn.info["prepared_receipt"] = True

    @sa.event.listens_for(engine, "begin")
    def rename_before_snapshot(conn):
        if conn.info.pop("prepared_receipt", False):
            with writer.begin() as changed:
                changed.execute(
                    sa.text("UPDATE tournament.player SET name='Snapshot#1234' WHERE id=:roster_player"), ids
                )

    try:
        with reconcile.readonly_snapshot(engine, revision) as conn:
            assert conn.scalar(sa.text("SHOW transaction_read_only")) == "on"
            assert (
                conn.execute(
                    sa.text("SELECT handle_snapshot FROM stats01_handles WHERE match_id=:match AND player_id=:player"),
                    ids,
                ).scalar_one()
                == "Snapshot#1234"
            )
    finally:
        engine.dispose()
        writer.dispose()


def test_historical_roster_handles_remain_observation_scoped_through_full_receipt(stats01_legacy_database, tmp_path):
    from test_stats01_preflight_sql import operator_results

    url, ids = stats01_legacy_database
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("""UPDATE tournament.player SET name=CASE id
                WHEN :roster_player THEN 'Historical#1234'
                WHEN :roster_tournament_other_member_other THEN 'OtherWorkspace#1234'
                WHEN :roster_tournament_hidden_member THEN 'OtherTournament#1234' END
                WHERE id IN (:roster_player,:roster_tournament_other_member_other,:roster_tournament_hidden_member)"""),
                ids,
            )
            conn.execute(
                sa.text("""INSERT INTO tournament.player(id,name,rank,tournament_id,team_id,workspace_member_id,is_substitution)
                SELECT (SELECT min(id)-1 FROM tournament.player),'Substitute#1234',rank,tournament_id,team_id,workspace_member_id,true
                FROM tournament.player WHERE id=:roster_player"""),
                ids,
            )
            conn.execute(
                sa.text("""INSERT INTO tournament.player(id,name,rank,tournament_id,team_id,workspace_member_id,is_substitution)
                SELECT (SELECT max(id)+1 FROM tournament.player),'LaterRoster#1234',rank,tournament_id,team_id,workspace_member_id,false
                FROM tournament.player WHERE id=:roster_player"""),
                ids,
            )
            conn.execute(
                sa.text("""UPDATE players.social_account SET username='CurrentPrimary#1234'
                WHERE user_id=:player AND provider='battlenet' AND is_primary"""),
                ids,
            )
            conn.execute(sa.text("""UPDATE players."user" SET name='Unrelated site display' WHERE id=:player"""), ids)
        summary, details, _ = operator_results(url, "stats01_preflight.sql")
        assert all(row["status"] == "ok" for row in summary)
        assert details == []
        result = upgrade_database(url, "stats01")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.connect() as conn:
            actual = conn.execute(
                sa.text("""SELECT match_id,workspace_member_id,handle_snapshot FROM stats.match_player
                WHERE (match_id IN (:match,:match_reversed,:match_hidden) AND workspace_member_id=:member)
                   OR (match_id=:match_other AND workspace_member_id=:member_other)
                ORDER BY match_id,workspace_member_id"""),
                ids,
            ).all()
            assert actual == sorted(
                [
                    (ids["match"], ids["member"], "Historical#1234"),
                    (ids["match_reversed"], ids["member"], "Historical#1234"),
                    (ids["match_hidden"], ids["member"], "OtherTournament#1234"),
                    (ids["match_other"], ids["member_other"], "OtherWorkspace#1234"),
                ]
            )
            prepare_proof(conn)
            assert mismatches(conn) == []
        summary, details = operator_results(url, "stats01_reconcile.sql")
        assert all(row["status"] == "ok" and row["legacy"] == row["migrated"] for row in summary)
        assert details == []
        receipt = tmp_path / "receipt"
        with reconcile.readonly_snapshot(engine, revision) as conn:
            assert reconcile.capture_receipt(conn, receipt, revision)["exit_code"] == 0
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE tournament.player SET name='RenamedRoster#1234'"))
            conn.execute(sa.text("UPDATE players.social_account SET username='RenamedPrimary#1234' WHERE is_primary"))
        with reconcile.readonly_snapshot(engine, revision, receipt_dir=receipt) as conn:
            assert reconcile.check_receipt(conn, receipt, revision)["exit_code"] == 0
        with engine.begin() as conn:
            conn.execute(
                sa.text("""UPDATE stats.match_player SET handle_snapshot='CurrentPrimary#1234'
                WHERE match_id=:match AND workspace_member_id=:member"""),
                ids,
            )
        with reconcile.readonly_snapshot(engine, revision, receipt_dir=receipt) as conn:
            assert reconcile.check_receipt(conn, receipt, revision)["exit_code"] == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("damage", ("old_format", "missing_handles", "missing_handle_manifest", "rehashed_omission"))
def test_receipt_requires_complete_scoped_handle_evidence(stats01_database, tmp_path, damage):
    url, _ = stats01_database
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    receipt = tmp_path / "receipt"
    try:
        with reconcile.readonly_snapshot(engine, revision) as conn:
            assert reconcile.capture_receipt(conn, receipt, revision)["exit_code"] == 0
        manifest_path = receipt / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        if damage == "old_format":
            manifest["format"] = "stats01-receipt/1"
        elif damage == "missing_handles":
            (receipt / "handles.jsonl").unlink()
        elif damage == "missing_handle_manifest":
            manifest.pop("handles_sha256")
        else:
            lines = (receipt / "handles.jsonl").read_bytes().splitlines(keepends=True)
            assert lines
            raw = b"".join(lines[1:])
            (receipt / "handles.jsonl").write_bytes(raw)
            manifest.update(handles_count=len(lines) - 1, handles_sha256=hashlib.sha256(raw).hexdigest())
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(EvidenceError):
            reconcile.load_manifest(receipt, revision)
        with pytest.raises(EvidenceError), reconcile.readonly_snapshot(engine, revision, receipt_dir=receipt):
            pass
    finally:
        engine.dispose()


def test_report_cannot_overwrite_scoped_handle_evidence(tmp_path):
    handles = tmp_path / "handles.jsonl"
    handles.write_bytes(b"immutable handle evidence\n")
    assert reconcile.main(["--mode", "capture", "--receipt-dir", str(tmp_path), "--report", str(handles)]) == 1
    assert handles.read_bytes() == b"immutable handle evidence\n"


def test_transfer_crosses_keyset_boundary_without_dropping_rows(stats01_legacy_database):
    url, ids = stats01_legacy_database
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    batch_sizes = []
    try:
        with engine.begin() as conn:
            game_base = conn.scalar(sa.text("SELECT max(id) FROM encounter.game")) + 1000
            match_base = conn.scalar(sa.text("SELECT max(id) FROM matches.match")) + 1000
            for offset in range(101):
                params = {
                    **ids,
                    "game_id": game_base + offset * 7,
                    "match_id": match_base + offset * 11,
                    "position": 1000 + offset,
                }
                conn.execute(
                    sa.text("""INSERT INTO encounter.game(id,encounter_id,position,map_id,state,result_version)
                  VALUES(:game_id,:encounter,:position,:map,'planned',0)"""),
                    params,
                )
                conn.execute(
                    sa.text("""INSERT INTO encounter.game_team(game_id,encounter_id,encounter_team_id,column_values)
                  VALUES(:game_id,:encounter,:encounter_team_home,'{}'),(:game_id,:encounter,:encounter_team_away,'{}')"""),
                    params,
                )
                conn.execute(
                    sa.text("""INSERT INTO matches.match(id,home_team_id,away_team_id,home_score,away_score,time,
                  log_name,code,log_record_id,source,encounter_id,map_id,map_index)
                  SELECT :match_id,home_team_id,away_team_id,home_score,away_score,time,log_name,code,log_record_id,source,
                  encounter_id,map_id,:position FROM matches.match WHERE id=:match"""),
                    params,
                )
                conn.execute(
                    sa.text("""INSERT INTO matches.statistics(match_id,round,team_id,user_id,hero_id,name,value)
                  SELECT :match_id,round,team_id,user_id,hero_id,name,value FROM matches.statistics WHERE match_id=:match"""),
                    params,
                )

        def observe(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO stats.fact") and isinstance(parameters, dict):
                batch_sizes.append(
                    conn.scalar(
                        sa.text("SELECT count(*) FROM matches.match WHERE id BETWEEN :lo AND :hi"),
                        {"lo": parameters["lo"], "hi": parameters["hi"]},
                    )
                )

        sa.event.listen(engine, "before_cursor_execute", observe)
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            revision.upgrade()
        sa.event.remove(engine, "before_cursor_execute", observe)
        assert batch_sizes and max(batch_sizes) <= 100
        assert 100 in batch_sizes
        with engine.connect() as conn:
            prepare_proof(conn)
            assert mismatches(conn) == []
    finally:
        engine.dispose()


def test_initial_owner_universe_does_not_self_certify_extra_jobs(stats01_database):
    url, ids = stats01_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("""INSERT INTO stats.ingest_job(workspace_id,discipline,source_kind,external_id,content_hash,
              filename,raw_ref,status) SELECT workspace_id,discipline,source_kind,'unreviewed-extra',content_hash,
              filename,raw_ref,status FROM stats.ingest_job WHERE id=:record"""),
                ids,
            )
        with engine.connect() as conn:
            prepare_proof(conn)
            assert "job_owners" in {r[0] for r in mismatches(conn)}
    finally:
        engine.dispose()


def test_dependency_rewrite_preserves_order_unrelated_duplicates_and_payload(stats01_legacy_database):
    url, ids = stats01_legacy_database
    engine = sa.create_engine(url)
    old = '["unrelated","matches.event","matches.statistics","matches.kill_feed","unrelated","matches.match"]'
    expected = ["unrelated", "stats.event", "stats.fact", "unrelated", "stats.match"]
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE achievements.rule SET depends_on=CAST(:old AS json) WHERE id=:rule"),
                {**ids, "old": old},
            )
            conn.execute(
                sa.text("""UPDATE event_outbox SET payload_json=jsonb_set(
              jsonb_set(payload_json::jsonb,'{changed_tables}',CAST(:old AS jsonb)),
              '{untouched}','{"nested":[1,null,"x"]}'::jsonb) WHERE id=:outbox"""),
                {**ids, "old": old},
            )
        result = upgrade_database(url, "stats01")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT depends_on FROM achievements.rule WHERE id=:rule"), ids) == expected
            payload = conn.scalar(sa.text("SELECT payload_json FROM event_outbox WHERE id=:outbox"), ids)
            assert payload["changed_tables"] == expected
            assert payload["untouched"] == {"nested": [1, None, "x"]}
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", ("matches.statistics", "matches.kill_feed", "matches.event"))
def test_null_segment_refused_in_drifted_legacy_schema(stats01_legacy_database, table):
    url, ids = stats01_legacy_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN round DROP NOT NULL"))
            conn.execute(sa.text(f"UPDATE {table} SET round=NULL WHERE match_id=:match"), ids)
        with engine.connect() as conn:
            assert classifications(conn)["9_representability"]
        result = upgrade_database(url, "stats01")
        assert result.returncode != 0
        assert "invalid_segment" in result.stdout + result.stderr
    finally:
        engine.dispose()


def test_original_bound_head_upgrades_without_rewriting_observations(stats01_database):
    from shared.testing.stats_parity import original_stats01_shape

    url, ids = stats01_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            original_stats01_shape(conn)
            jobs = conn.execute(
                sa.text(
                    "SELECT id,content_hash,created_at,updated_at,attempts,started_at,finished_at FROM stats.ingest_job ORDER BY id"
                )
            ).all()
            facts = conn.scalar(sa.text("SELECT count(*) FROM stats.fact"))
            events = conn.scalar(sa.text("SELECT count(*) FROM stats.event"))
            oracle = conn.execute(
                sa.text("SELECT id,after_json FROM audit_log WHERE action='stats.initial_transfer' ORDER BY id")
            ).all()
        result = upgrade_database(url, "stats01a")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.connect() as conn:
            assert (
                conn.execute(
                    sa.text(
                        "SELECT id,content_hash,created_at,updated_at,attempts,started_at,finished_at FROM stats.ingest_job ORDER BY id"
                    )
                ).all()
                == jobs
            )
            assert conn.scalar(sa.text("SELECT count(*) FROM stats.fact")) == facts
            assert conn.scalar(sa.text("SELECT count(*) FROM stats.event")) == events
            assert (
                conn.execute(
                    sa.text("SELECT id,after_json FROM audit_log WHERE action='stats.initial_transfer' ORDER BY id")
                ).all()
                == oracle
            )
            assert conn.scalar(sa.text("SELECT count(*) FROM stats.ingest_job WHERE raw_status<>'unverified'")) == 0
            assert conn.execute(
                sa.text("SELECT encounter_id,source_map_index FROM stats.match WHERE id=:match"), ids
            ).one() == (ids["encounter"], 1)
            prepare_proof(conn)
            assert mismatches(conn) == []
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "mutation",
    (
        "UPDATE stats.ingest_job SET attempts=attempts+1 WHERE id=:record",
        "UPDATE stats.fact SET value=value+1 WHERE match_id=:match AND segment=0",
        "DELETE FROM audit_log WHERE action='stats.initial_transfer'",
    ),
)
def test_original_bound_head_refuses_unexplained_mutations_before_ddl(stats01_database, mutation):
    from shared.testing.stats_parity import original_stats01_shape

    url, ids = stats01_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            original_stats01_shape(conn)
            conn.execute(sa.text(mutation), ids)
        result = upgrade_database(url, "stats01a")
        assert result.returncode != 0
        assert "stats01a refuses unexplained" in result.stdout + result.stderr
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == "stats01"
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT count(*) FROM information_schema.columns WHERE table_schema='stats' AND column_name IN ('raw_status','source_map_index')"
                    )
                )
                == 0
            )
            assert conn.scalar(sa.text("SELECT count(*) FROM audit_log WHERE action='stats.history_upgrade'")) == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("native_value", ("-0", "0"))
def test_original_bound_head_preserves_exact_signed_zero_outside_mv(stats01_database, native_value):
    from shared.testing.stats_parity import original_stats01_shape

    url, ids = stats01_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            source = conn.execute(
                sa.text("""UPDATE matches.statistics SET value='-0'::double precision
                WHERE match_id=:match AND round=0 AND hero_id IS NULL AND name::text='HeroTimePlayed'"""),
                ids,
            )
            target = conn.execute(
                sa.text("""UPDATE stats.fact SET value=CAST(:value AS double precision)
                WHERE match_id=:match AND segment=0 AND entity_id IS NULL
                  AND stat_id=(SELECT id FROM stats.stat_def WHERE discipline='overwatch' AND code='hero_time_played')"""),
                {**ids, "value": native_value},
            )
            assert source.rowcount == target.rowcount > 0
            original_stats01_shape(conn)
            oracle = conn.execute(
                sa.text("SELECT id,after_json FROM audit_log WHERE action='stats.initial_transfer' ORDER BY id")
            ).all()
        result = upgrade_database(url, "stats01a")
        if native_value == "-0":
            assert result.returncode == 0, result.stdout + result.stderr
        else:
            assert result.returncode != 0
            assert "stats01a refuses unexplained facts semantic differences" in result.stdout + result.stderr
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == (
                "stats01a" if native_value == "-0" else "stats01"
            )
            assert (
                conn.execute(
                    sa.text("SELECT id,after_json FROM audit_log WHERE action='stats.initial_transfer' ORDER BY id")
                ).all()
                == oracle
            )
            assert conn.scalar(sa.text("SELECT count(*) FROM audit_log WHERE action='stats.history_upgrade'")) == (
                1 if native_value == "-0" else 0
            )
            assert conn.scalar(
                sa.text("""SELECT count(*) FROM information_schema.columns
                WHERE table_schema='stats' AND column_name IN ('raw_status','source_map_index')""")
            ) == (2 if native_value == "-0" else 0)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "resident_metadata,allowed",
    (
        ({"username": "P4 Bravo"}, True),
        ({"username": "P4 Substitute"}, False),
        ({"username": "P4 Bravo", "map_name": "Not the source map"}, False),
    ),
    ids=("legitimate_co_best", "non_holder_username", "foreign_metadata"),
)
def test_original_bound_head_accepts_only_proven_co_best_metadata(stats01_legacy_database, resident_metadata, allowed):
    from shared.testing.stats_parity import original_stats01_shape

    url, ids = stats01_legacy_database
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    best_query = """SELECT best_value,metadata->>'username' FROM stats.mv_entity_global_stats
        WHERE entity_id=:hero AND stat_id=(SELECT id FROM stats.stat_def
        WHERE discipline='overwatch' AND code='all_damage_dealt')"""
    preserved_queries = (
        """SELECT to_jsonb(f)-'value',encode(float8send(value),'hex') FROM stats.fact f
        ORDER BY match_id,segment,workspace_member_id,entity_id,stat_id,encounter_team_id""",
        "SELECT id,encode(float8send(duration_s),'hex') FROM stats.match ORDER BY id",
        """SELECT to_jsonb(s)-'value',encode(float8send(value),'hex')
        FROM matches.statistics s ORDER BY id""",
        "SELECT to_jsonb(g) FROM encounter.game g ORDER BY id",
        "SELECT to_jsonb(t) FROM encounter.game_team t ORDER BY game_id,encounter_team_id",
        "SELECT to_jsonb(t) FROM encounter.team t ORDER BY id",
        "SELECT id,after_json FROM audit_log WHERE action='stats.initial_transfer' ORDER BY id",
    )
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("""UPDATE matches.statistics SET hero_id=:hero,
                value=CASE WHEN name='AllDamageDealt' THEN 1000000000000.0 ELSE value END
                WHERE match_id=:match_hidden AND round=0 AND hero_id IS NOT NULL"""),
                ids,
            )
            candidates = conn.execute(
                sa.text("""SELECT wm.id,u.name,s.value,s.match_id FROM matches.statistics s
                JOIN matches.match m ON m.id=s.match_id
                JOIN encounter.encounter enc ON enc.id=m.encounter_id
                JOIN workspace_member wm ON wm.workspace_id=enc.workspace_id AND wm.player_id=s.user_id
                JOIN players."user" u ON u.id=s.user_id
                WHERE s.round=0 AND s.hero_id=:hero AND s.name='AllDamageDealt'
                AND EXISTS(SELECT 1 FROM matches.statistics q WHERE q.match_id=s.match_id
                  AND q.user_id=s.user_id AND q.hero_id=s.hero_id AND q.round=0
                  AND q.name='HeroTimePlayed' AND q.value>60)
                ORDER BY s.value DESC,s.match_id DESC,wm.id"""),
                ids,
            ).all()
            assert ids["member"] < ids["member_away"]
            assert candidates[:2] == [
                (ids["member"], "P4 Alpha", 1e12, ids["match_hidden"]),
                (ids["member_away"], "P4 Bravo", 1e12, ids["match_hidden"]),
            ]
            assert all(row.value < 1e12 for row in candidates[2:])
        result = upgrade_database(url, "stats01")
        assert result.returncode == 0, result.stdout + result.stderr
        with engine.begin() as conn:
            assert conn.execute(sa.text(best_query), ids).one() == (1e12, "P4 Alpha")
            original_stats01_shape(conn)
            # The old sort left full ties unspecified. Freeze the other legal
            # outcome explicitly instead of depending on PostgreSQL's tie order.
            conn.execute(sa.text("ALTER MATERIALIZED VIEW stats.mv_entity_global_stats RENAME TO old_bound_mv"))
            conn.execute(sa.text("ALTER INDEX stats.uq_mv_entity_global_stats RENAME TO uq_old_bound_mv"))
            patch = sa.literal(json.dumps(resident_metadata)).compile(
                dialect=conn.dialect, compile_kwargs={"literal_binds": True}
            )
            conn.execute(
                sa.text(f"""CREATE MATERIALIZED VIEW stats.mv_entity_global_stats AS
                SELECT discipline,stat_id,entity_id,best_value,avg,
                CASE WHEN entity_id={ids["hero"]} AND stat_id=(SELECT id FROM stats.stat_def
                  WHERE discipline='overwatch' AND code='all_damage_dealt')
                THEN metadata||CAST({patch} AS jsonb) ELSE metadata END AS metadata
                FROM stats.old_bound_mv""")
            )
            original = [conn.execute(sa.text(query)).all() for query in preserved_queries]
            assert conn.execute(sa.text(best_query), ids).one() == (1e12, resident_metadata["username"])
        result = upgrade_database(url, "stats01a")
        if allowed:
            assert result.returncode == 0, result.stdout + result.stderr
        else:
            assert result.returncode != 0
            assert "stats01a refuses unexplained" in result.stdout + result.stderr
        with engine.connect() as conn:
            assert [conn.execute(sa.text(query)).all() for query in preserved_queries] == original
            assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == (
                "stats01a" if allowed else "stats01"
            )
            assert conn.execute(sa.text(best_query), ids).one() == (
                1e12,
                "P4 Alpha" if allowed else resident_metadata["username"],
            )
            histories = (
                conn.execute(sa.text("SELECT after_json FROM audit_log WHERE action='stats.history_upgrade'"))
                .scalars()
                .all()
            )
            assert len(histories) == int(allowed)
            if allowed:
                changes = [
                    change
                    for change in histories[0]["mv_changes"]
                    if change["owner_key"][2] == ids["hero"]
                    and change["before"][-1]["username"] == "P4 Bravo"
                    and change["after"][-1]["username"] == "P4 Alpha"
                ]
                assert len(changes) == 1
                prepare_proof(conn)
                assert mismatches(conn) == []
            else:
                assert (
                    conn.scalar(
                        sa.text("""SELECT count(*) FROM information_schema.columns
                WHERE table_schema='stats' AND column_name IN ('raw_status','source_map_index')""")
                    )
                    == 0
                )
    finally:
        engine.dispose()
