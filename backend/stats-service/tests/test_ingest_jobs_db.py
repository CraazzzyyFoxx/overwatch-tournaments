"""Durable, idempotent canonical jobs against a real migrated PostgreSQL.

Only S3 is substituted. Concurrency uses independent committed sessions; failures are injected at the S3 object, the
COMMIT and the broker, and each must leave no fake acceptance and recover through the outbox/same keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from shared import models
from shared.core.errors import BaseAPIException
from shared.messaging.outbox import publish_pending_outbox_events
from shared.schemas.match_doc import IngestIssue, MatchDoc
from src.services.ingest import jobs
from src.services.match_logs import reaper, retention
from src.services.match_logs.log_records import log_records_service
from tests._ingest_support import (
    DOC,
    body,
    counts,
    make_doc,
    open_environment,
    user_of,
)

PENDING, PROCESSING, DONE, FAILED = (
    models.IngestJobStatus.PENDING,
    models.IngestJobStatus.PROCESSING,
    models.IngestJobStatus.DONE,
    models.IngestJobStatus.FAILED,
)


def run(database, scenario, *args):
    url, seeded = database

    async def go():
        async with open_environment(url, seeded) as env:
            await scenario(env, *args)

    asyncio.run(go())


async def submit(env, doc_or_raw, label="ok"):
    raw = doc_or_raw if isinstance(doc_or_raw, bytes) else body(doc_or_raw)
    async with env.sf() as session:
        return await jobs.submit_document(session, raw=raw, user=user_of(env, label), s3=env.s3)


async def row(env, job_id):
    async with env.sf() as session:
        return await session.get(models.IngestJob, job_id, populate_existing=True)


async def requests(env, job_id):
    async with env.sf() as session:
        return list(
            await session.scalars(
                sa.select(models.EventOutbox).where(
                    models.EventOutbox.event_type == "process_ingest_job",
                    models.EventOutbox.payload_json["ingest_job_id"].as_integer() == job_id,
                )
            )
        )


def test_concurrent_identical_posts_create_one_job_and_one_work_request(ingest_database):
    async def scenario(env):
        raw = body(make_doc())
        results = await asyncio.gather(*(submit(env, raw) for _ in range(8)))
        assert len({job.id for job in results}) == 1
        state = await counts(env)
        assert state["jobs"] == 1
        assert len(await requests(env, results[0].id)) == 1
        stored = await row(env, results[0].id)
        assert stored.raw_ref == f"stats/raw/{env.ws['A']}/{hashlib.sha256(raw).hexdigest()}"
        assert stored.content_hash == hashlib.sha256(raw).hexdigest()
        assert stored.api_key_id == env.keys["ok"]["api_key_id"] and stored.uploader_user_id is not None
        assert env.s3.objects[stored.raw_ref] == raw

    run(ingest_database, scenario)


def test_raw_bytes_are_hashed_before_any_normalisation(ingest_database):
    async def scenario(env):
        compact = body(make_doc(None))
        pretty = json.dumps(json.loads(compact), indent=2).encode()
        a, b = await submit(env, compact), await submit(env, pretty)
        assert a.id != b.id and a.content_hash != b.content_hash
        assert a.content_hash == hashlib.sha256(compact).hexdigest()
        assert (await row(env, a.id)).document_ref == (await row(env, b.id)).document_ref  # same document, one object
        again = await submit(env, compact)
        assert again.id == a.id
        assert (await counts(env))["jobs"] == 2

    run(ingest_database, scenario)


def test_changed_bytes_under_one_external_id_conflict_and_touch_nothing(ingest_database):
    async def scenario(env):
        first = await submit(env, make_doc("same"))
        stored = await row(env, first.id)
        before = await counts(env)
        with pytest.raises(BaseAPIException) as caught:
            await submit(env, make_doc("same", duration_s=61))
        assert (caught.value.status_code, caught.value.detail) == (409, {"code": "idempotency_conflict"})
        after = await row(env, first.id)
        assert (after.raw_ref, after.document_ref, after.content_hash) == (
            stored.raw_ref,
            stored.document_ref,
            stored.content_hash,
        )
        # The refused bytes were written as immutable objects but no job or outbox row points at them.
        assert {k: v for k, v in (await counts(env)).items() if k != "objects"} == {
            k: v for k, v in before.items() if k != "objects"
        }
        assert env.s3.objects[stored.raw_ref] == body(make_doc("same"))
        # Same external id and identical bytes is the same job, in any request.
        assert (await submit(env, make_doc("same"))).id == first.id

    run(ingest_database, scenario)


def test_storage_failures_and_commit_failure_never_fake_acceptance(ingest_database):
    async def scenario(env):
        doc = make_doc("flaky")
        # The seeded identity world already queued its own outbox events; only this test's requests count.
        seeded = await counts(env)
        env.s3.put_ok = False
        for _ in range(2):
            with pytest.raises(jobs.IngestRejected) as caught:
                await submit(env, doc)
            assert caught.value.status_code == 503 and caught.value.headers == {"Retry-After": "1"}
        env.s3.put_ok = True
        env.s3.fail_prefix = "stats/documents/"
        with pytest.raises(jobs.IngestRejected) as caught:
            await submit(env, doc)
        assert caught.value.status_code == 503
        env.s3.fail_prefix = None
        state = await counts(env)
        assert (state["jobs"], state["outbox"]) == (seeded["jobs"], seeded["outbox"])

        # COMMIT fails after both objects exist: nothing committed, the retry reuses the very same keys.
        async with env.sf() as session:

            async def broken():
                raise OperationalError("COMMIT", {}, Exception("connection lost"))

            session.commit = broken
            with pytest.raises(jobs.IngestRejected) as caught:
                await jobs.submit_document(session, raw=body(doc), user=user_of(env, "ok"), s3=env.s3)
            assert caught.value.status_code == 503
        failed = await counts(env)
        assert (failed["jobs"], failed["outbox"]) == (seeded["jobs"], seeded["outbox"]) and len(failed["objects"]) == 2
        job = await submit(env, doc)
        assert job.status == PENDING
        assert (await counts(env))["objects"] == failed["objects"]

    run(ingest_database, scenario)


def test_a_broker_outage_only_delays_the_outbox_request(ingest_database):
    class Broker:
        def __init__(self):
            self.down, self.sent = True, []

        async def publish(self, payload, queue, exchange, **kwargs):
            if self.down:
                raise ConnectionError("broker down")
            self.sent.append((payload, kwargs["routing_key"]))

    async def scenario(env):
        job = await submit(env, make_doc("outage"))
        broker = Broker()
        async with env.sf() as session:
            assert await publish_pending_outbox_events(session, broker, now=datetime.now(UTC)) == 0
        assert (await row(env, job.id)).status == PENDING  # still queued, not failed and not lost
        broker.down = False
        async with env.sf() as session:
            assert await publish_pending_outbox_events(session, broker, now=datetime.now(UTC) + timedelta(minutes=10))
        ((payload, routing_key),) = [item for item in broker.sent if item[0].get("ingest_job_id") == job.id]
        assert routing_key == "stats.ingest.overwatch" and payload["event_type"] == "process_ingest_job"

    run(ingest_database, scenario)


def test_semantic_failure_persists_failed_job_diagnostics_and_never_charges_twice(ingest_database):
    async def scenario(env):
        bad = make_doc("bad", map="no-such-map", facts=[{"team": "alpha", "stat": "no_stat", "value": 1}])
        bad["participants"][0]["role"] = {"dimension": "player_role", "role": "no_role"}
        bad["events"] = [{"t": 1, "type": "no_event", "actor": "a", "entity": "no-hero", "segment": 1}]
        before = await counts(env)
        with pytest.raises(jobs.IngestRejected) as caught:
            await submit(env, bad)
        exc = caught.value
        assert (exc.status_code, exc.code) == (422, "unknown_code")
        job_id = exc.details["ingest_job_id"]
        stored = await row(env, job_id)
        assert stored.status == FAILED and stored.attempts == 0 and stored.finished_at is not None
        assert stored.document_ref in env.s3.objects and stored.hint_tournament_id is None
        assert await requests(env, job_id) == []  # nothing to process

        async with env.sf() as session:
            misses = {
                (m.kind, m.raw_name): (m.occurrences, m.last_ingest_job_id)
                for m in await session.scalars(sa.select(models.CatalogAliasMiss))
            }
        assert misses == {
            ("map", "no-such-map"): (1, job_id),
            ("stat", "no_stat"): (1, job_id),
            ("event", "no_event"): (1, job_id),
            ("character", "no-hero"): (1, job_id),
            ("role", "player_role:no_role"): (1, job_id),
        }
        assert (await counts(env))["audit"] > before["audit"]
        async with env.sf() as session:
            transitions = (
                await session.scalars(
                    sa.select(models.AuditLog.action).where(
                        models.AuditLog.entity_type == "ingest_job", models.AuditLog.entity_id == job_id
                    )
                )
            ).all()
        assert transitions.count("stats.job_transition") == 2  # created pending, then failed in the same transaction

        # The structured error survives the real read serializer.
        async with env.sf() as session:
            read = await jobs.get_ingest_job(session, job_id=job_id, user=user_of(env, "ok"))
        assert read.status == FAILED and read.error.code == "unknown_code"
        assert {issue.kind for issue in read.error.issues if issue.kind} == {
            "map",
            "stat",
            "event",
            "character",
            "role",
        }

        # A repeated identical request returns the failed job: no new misses, attempts or job.
        repeat = await submit(env, bad)
        assert repeat.id == job_id and repeat.status == FAILED and repeat.attempts == 0
        async with env.sf() as session:
            assert await session.scalar(sa.select(sa.func.max(models.CatalogAliasMiss.occurrences))) == 1
        assert (await counts(env))["jobs"] == before["jobs"] + 1

    run(ingest_database, scenario)


def test_error_serialization_round_trips_and_historical_text_is_not_discarded():
    issues = [
        IngestIssue(["facts", i, "stat"], "unknown_stat", "x" * 90, kind="stat", raw_name=f"s{i}") for i in range(2000)
    ]
    encoded = jobs.encode_error("unknown_code", "m" * 900, issues)
    assert len(encoded) <= 16000 and json.loads(encoded)["issues"]
    error = jobs.decode_error(encoded)
    assert error.code == "unknown_code" and len(error.message) == 500 and error.issues[0].raw_name == "s0"
    assert jobs.encode_error("c", "m", issues[:2]) == jobs.encode_error("c", "m", issues[:2])
    assert jobs.decode_error(None) is None
    historical = jobs.decode_error("Processing abandoned after 5 attempts. Retry manually.")
    assert (historical.code, historical.message, historical.issues) == (
        "historical",
        "Processing abandoned after 5 attempts. Retry manually.",
        [],
    )
    assert jobs.decode_error('{"unrelated": true}').code == "historical"


def test_document_envelope_round_trip_and_rejection_of_foreign_shapes(ingest_database):
    async def scenario(env):
        doc = MatchDoc.model_validate(make_doc("env"))
        ref = await jobs.store_document(env.s3, workspace_id=env.ws["A"], doc=doc, producer="canonical")
        stored = env.s3.objects[ref]
        assert set(json.loads(stored)) == {"document", "producer"}
        assert ref == f"stats/documents/{env.ws['A']}/{hashlib.sha256(stored).hexdigest()}.json"
        assert await jobs.store_document(env.s3, workspace_id=env.ws["A"], doc=doc, producer="canonical") == ref
        loaded, producer = await jobs.load_document(env.s3, ref)
        assert loaded == doc and producer == "canonical"
        decoded = await jobs.store_document(env.s3, workspace_id=env.ws["A"], doc=doc, producer="decoded")
        assert decoded != ref and (await jobs.load_document(env.s3, decoded))[1] == "decoded"
        with pytest.raises(ValueError):
            await jobs.store_document(env.s3, workspace_id=env.ws["A"], doc=doc, producer="client")
        with pytest.raises(LookupError):
            await jobs.load_document(env.s3, "stats/documents/absent.json")
        for bad in (
            b"not json",
            json.dumps({"document": json.loads(stored)["document"]}).encode(),
            json.dumps({**json.loads(stored), "producer": "client"}).encode(),
            json.dumps({**json.loads(stored), "extra": 1}).encode(),
            json.dumps({"document": {"protocol": "owt.match/1"}, "producer": "canonical"}).encode(),
        ):
            env.s3.objects["bad"] = bad
            with pytest.raises(ValueError):
                await jobs.load_document(env.s3, "bad")
        # Public submissions are bare documents: the envelope is never accepted as input.
        with pytest.raises(jobs.IngestRejected) as caught:
            await submit(env, json.loads(stored))
        assert caught.value.status_code == 422

    run(ingest_database, scenario)


@pytest.mark.parametrize(
    ("raw", "status", "code"),
    [
        (b"\xff\xfe", 400, "invalid_utf8"),
        (b'{"a": 1} {"b": 2}', 400, "invalid_json"),
        (b'{"a": 1, "a": 2}', 400, "invalid_document"),
        (b"[1, 2]", 400, "invalid_document"),
        (json.dumps({**DOC, "protocol": "owt.match/2"}).encode(), 422, "unsupported_protocol"),
        (json.dumps({**DOC, "workspace_id": 1}).encode(), 422, "document_invalid"),
        (json.dumps({**DOC, "producer": "decoded"}).encode(), 422, "document_invalid"),
        (json.dumps({**DOC, "discipline": "go"}).encode(), 422, "unsupported_discipline"),
    ],
)
def test_structural_rejections_have_no_job_and_no_writes(ingest_database, raw, status, code):
    async def scenario(env):
        before = await counts(env)
        with pytest.raises(jobs.IngestRejected) as caught:
            await submit(env, raw)
        assert (caught.value.status_code, caught.value.code) == (status, code)
        assert "ingest_job_id" not in caught.value.details
        assert await counts(env) == before

    run(ingest_database, scenario)


def test_oversized_document_is_rejected_before_parsing(ingest_database):
    async def scenario(env):
        before = await counts(env)
        with pytest.raises(jobs.IngestRejected) as caught:
            await submit(env, b" " * (25 * 1024 * 1024 + 1))
        assert (caught.value.status_code, caught.value.code) == (413, "match_document_too_large")
        assert await counts(env) == before

    run(ingest_database, scenario)


def test_claim_fencing_survives_reaper_reset_and_budget_reset_to_the_same_attempt_number(ingest_database):
    async def reset_to_pending(env, job_id, *, retry):
        async with env.sf() as session:
            if retry:
                await log_records_service.retry(session, job_id, workspace_id=env.ws["A"])
                return
            job = await session.get(models.IngestJob, job_id, populate_existing=True)
            await log_records_service.transition(session, job, PENDING)
            await session.commit()

    async def scenario(env):
        job_id = (await submit(env, make_doc("fence"))).id
        async with env.sf() as session:
            claim1 = await jobs.claim_job(session, job_id)
        assert claim1.attempts == 1
        async with env.sf() as session:
            assert await jobs.claim_job(session, job_id) is None  # processing: duplicate delivery does nothing

        await reset_to_pending(env, job_id, retry=False)  # reaper
        assert (await row(env, job_id)).started_at == claim1.started_at  # retained across pending
        async with env.sf() as session:
            claim2 = await jobs.claim_job(session, job_id)
        assert claim2.attempts == 2 and claim2.started_at > claim1.started_at

        async with env.sf() as session:
            assert not await jobs.finish_claim(session, claim1, DONE, document_ref="stats/documents/swapped.json")
        current = await row(env, job_id)
        assert current.status == PROCESSING and current.document_ref != "stats/documents/swapped.json"

        async with env.sf() as session:
            assert await jobs.finish_claim(session, claim2, FAILED, error_message="boom")
        await reset_to_pending(env, job_id, retry=True)  # admin retry resets the attempt budget
        reset = await row(env, job_id)
        assert reset.attempts == 0 and reset.started_at == claim2.started_at  # timestamp never cleared
        async with env.sf() as session:
            claim3 = await jobs.claim_job(session, job_id)
        assert claim3.attempts == claim1.attempts == 1 and claim3.started_at > claim2.started_at > claim1.started_at

        # The paused first attempt wakes up with the same attempt number as the live one and is still fenced.
        async with env.sf() as session:
            assert not await jobs.finish_claim(session, claim1, DONE)
        assert (await row(env, job_id)).status == PROCESSING
        async with env.sf() as session:
            assert await jobs.finish_claim(session, claim3, DONE, document_ref="stats/documents/final.json")
        final = await row(env, job_id)
        assert final.status == DONE and final.document_ref == "stats/documents/final.json"
        async with env.sf() as session:
            assert not await jobs.finish_claim(session, claim3, FAILED)  # a finished claim cannot finish twice
            actions = (
                await session.scalars(
                    sa.select(models.AuditLog.action).where(
                        models.AuditLog.entity_type == "ingest_job", models.AuditLog.entity_id == job_id
                    )
                )
            ).all()
        # created, claim1, reaper, claim2, failed, retry, claim3, done -- every transition has job evidence
        assert actions.count("stats.job_transition") == 8

    run(ingest_database, scenario)


def test_reads_bind_only_the_current_evidence_job(ingest_database):
    async def scenario(env):
        first, second = await submit(env, make_doc("one")), await submit(env, make_doc("two"))
        async with env.sf() as session:
            session.add(
                models.StatsMatch(
                    workspace_id=env.ws["A"],
                    discipline="overwatch",
                    encounter_id=env.ids["A"]["encounter"],
                    encounter_game_id=env.ids["A"]["game"],
                    ingest_job_id=second.id,
                    revision=3,
                    played_at=datetime.now(UTC),
                    duration_s=60,
                    map_entity_id=env.ids["map"],
                    map_kind="map",
                )
            )
            for job_id in (first.id, second.id):
                (await session.get(models.IngestJob, job_id)).status = DONE
            await session.commit()
        async with env.sf() as session:
            superseded = await jobs.get_ingest_job(session, job_id=first.id, user=user_of(env, "ok"))
            current = await jobs.get_ingest_job(session, job_id=second.id, user=user_of(env, "ok"))
        assert superseded.status == DONE and superseded.binding is None
        assert (current.binding.encounter_game_id, current.binding.revision) == (env.ids["A"]["game"], 3)
        payload = current.model_dump(mode="json")
        assert not {"raw_ref", "document_ref", "api_key_id"} & payload.keys()

    run(ingest_database, scenario)


def test_retention_keeps_shared_documents_and_deletes_unreferenced_failed_objects(ingest_database, monkeypatch):
    async def scenario(env):
        async def failed(external):
            doc = make_doc(external, map="gone")
            with pytest.raises(jobs.IngestRejected) as caught:
                await submit(env, doc)
            return caught.value.details["ingest_job_id"]

        lone, shared = await failed("lone"), await failed("shared")
        keeper = (await submit(env, make_doc("keeper"))).id
        async with env.sf() as session:
            shared_ref = (await session.get(models.IngestJob, shared)).document_ref
            (await session.get(models.IngestJob, keeper)).document_ref = shared_ref
            await session.commit()
        lone_row, shared_row = await row(env, lone), await row(env, shared)
        monkeypatch.setattr(retention, "acquire_distributed_lock", lambda *a, **k: asyncio.sleep(0, "token"))
        monkeypatch.setattr(retention, "release_distributed_lock", lambda *a, **k: asyncio.sleep(0))
        purged = await retention.purge_expired_failed_logs(
            redis=object(), s3=env.s3, session_factory=env.sf, now=datetime.now(UTC) + timedelta(days=60)
        )
        assert purged == 2
        async with env.sf() as session:
            assert await session.get(models.IngestJob, lone) is None
            assert await session.get(models.IngestJob, shared) is None
            assert await session.get(models.IngestJob, keeper) is not None
        assert lone_row.raw_ref not in env.s3.objects and lone_row.document_ref not in env.s3.objects
        assert shared_row.raw_ref not in env.s3.objects
        assert shared_ref in env.s3.objects  # still referenced by the live keeper job
        assert (await row(env, keeper)).document_ref == shared_ref

    run(ingest_database, scenario)


def test_reaper_requeues_a_stalled_canonical_job_for_selected_disciplines_only(ingest_database):
    async def scenario(env):
        job_id = (await submit(env, make_doc("stalled"))).id
        old = datetime.now(UTC) - timedelta(days=1)
        async with env.sf() as session:
            await session.execute(
                sa.update(models.IngestJob).where(models.IngestJob.id == job_id).values(created_at=old, updated_at=old)
            )
            await session.commit()
        windows = {"pending_after_seconds": 900, "processing_after_seconds": 1800, "max_attempts": 5, "limit": 25}
        now = datetime.now(UTC)
        async with env.sf() as session:
            other, _ = await reaper._claim_stalled(session, now=now, disciplines=["lol"], **windows)
        assert other == [] and len(await requests(env, job_id)) == 1
        async with env.sf() as session:
            selected, exhausted = await reaper._claim_stalled(session, now=now, disciplines=["overwatch"], **windows)
        assert [item.record_id for item in selected] == [job_id] and exhausted == []
        # The reset and its new work request committed together; the original request is still there too.
        assert len(await requests(env, job_id)) == 2
        stored = await row(env, job_id)
        assert stored.status == PENDING and stored.attempts == 0 and stored.started_at is None
        # Not stalled any more: a second sweep does nothing and queues nothing.
        async with env.sf() as session:
            again, _ = await reaper._claim_stalled(session, now=now, **windows)
        assert again == [] and len(await requests(env, job_id)) == 2

    run(ingest_database, scenario)


def test_failed_job_keeps_validated_hints_and_stays_in_scope(ingest_database):
    async def scenario(env):
        hint = {
            "tournament_id": env.ids["A"]["tournament"],
            "encounter_id": env.ids["A"]["encounter"],
            "encounter_game_id": env.ids["A"]["game"],
        }
        with pytest.raises(jobs.IngestRejected) as caught:
            await submit(env, make_doc("hinted", map="nowhere", hint=hint))
        stored = await row(env, caught.value.details["ingest_job_id"])
        assert stored.status == FAILED
        assert (stored.hint_tournament_id, stored.hint_encounter_id, stored.hint_encounter_game_id) == (
            hint["tournament_id"],
            hint["encounter_id"],
            hint["encounter_game_id"],
        )
        # An unresolved hint next to vocabulary misses is never persisted: the failed job carries NULL hints.
        with pytest.raises(jobs.IngestRejected) as caught:
            await submit(env, make_doc("badhint", map="nowhere", hint={"tournament_id": env.ids["B"]["tournament"]}))
        assert caught.value.code == "unknown_code"
        unsafe = await row(env, caught.value.details["ingest_job_id"])
        assert (unsafe.hint_tournament_id, unsafe.hint_encounter_id, unsafe.hint_encounter_game_id) == (
            None,
            None,
            None,
        )

    run(ingest_database, scenario)


def test_canonical_and_raw_jobs_never_share_a_hash_whatever_their_object_keys_look_like(ingest_database):
    async def raw_job(env, sha, *, kind, raw_ref):
        async with env.sf() as session:
            job, created = await jobs._jobs.create_or_get(
                session,
                workspace_id=env.ws["A"],
                discipline="overwatch",
                source_kind=kind,
                external_id=None,
                content_hash=sha,
                filename="x.log",
                raw_ref=raw_ref,
                document_ref=None,
                uploader_user_id=None,
                api_key_id=None,
                hint_tournament_id=None,
                hint_encounter_id=None,
                hint_encounter_game_id=None,
                classify_existing=jobs.provenance_classifier(env.s3),
            )
            await session.commit()
        return job.id, created

    async def scenario(env):
        # Existing raw jobs: an imported-style key layout, and a raw job whose key even looks canonical.
        for external, raw_ref_of in (
            ("imported", lambda sha: f"legacy/{sha[:8]}/odd-layout.bin"),
            ("lookalike", lambda sha: f"stats/raw/{env.ws['A']}/{sha}"),
        ):
            raw = body(make_doc(None, source={"kind": "manual"}, map=f"m-{external}"))
            sha = hashlib.sha256(raw).hexdigest()
            existing, created = await raw_job(env, sha, kind="manual", raw_ref=raw_ref_of(sha))
            assert created
            before = await counts(env)
            with pytest.raises(BaseAPIException) as caught:
                await submit(env, raw)
            assert (caught.value.status_code, caught.value.detail) == (409, "stats_upload_scope_conflict")
            stored = await row(env, existing)
            assert stored.document_ref is None and stored.raw_ref == raw_ref_of(sha)
            assert {k: v for k, v in (await counts(env)).items() if k != "objects"} == {
                k: v for k, v in before.items() if k != "objects"
            }

        # Existing canonical job: a raw upload of the same bytes (any key layout) is refused untouched.
        canonical_raw = body(make_doc(None, source={"kind": "manual"}))
        canonical_sha = hashlib.sha256(canonical_raw).hexdigest()
        canonical = await submit(env, canonical_raw)
        for kind, ref in (("manual", f"logs/{canonical_sha}"), ("upload", "elsewhere/object")):
            with pytest.raises(BaseAPIException) as caught:
                await raw_job(env, canonical_sha, kind=kind, raw_ref=ref)
            assert caught.value.status_code == 409
        assert (await row(env, canonical.id)).document_ref is not None
        assert (await submit(env, canonical_raw)).id == canonical.id  # canonical to canonical is the same job

        # Two raw upload channels with unusual key layouts remain one job.
        sha = hashlib.sha256(b"raw log bytes").hexdigest()
        first, _ = await raw_job(env, sha, kind="upload", raw_ref="a/b/c")
        second, created = await raw_job(env, sha, kind="discord", raw_ref="d/e/f")
        assert second == first and not created

    run(ingest_database, scenario)


def test_object_locks_are_held_before_any_object_is_written(ingest_database):
    async def scenario(env):
        doc = make_doc("locked")
        document_ref, _ = jobs.envelope_for(env.ws["A"], MatchDoc.model_validate(doc), "canonical")
        async with env.sf() as retention_session:
            # The retention sweep holds the envelope's object lock while it decides whether to delete it.
            await jobs.lock_object(retention_session, document_ref)
            task = asyncio.create_task(submit(env, doc))
            await asyncio.sleep(1.0)
            assert not task.done() and env.s3.objects == {}  # nothing was PUT while the lock is held
            await retention_session.commit()
        job = await asyncio.wait_for(task, 30)
        assert job.status == PENDING and document_ref in env.s3.objects

    run(ingest_database, scenario)


def test_canonical_classification_survives_deleting_the_submitting_key(ingest_database):
    async def scenario(env):
        raw = body(make_doc(None, source={"kind": "manual"}))
        first = await submit(env, raw, "ok")
        async with env.sf() as session:
            await session.execute(sa.delete(models.ApiKey).where(models.ApiKey.id == env.keys["ok"]["api_key_id"]))
            await session.commit()
        stored = await row(env, first.id)
        assert stored.api_key_id is None and stored.document_ref is not None  # FK nulled, still canonical
        again = await submit(env, raw, "ok2")  # identical bytes through another valid key
        assert again.id == first.id and again.status == PENDING
        assert (await counts(env))["jobs"] == 1

    run(ingest_database, scenario)


def test_existing_row_is_classified_by_its_envelope_producer_and_a_bad_envelope_is_explicit(ingest_database):
    async def scenario(env):
        raw = body(make_doc(None, source={"kind": "manual"}))
        sha = hashlib.sha256(raw).hexdigest()
        doc = MatchDoc.model_validate(json.loads(raw))
        decoded_ref = await jobs.store_document(env.s3, workspace_id=env.ws["A"], doc=doc, producer="decoded")
        async with env.sf() as session:
            raw_job, _ = await jobs._jobs.create_or_get(
                session,
                workspace_id=env.ws["A"],
                discipline="overwatch",
                source_kind="manual",
                external_id=None,
                content_hash=sha,
                filename="x.log",
                raw_ref=f"logs/{sha}",
                document_ref=decoded_ref,  # a raw job after decode: it has a document, but producer=decoded
                uploader_user_id=None,
                api_key_id=None,
                hint_tournament_id=None,
                hint_encounter_id=None,
                hint_encounter_game_id=None,
            )
            await session.commit()
        with pytest.raises(BaseAPIException) as caught:  # decoded -> raw: canonical submit must not reuse it
            await submit(env, raw)
        assert (caught.value.status_code, caught.value.detail) == (409, "stats_upload_scope_conflict")
        for content in (None, b"{not an envelope"):
            if content is None:
                env.s3.objects.pop(decoded_ref)  # envelope missing
            else:
                env.s3.objects[decoded_ref] = content  # envelope corrupt
            before = await counts(env)
            with pytest.raises(jobs.IngestRejected) as caught:
                await submit(env, raw)
            assert (caught.value.status_code, caught.value.code) == (409, "stored_document_invalid")
            assert {k: v for k, v in (await counts(env)).items() if k != "objects"} == {
                k: v for k, v in before.items() if k != "objects"
            }
        assert (await row(env, raw_job.id)).document_ref == decoded_ref

    run(ingest_database, scenario)
