"""Real PostgreSQL preparation tests on controller-owned disposable P3 clones.

Only the external object-store accessor is replaced. All assertions inspect SQL rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
import sqlalchemy as sa

from scripts import stats01_prepare as prep
from shared.testing.db import MIGRATION_PROOF_SKIP, migration_proofs_enabled
from shared.testing.stats_parity import legacy_database, raw_objects, seed_legacy

RAW = b"timestamp,event,player\r\n0,match_start,Player#1234\r\n"


class ObjectStore:
    def __init__(self, objects):
        self.objects = objects

    async def get_object(self, key):
        return self.objects.get(key)


@pytest.fixture(scope="module")
def legacy_template():
    if not migration_proofs_enabled():
        pytest.skip(MIGRATION_PROOF_SKIP)
    with legacy_database() as url:
        engine = sa.create_engine(url)
        with engine.begin() as conn:
            ids = seed_legacy(conn)
        engine.dispose()
        yield url, ids


@pytest.fixture
def database(legacy_template):
    url, _ = legacy_template
    with legacy_database(template_url=url) as clone:
        engine = sa.create_engine(clone)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def seeded(database, legacy_template):
    with database.connect() as conn, conn.begin() as tx:
        _, ids = legacy_template
        match = (
            conn.execute(
                sa.text("""
            SELECT m.id, m.log_record_id, e.tournament_id, m.encounter_id, e.workspace_id,
                   m.home_team_id, m.away_team_id, m.map_id
            FROM matches.match m JOIN encounter.encounter e ON e.id=m.encounter_id
            WHERE m.id=:id
        """),
                {"id": ids["match"]},
            )
            .mappings()
            .one()
        )
        key = f"logs/{match['tournament_id']}/preparation.csv"
        conn.execute(
            sa.text("UPDATE log_processing.record SET filename='preparation.csv', content_hash=NULL WHERE id=:id"),
            {"id": match["log_record_id"]},
        )
        conn.execute(sa.text("UPDATE matches.match SET log_name='preparation.csv' WHERE id=:id"), {"id": match["id"]})
        yield conn, dict(match), ObjectStore({**raw_objects(ids), key: RAW}), ids
        tx.rollback()


def run(awaitable):
    return asyncio.run(awaitable)


def approval(snapshot, **fields):
    return {
        **fields,
        "snapshot": snapshot,
        "expected": prep.fingerprint(snapshot),
        "evidence": "Reviewed local fixture's original object and identities",
    }


def raw_item(conn, row, store, action="fill_hash", **extra):
    snapshot = run(prep.inspect_raw(conn, store, record_id=row["log_record_id"], match_id=row["id"]))
    return approval(
        snapshot,
        action=action,
        record_id=row["log_record_id"],
        match_id=row["id"],
        tournament_id=row["tournament_id"],
        filename=snapshot["record"]["filename"],
        log_name=snapshot["match"]["log_name"],
        raw_ref=snapshot["raw_ref"],
        content_hash=hashlib.sha256(RAW).hexdigest(),
        **extra,
    )


def test_check_is_read_only_and_hashes_exact_bytes(seeded):
    conn, row, store, _ = seeded
    before = conn.execute(
        sa.text("SELECT to_jsonb(r) FROM log_processing.record r WHERE id=:id"), {"id": row["log_record_id"]}
    ).scalar_one()
    report = run(prep.check(conn, store))
    after = conn.execute(
        sa.text("SELECT to_jsonb(r) FROM log_processing.record r WHERE id=:id"), {"id": row["log_record_id"]}
    ).scalar_one()
    assert before == after
    entry = next(x for x in report["raw"] if x.get("record_id") == row["log_record_id"])
    assert entry["snapshot"]["content_hash"] == hashlib.sha256(RAW).hexdigest()
    assert entry["snapshot"]["content_hash"] != hashlib.sha256(RAW.replace(b"\r\n", b"\n")).hexdigest()


@pytest.mark.parametrize(
    "value,filename,reason",
    [
        (None, "preparation.csv", "missing_raw_object"),
        (b"", "preparation.csv", "empty_raw_object"),
        (b"\xff", "preparation.csv", "unprocessable_raw_object"),
        (RAW, "../bad", "unsafe_raw_key"),
    ],
)
def test_bad_objects_fail_without_writes(seeded, value, filename, reason):
    conn, row, store, _ = seeded
    store.objects[f"logs/{row['tournament_id']}/preparation.csv"] = value
    conn.execute(
        sa.text("UPDATE log_processing.record SET filename=:name WHERE id=:id"),
        {"name": filename, "id": row["log_record_id"]},
    )
    with pytest.raises(prep.PreparationBlocked, match=reason):
        run(prep.inspect_raw(conn, store, record_id=row["log_record_id"]))
    assert (
        conn.execute(
            sa.text("SELECT content_hash FROM log_processing.record WHERE id=:id"), {"id": row["log_record_id"]}
        ).scalar_one()
        is None
    )


def test_hash_conflict_and_size_limit_are_not_repairs(seeded):
    conn, row, store, _ = seeded
    with pytest.raises(prep.PreparationBlocked, match="oversize_raw_object"):
        run(prep.inspect_raw(conn, store, record_id=row["log_record_id"], max_bytes=1))
    conn.execute(
        sa.text("UPDATE log_processing.record SET content_hash=:hash WHERE id=:id"),
        {"hash": "0" * 64, "id": row["log_record_id"]},
    )
    with pytest.raises(prep.PreparationBlocked, match="raw_hash_conflict"):
        run(prep.inspect_raw(conn, store, record_id=row["log_record_id"]))


def test_fill_hash_resume_and_stale_manifest(seeded):
    conn, row, store, _ = seeded
    item = raw_item(conn, row, store)
    run(prep.apply_item(conn, store, "raw", item))
    run(prep.apply_item(conn, store, "raw", item))
    assert (
        conn.execute(
            sa.text("SELECT content_hash FROM log_processing.record WHERE id=:id"), {"id": row["log_record_id"]}
        ).scalar_one()
        == hashlib.sha256(RAW).hexdigest()
    )
    conn.execute(
        sa.text("UPDATE log_processing.record SET attempts=attempts+1 WHERE id=:id"), {"id": row["log_record_id"]}
    )
    with pytest.raises(prep.PreparationBlocked, match="fingerprint_drift"):
        run(prep.apply_item(conn, store, "raw", item))


def test_link_reuses_record_and_never_rewrites_log_name(seeded):
    conn, row, store, _ = seeded
    conn.execute(
        sa.text("UPDATE log_processing.record SET content_hash=:hash WHERE id=:id"),
        {"hash": hashlib.sha256(RAW).hexdigest(), "id": row["log_record_id"]},
    )
    conn.execute(sa.text("UPDATE matches.match SET log_record_id=NULL WHERE id=:id"), {"id": row["id"]})
    snapshot = run(prep.inspect_raw(conn, store, match_id=row["id"]))
    item = approval(
        snapshot,
        action="link_match",
        match_id=row["id"],
        record_id=None,
        tournament_id=row["tournament_id"],
        filename=None,
        log_name="preparation.csv",
        raw_ref=snapshot["raw_ref"],
        content_hash=hashlib.sha256(RAW).hexdigest(),
        reuse_record_id=row["log_record_id"],
    )
    run(prep.apply_item(conn, store, "raw", item))
    run(prep.apply_item(conn, store, "raw", item))
    assert conn.execute(
        sa.text("SELECT log_record_id,log_name FROM matches.match WHERE id=:id"), {"id": row["id"]}
    ).one() == (row["log_record_id"], "preparation.csv")


def creation_item(conn, row, store):
    conn.execute(
        sa.text("UPDATE matches.match SET log_record_id=NULL, log_name='new.csv' WHERE id=:id"), {"id": row["id"]}
    )
    key = f"logs/{row['tournament_id']}/new.csv"
    store.objects[key] = RAW
    snapshot = run(prep.inspect_raw(conn, store, match_id=row["id"]))
    return approval(
        snapshot,
        action="link_match",
        match_id=row["id"],
        record_id=None,
        tournament_id=row["tournament_id"],
        filename=None,
        log_name="new.csv",
        raw_ref=key,
        content_hash=hashlib.sha256(RAW).hexdigest(),
        create=True,
    )


def test_record_creation_and_link_roll_back_together(seeded):
    conn, row, store, _ = seeded
    item = creation_item(conn, row, store)
    # A real database trigger rejects the link after the record INSERT.
    conn.exec_driver_sql("""CREATE FUNCTION pg_temp.reject_preparation_link() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'fixture rejects link'; END $$""")
    conn.exec_driver_sql(
        "CREATE TRIGGER preparation_reject BEFORE UPDATE OF log_record_id ON matches.match FOR EACH ROW EXECUTE FUNCTION pg_temp.reject_preparation_link()"
    )
    with pytest.raises(sa.exc.DBAPIError), conn.begin_nested():
        run(prep.apply_item(conn, store, "raw", item))
    assert (
        conn.execute(
            sa.text("SELECT count(*) FROM log_processing.record WHERE tournament_id=:id AND filename='new.csv'"),
            {"id": row["tournament_id"]},
        ).scalar_one()
        == 0
    )
    assert (
        conn.execute(sa.text("SELECT log_record_id FROM matches.match WHERE id=:id"), {"id": row["id"]}).scalar_one()
        is None
    )


def test_manifest_digest_is_operator_supplied(tmp_path):
    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps({"version": 1, "raw": [], "games": [], "members": []}), encoding="utf-8")
    with pytest.raises(prep.PreparationBlocked, match="manifest_sha256_mismatch"):
        prep.load_manifest(path, "0" * 64)
    assert prep.load_manifest(path, hashlib.sha256(path.read_bytes()).hexdigest())["version"] == 1


def test_ambiguous_candidates_cannot_be_chosen(seeded):
    conn, row, store, _ = seeded
    conn.execute(sa.text("UPDATE matches.match SET log_record_id=NULL WHERE id=:id"), {"id": row["id"]})
    conn.execute(
        sa.text("UPDATE log_processing.record SET content_hash=:hash WHERE id=:id"),
        {"id": row["log_record_id"], "hash": hashlib.sha256(RAW).hexdigest()},
    )
    conn.execute(
        sa.text("""INSERT INTO log_processing.record (tournament_id,filename,status,source,content_hash)
        VALUES (:tid,:name,'done','manual',:hash)"""),
        {
            "tid": row["tournament_id"],
            "name": f"logs/{row['tournament_id']}/preparation.csv",
            "hash": hashlib.sha256(RAW).hexdigest(),
        },
    )
    snapshot = run(prep.inspect_raw(conn, store, match_id=row["id"]))
    item = approval(
        snapshot,
        action="link_match",
        match_id=row["id"],
        record_id=None,
        tournament_id=row["tournament_id"],
        filename=None,
        log_name="preparation.csv",
        raw_ref=snapshot["raw_ref"],
        content_hash=hashlib.sha256(RAW).hexdigest(),
        reuse_record_id=row["log_record_id"],
    )
    with pytest.raises(prep.PreparationBlocked, match="ambiguous_raw_candidates"):
        run(prep.apply_item(conn, store, "raw", item))
    assert (
        conn.execute(sa.text("SELECT log_record_id FROM matches.match WHERE id=:id"), {"id": row["id"]}).scalar_one()
        is None
    )


def test_concurrent_creation_commits_one_record(database, legacy_template):
    _, ids = legacy_template
    store = ObjectStore(raw_objects(ids))
    row = {"id": ids["match"], "tournament_id": ids["tournament"]}
    with database.begin() as conn:
        item = creation_item(conn, row, store)
    barrier = Barrier(2)

    def attempt():
        with database.begin() as conn:
            barrier.wait(timeout=10)
            return run(prep.apply_item(conn, store, "raw", item))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    with database.connect() as conn:
        records = conn.execute(
            sa.text(
                "SELECT id,content_hash,status::text,source::text,uploader_id,started_at,finished_at FROM log_processing.record WHERE tournament_id=:id AND filename='new.csv'"
            ),
            {"id": ids["tournament"]},
        ).all()
        assert len(records) == 1
        assert tuple(records[0][1:]) == (hashlib.sha256(RAW).hexdigest(), "done", "manual", None, None, None)
        assert (
            conn.execute(
                sa.text("SELECT log_record_id FROM matches.match WHERE id=:id"), {"id": ids["match"]}
            ).scalar_one()
            == records[0][0]
        )
        assert all(result["after"]["match"]["log_record_id"] == records[0][0] for result in results)


def member_item(conn, ids, *, create):
    snapshot = prep.inspect_member(conn, ids["player_no_member"], ids["workspace"])
    decision = {"create": {"removed": True}} if create else {"member_id": ids["member_other"]}
    return approval(
        snapshot,
        player_id=ids["player_no_member"],
        workspace_id=ids["workspace"],
        source_ids=snapshot["sources"],
        **decision,
    )


def reference_missing_player(conn, ids):
    conn.execute(
        sa.text("""UPDATE matches.event SET user_id=:player WHERE match_id=:match
        AND user_id=:previous"""),
        {"player": ids["player_no_member"], "match": ids["match"], "previous": ids["player_event_only"]},
    )


def authorization_rows(conn):
    tables = conn.execute(
        sa.text("""SELECT table_schema,table_name FROM information_schema.tables
        WHERE table_schema IN ('auth','rbac') AND table_type='BASE TABLE' ORDER BY 1,2""")
    ).all()
    quote = conn.dialect.identifier_preparer.quote_identifier
    return {
        (schema, table): conn.exec_driver_sql(
            f"SELECT md5(to_jsonb(t)::text) FROM {quote(schema)}.{quote(table)} t ORDER BY 1"
        )
        .scalars()
        .all()
        for schema, table in tables
    }


def test_historical_member_creation_grants_no_access_and_resumes(seeded):
    conn, _, store, ids = seeded
    reference_missing_player(conn, ids)
    before = authorization_rows(conn)
    item = member_item(conn, ids, create=True)
    assert item["source_ids"], "shared fixture must include event-only participation on match"
    run(prep.apply_item(conn, store, "members", item))
    run(prep.apply_item(conn, store, "members", item))
    member = conn.execute(
        sa.text(
            "SELECT player_id,workspace_id,removed_at FROM workspace_member WHERE player_id=:pid AND workspace_id=:wid"
        ),
        {"pid": ids["player_no_member"], "wid": ids["workspace"]},
    ).one()
    assert member[:2] == (ids["player_no_member"], ids["workspace"])
    assert member[2] is not None
    assert authorization_rows(conn) == before


def test_foreign_member_is_not_identity_evidence(seeded):
    conn, _, store, ids = seeded
    reference_missing_player(conn, ids)
    item = member_item(conn, ids, create=False)
    with pytest.raises(prep.PreparationBlocked, match="foreign_or_conflicting_member"):
        run(prep.apply_item(conn, store, "members", item))
    assert (
        conn.execute(
            sa.text("SELECT count(*) FROM workspace_member WHERE player_id=:pid AND workspace_id=:wid"),
            {"pid": ids["player_no_member"], "wid": ids["workspace"]},
        ).scalar_one()
        == 0
    )


def test_existing_removed_member_remains_removed(seeded):
    conn, _, store, ids = seeded
    snapshot = prep.inspect_member(conn, ids["player_removed"], ids["workspace"])
    item = approval(
        snapshot,
        player_id=ids["player_removed"],
        workspace_id=ids["workspace"],
        source_ids=snapshot["sources"],
        member_id=ids["member_removed"],
    )
    result = run(prep.apply_item(conn, store, "members", item))
    assert result["before"] == result["after"]
    assert result["after"]["members"][0]["removed_at"] is not None


def game_item(conn, ids, **decision):
    return approval(
        prep.inspect_game(conn, ids["match"]),
        match_id=ids["match"],
        encounter_id=ids["encounter"],
        map_id=ids["map"],
        encounter_team_ids=[ids["encounter_team_home"], ids["encounter_team_away"]],
        **decision,
    )


def test_scheduled_historical_game_preserves_confirmed_parent(seeded):
    conn, _, store, ids = seeded
    conn.execute(
        sa.text("""UPDATE encounter.encounter SET status='COMPLETED',result_status='confirmed',
        result_source='admin',result_version=7,confirmed_at=now() WHERE id=:id"""),
        {"id": ids["encounter"]},
    )
    item = game_item(conn, ids, position=9, create={"state": "planned"})
    result = run(prep.apply_item(conn, store, "games", item))
    repeated = run(prep.apply_item(conn, store, "games", item))
    assert result["before"]["encounter"] == result["after"]["encounter"]
    assert result["before"]["teams"] == result["after"]["teams"]
    assert repeated["before"] == repeated["after"]
    game = conn.execute(
        sa.text(
            "SELECT id,state::text,result_source,confirmed_at,result_version FROM encounter.game WHERE encounter_id=:id AND position=9"
        ),
        {"id": ids["encounter"]},
    ).one()
    assert tuple(game[1:]) == ("planned", None, None, 0)
    assert conn.execute(
        sa.text("SELECT score,placement FROM encounter.game_team WHERE game_id=:id ORDER BY encounter_team_id"),
        {"id": game[0]},
    ).all() == [(None, None), (None, None)]
    assert (
        conn.execute(sa.text("SELECT map_index FROM matches.match WHERE id=:id"), {"id": ids["match"]}).scalar_one()
        == 9
    )


def test_foreign_game_and_stale_results_are_refused(seeded):
    conn, _, store, ids = seeded
    foreign = game_item(conn, ids, position=1, game_id=ids["game_other"])
    with pytest.raises(prep.PreparationBlocked, match="foreign_or_missing_game"):
        run(prep.apply_item(conn, store, "games", foreign))
    item = game_item(conn, ids, position=1, game_id=ids["game"])
    conn.execute(
        sa.text("UPDATE encounter.encounter SET result_version=result_version+1 WHERE id=:id"), {"id": ids["encounter"]}
    )
    with pytest.raises(prep.PreparationBlocked, match="fingerprint_drift"):
        run(prep.apply_item(conn, store, "games", item))


def test_storage_access_failure_is_distinct_from_missing(seeded):
    conn, row, _, _ = seeded

    class DeniedStore:
        async def get_object(self, key):
            raise PermissionError("secret credential must not escape")

    with pytest.raises(prep.PreparationBlocked, match="storage_access_unavailable") as exc:
        run(prep.inspect_raw(conn, DeniedStore(), record_id=row["log_record_id"]))
    assert "secret credential" not in str(exc.value)


def test_default_inventory_executes_in_database_enforced_read_only_transaction(database, legacy_template):
    _, ids = legacy_template
    with database.connect() as conn, conn.begin():
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        report = run(prep.check(conn, ObjectStore(raw_objects(ids))))
        assert report["blockers"] == []
        assert (
            conn.execute(
                sa.text("SELECT log_record_id FROM matches.match WHERE id=:id"), {"id": ids["match_no_raw"]}
            ).scalar_one()
            is None
        )


def test_removed_preparation_member_is_excluded_from_real_token_memberships(database, legacy_template):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from shared.models.identity.auth_user import AuthUser
    from shared.repository.workspace import WorkspaceMemberRepository

    _, ids = legacy_template
    with database.begin() as conn:
        reference_missing_player(conn, ids)
        assert (
            conn.execute(
                sa.text('SELECT auth_user_id FROM players."user" WHERE id=:id'), {"id": ids["player_no_member"]}
            ).scalar_one()
            == ids["auth_user_no_member"]
        )
        run(prep.apply_item(conn, ObjectStore(raw_objects(ids)), "members", member_item(conn, ids, create=True)))
        # The live ORM selects ``observed_only`` (ingest01); this clone is P3-shaped, so give it that one column.
        conn.execute(sa.text("ALTER TABLE workspace_member ADD COLUMN observed_only BOOLEAN NOT NULL DEFAULT false"))

    async def memberships():
        engine = create_async_engine(database.url.set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine) as session:
                return await WorkspaceMemberRepository().list_memberships_for_auth_user(
                    session, ids["auth_user_no_member"]
                )
        finally:
            await engine.dispose()

    actual = run(memberships())
    assert ids["workspace"] not in {wid for wid, _ in actual}
    principal = AuthUser(id=ids["auth_user_no_member"], is_superuser=False)
    principal.set_rbac_cache([], [], workspaces=[{"workspace_id": wid, "slug": slug} for wid, slug in actual])
    assert not principal.is_workspace_member(ids["workspace"])
    # Positive control: the real query sees this SAME linked identity when active.
    with database.begin() as conn:
        conn.execute(
            sa.text("UPDATE workspace_member SET removed_at=NULL WHERE workspace_id=:wid AND player_id=:pid"),
            {"wid": ids["workspace"], "pid": ids["player_no_member"]},
        )
    assert ids["workspace"] in {wid for wid, _ in run(memberships())}


def test_foreign_raw_record_never_rebinds_match(seeded):
    conn, row, store, ids = seeded
    with pytest.raises(prep.PreparationBlocked, match="foreign_raw_owner"):
        run(prep.inspect_raw(conn, store, record_id=ids["record_other"], match_id=row["id"]))
    assert (
        conn.execute(sa.text("SELECT log_record_id FROM matches.match WHERE id=:id"), {"id": row["id"]}).scalar_one()
        == ids["record"]
    )


def test_second_match_cannot_claim_reviewed_game(seeded):
    conn, _, store, ids = seeded
    conn.execute(
        sa.text("UPDATE matches.match SET map_id=:map,map_index=1 WHERE id=:id"),
        {"map": ids["map"], "id": ids["match_reversed"]},
    )
    item = game_item(conn, ids, position=1, game_id=ids["game"])
    before = conn.execute(
        sa.text("SELECT map_index FROM matches.match WHERE id=:id"), {"id": ids["match"]}
    ).scalar_one()
    with pytest.raises(prep.PreparationBlocked, match="duplicate_game_claim"):
        run(prep.apply_item(conn, store, "games", item))
    assert (
        conn.execute(sa.text("SELECT map_index FROM matches.match WHERE id=:id"), {"id": ids["match"]}).scalar_one()
        == before
    )


def test_changed_object_refuses_reviewed_apply_without_filling_hash(seeded):
    conn, row, store, _ = seeded
    item = raw_item(conn, row, store)
    store.objects[item["raw_ref"]] = RAW + b"1,changed,other\\n"
    with pytest.raises(prep.PreparationBlocked, match="raw_manifest_identity_conflict"):
        run(prep.apply_item(conn, store, "raw", item))
    assert (
        conn.execute(
            sa.text("SELECT content_hash FROM log_processing.record WHERE id=:id"), {"id": row["log_record_id"]}
        ).scalar_one()
        is None
    )


def test_apply_requires_reviewed_manifest_and_independent_digest(capsys):
    with pytest.raises(SystemExit) as exc:
        prep.main(["--apply"])
    assert exc.value.code == 2
    assert "--manifest-sha256" in capsys.readouterr().err


def test_record_verification_preserves_existing_bytes_and_reference_prefix(seeded):
    conn, row, store, _ = seeded
    digest = hashlib.sha256(RAW).hexdigest()
    conn.execute(
        sa.text("UPDATE log_processing.record SET filename='logs/preparation.csv',content_hash=:hash WHERE id=:id"),
        {"hash": digest, "id": row["log_record_id"]},
    )
    item = raw_item(conn, row, store, action="verify_record")
    result = run(prep.apply_item(conn, store, "raw", item))
    assert result["before"] == result["after"]
    assert result["after"]["record"]["filename"] == "logs/preparation.csv"
    assert result["after"]["raw_ref"] == f"logs/{row['tournament_id']}/preparation.csv"
    assert result["official_before"] == result["official_after"]


def native_run(url, action):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    async def execute():
        engine = create_async_engine(sa.make_url(url).set(drivername="postgresql+asyncpg"), poolclass=sa.pool.NullPool)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
                return await action(session)
        finally:
            await engine.dispose()

    return run(execute())


def test_native_verification_is_audited_lossless_and_repeatable(stats01_database, tmp_path):
    from scripts import stats01_reconcile as reconcile

    url, ids = stats01_database
    engine = sa.create_engine(url)
    revision = reconcile.revision_module()
    receipt = tmp_path / "native-before"
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE log_processing.record SET content_hash=NULL WHERE id=:record"), ids)
            conn.execute(sa.text("UPDATE stats.ingest_job SET content_hash=NULL WHERE id=:record"), ids)
        with reconcile.readonly_snapshot(engine, revision) as conn:
            reconcile.capture_receipt(conn, receipt, revision)
        with engine.connect() as conn:
            before = conn.execute(sa.text("SELECT to_jsonb(j) FROM stats.ingest_job j ORDER BY id")).scalars().all()
            facts = conn.scalar(sa.text("SELECT count(*) FROM stats.fact"))
            official = (
                conn.execute(
                    sa.text("SELECT to_jsonb(g) FROM encounter.game_team g ORDER BY game_id,encounter_team_id")
                )
                .scalars()
                .all()
            )
        store = ObjectStore(raw_objects(ids))
        report = native_run(url, lambda session: prep.verify_native_raw(session, store))
        assert report["blockers"] == []
        assert next(item for item in report["raw"] if item["job_id"] == ids["record"])["raw_status"] == "available"
        with engine.connect() as conn:
            assert (
                conn.execute(sa.text("SELECT to_jsonb(j) FROM stats.ingest_job j ORDER BY id")).scalars().all()
                == before
            )
        report["review"] = "Reviewed actual isolated native fixture bytes and target"
        first = native_run(url, lambda session: prep.apply_native_raw(session, store, report, manifest_sha256="a" * 64))
        second = native_run(
            url, lambda session: prep.apply_native_raw(session, store, report, manifest_sha256="a" * 64)
        )
        assert first["applied"] and second["applied"] == []
        with engine.connect() as conn:
            after = conn.execute(sa.text("SELECT to_jsonb(j) FROM stats.ingest_job j ORDER BY id")).scalars().all()
            for old, new in zip(before, after, strict=True):
                assert {k: v for k, v in old.items() if k not in {"raw_status", "content_hash"}} == {
                    k: v for k, v in new.items() if k not in {"raw_status", "content_hash"}
                }
                if old["content_hash"] is not None:
                    assert new["content_hash"] == old["content_hash"]
            assert conn.scalar(sa.text("SELECT count(*) FROM stats.fact")) == facts
            assert (
                conn.execute(
                    sa.text("SELECT to_jsonb(g) FROM encounter.game_team g ORDER BY game_id,encounter_team_id")
                )
                .scalars()
                .all()
                == official
            )
            assert conn.scalar(sa.text("SELECT count(*) FROM audit_log WHERE action='stats.raw_verification'")) == len(
                first["applied"]
            )
        with reconcile.readonly_snapshot(engine, revision, receipt_dir=receipt) as conn:
            assert reconcile.check_receipt(conn, receipt, revision)["exit_code"] == 2
    finally:
        engine.dispose()


def test_native_missing_conflict_and_shared_sources_never_invent_hashes(stats01_database):
    url, ids = stats01_database
    engine = sa.create_engine(url)
    store = ObjectStore(raw_objects(ids))
    try:
        with engine.begin() as conn:
            key = conn.scalar(sa.text("SELECT raw_ref FROM stats.ingest_job WHERE id=:record"), ids)
            conn.execute(
                sa.text("UPDATE stats.ingest_job SET content_hash=:hash WHERE id=:record"), {**ids, "hash": "0" * 64}
            )
        report = native_run(url, lambda session: prep.verify_native_raw(session, store))
        item = next(item for item in report["raw"] if item["job_id"] == ids["record"])
        assert (
            item["raw_status"] == "conflict"
            and item["inspected_sha256"] == hashlib.sha256(store.objects[key]).hexdigest()
        )
        report["review"] = "Known immutable source hash differs from inspected bytes"
        native_run(url, lambda session: prep.apply_native_raw(session, store, report, manifest_sha256="b" * 64))
        with engine.connect() as conn:
            assert conn.execute(
                sa.text("SELECT raw_status,content_hash FROM stats.ingest_job WHERE id=:record"), ids
            ).one() == ("conflict", "0" * 64)
        store.objects.pop(key)
        missing = native_run(url, lambda session: prep.verify_native_raw(session, store))
        item = next(item for item in missing["raw"] if item["job_id"] == ids["record"])
        assert item["raw_status"] == "missing" and item["inspected_sha256"] is None
        missing["review"] = "Actual object store reports not found, not access denied"
        native_run(url, lambda session: prep.apply_native_raw(session, store, missing, manifest_sha256="b" * 64))
        with engine.connect() as conn:
            assert conn.execute(
                sa.text("SELECT raw_status,content_hash FROM stats.ingest_job WHERE id=:record"), ids
            ).one() == ("missing", "0" * 64)
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE stats.match SET ingest_job_id=:record WHERE id=:match_no_raw"), ids)
        store.objects[key] = RAW
        shared = native_run(url, lambda session: prep.verify_native_raw(session, store))
        assert next(item for item in shared["raw"] if item["job_id"] == ids["record"])["raw_status"] == "unverified"
        shared["review"] = "Shared observations have no unique original parse provenance"
        native_run(url, lambda session: prep.apply_native_raw(session, store, shared, manifest_sha256="b" * 64))
        with engine.connect() as conn:
            assert conn.execute(
                sa.text("SELECT raw_status,content_hash FROM stats.ingest_job WHERE id=:record"), ids
            ).one() == ("unverified", "0" * 64)
    finally:
        engine.dispose()


def test_native_access_errors_are_not_missing_evidence(stats01_database):
    url, _ = stats01_database

    class Denied:
        async def get_object(self, key):
            raise PermissionError("not an object absence")

    report = native_run(url, lambda session: prep.verify_native_raw(session, Denied()))
    assert report["blockers"] and report["raw"] == []
    assert {row["reason"] for row in report["blockers"]} == {"storage_access_unavailable"}
    report["review"] = "Cannot approve failed inspection"
    with pytest.raises(prep.PreparationBlocked, match="incomplete_native_verification"):
        native_run(url, lambda session: prep.apply_native_raw(session, Denied(), report, manifest_sha256="c" * 64))


@pytest.mark.parametrize(
    "mutation",
    (
        "UPDATE stats.ingest_job SET attempts=attempts+1 WHERE id=:record",
        "UPDATE stats.match SET revision=revision+1 WHERE id=:match",
    ),
)
def test_native_apply_rejects_changed_target_without_partial_classification(stats01_database, mutation):
    url, ids = stats01_database
    store = ObjectStore(raw_objects(ids))
    report = native_run(url, lambda session: prep.verify_native_raw(session, store))
    report["review"] = "Reviewed before target drift"
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(mutation), ids)
        with pytest.raises(prep.PreparationBlocked, match="native_target_drift"):
            native_run(url, lambda session: prep.apply_native_raw(session, store, report, manifest_sha256="d" * 64))
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT count(*) FROM audit_log WHERE action='stats.raw_verification'")) == 0
            assert conn.scalar(sa.text("SELECT count(*) FROM stats.ingest_job WHERE raw_status<>'unverified'")) == 0
    finally:
        engine.dispose()


def test_native_inventory_requires_exact_target_and_signed_bytes(stats01_database, tmp_path):
    url, ids = stats01_database
    report = native_run(url, lambda session: prep.verify_native_raw(session, ObjectStore(raw_objects(ids))))
    inventory = {"format": prep.NATIVE_INVENTORY, "target": report["target"], "objects": report["objects"]}
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory), encoding="utf-8")
    with pytest.raises(prep.PreparationBlocked, match="manifest_sha256_mismatch"):
        prep.load_signed_json(path, "0" * 64)
    loaded = prep.load_signed_json(path, hashlib.sha256(path.read_bytes()).hexdigest())
    accepted = native_run(url, lambda session: prep.verify_native_raw(session, None, inventory=loaded))
    assert [item["raw_status"] for item in accepted["raw"]] == [item["raw_status"] for item in report["raw"]]
    loaded["target"] = {**loaded["target"], "database_name": "a-different-dump"}
    with pytest.raises(prep.PreparationBlocked, match="native_input_target_mismatch"):
        native_run(url, lambda session: prep.verify_native_raw(session, None, inventory=loaded))


def test_native_changed_bytes_roll_back_the_whole_reviewed_application(stats01_database):
    url, ids = stats01_database
    store = ObjectStore(raw_objects(ids))
    report = native_run(url, lambda session: prep.verify_native_raw(session, store))
    report["review"] = "Exact original bytes reviewed"
    last = report["raw"][-1]["snapshot"]["job"]["raw_ref"]
    store.objects[last] += b"\nchanged after review"
    with pytest.raises(prep.PreparationBlocked, match="native_inspection_drift"):
        native_run(url, lambda session: prep.apply_native_raw(session, store, report, manifest_sha256="e" * 64))
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT count(*) FROM audit_log WHERE action='stats.raw_verification'")) == 0
            assert conn.scalar(sa.text("SELECT count(*) FROM stats.ingest_job WHERE raw_status<>'unverified'")) == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "flags",
    (
        ["--apply-native-raw"],
        ["--verify-native-raw", "--inventory", "unchecked.json"],
        ["--check", "--source-evidence", "unchecked.json", "--source-evidence-sha256", "0" * 64],
    ),
)
def test_native_cli_refuses_unsigned_inputs_before_database_access(flags):
    with pytest.raises(SystemExit) as exc:
        prep.main(flags)
    assert exc.value.code == 2


def test_legacy_inventory_does_not_require_raw_recovery_or_new_official_games(seeded):
    conn, _, _, ids = seeded
    conn.execute(sa.text("UPDATE encounter.game SET state='cancelled' WHERE encounter_id=:encounter"), ids)
    report = run(prep.check(conn, ObjectStore({})))
    assert report["blockers"] == []
    assert {"missing_raw_object", "unresolved_game"} <= {row["reason"] for row in report["warnings"]}
