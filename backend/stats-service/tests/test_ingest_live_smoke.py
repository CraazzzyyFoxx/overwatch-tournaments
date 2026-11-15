"""Opt-in live smoke of the whole P5 ingest path: real processes, real brokers, real database, real HTTP.

Skipped unless ``RUN_P5_LIVE_SMOKE=1``. The recipe (throwaway RabbitMQ/Redis/S3 containers and the ``P5_SMOKE_*``
variables) is in ``docs/releases/2026-10-15-multi-game-p5-ingest.md``. ``live_smoke_support.LiveStack`` owns a scratch
database, vhost, bucket and Redis database and drops them afterwards; the processes under test are the real stats
``serve_rpc`` and ``serve_worker`` (one per discipline), identity ``serve``, tournament ``serve`` (outbox drain and the
evidence consumer) and the built Go gateway. Requests are raw canonical JSON over HTTP with real API keys minted by
``ApiKeyService.create``; outcomes are asserted on native SQL rows, the outbox and the encounter journal, not on HTTP
success. The tests share one stack and run in file order.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.messaging.config import (
    MATCH_INGESTED_TOURNAMENT_DLQ,
    ingest_dlq,
    ingest_queue,
    ingest_replay_dlq,
    ingest_replay_queue,
)
from shared.schemas.events import AchievementEvaluateEvent, ProcessIngestJobEvent
from tests.ingest_seed import add_game, shuffled
from tests.live_smoke_support import (
    JSON_HEADERS,
    TERMINAL,
    Live,
    LiveStack,
    Response,
    bring_up,
    canonical,
    err,
    free_port,
    http,
    wait_until,
)
from tests.live_smoke_world import async_session_factory, document, with_unknown_identities
from tests.test_ow_decoder_reference_capture import DIRECTORY, observe

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_P5_LIVE_SMOKE") != "1", reason="live smoke: set RUN_P5_LIVE_SMOKE=1"
)


@pytest.fixture(scope="module")
def live():
    stack = LiveStack(Path(os.environ["P5_SMOKE_EVIDENCE_DIR"]) if os.environ.get("P5_SMOKE_EVIDENCE_DIR") else None)
    try:
        yield bring_up(stack)
    finally:
        path = stack.close()
        print(f"\nP5 live smoke evidence: {path}")


# =====================================================================================================================


def test_each_process_serves_only_its_own_work(live: Live) -> None:
    stack = live.stack
    assert stack.consumers(ingest_queue("overwatch").name) == 1
    assert stack.consumers(ingest_queue("lol").name) == 1
    assert stack.consumers(ingest_replay_queue("overwatch").name) == 1
    assert stack.consumers(ingest_replay_queue("lol").name) == 1
    for slug in ("overwatch", "lol"):
        assert stack.queue(ingest_dlq(slug).name) is not None
        assert stack.queue(ingest_replay_dlq(slug).name) is not None
    # RPC handlers live in one process only: a single consumer, owned by serve_rpc (the workers hold none).
    assert stack.consumers("rpc.stats.ingest.submit") == 1
    assert stack.health("worker_overwatch")[0] == 200 and stack.health("worker_lol")[0] == 200
    # P3 per-discipline grid defaults: each discipline resolves its own default and effective payload.
    off, on = live.grids["OFF"], live.grids["ON"]
    assert set(off["default"]) == {"overwatch", "lol"} and set(on["default"]) == {"overwatch"}
    assert len({*off["default"].values(), *on["default"].values()}) == 3
    assert off["effective"]["overwatch"]["tier_numbers"] == [4] and off["effective"]["lol"]["tier_numbers"] == [9]
    assert [off["effective"][code]["id"] for code in ("overwatch", "lol")] == [
        off["default"]["overwatch"],
        off["default"]["lol"],
    ]
    for case in live.cases.values():
        row = live.q(
            "SELECT t.discipline, g.discipline FROM tournament.tournament t "
            "JOIN public.division_grid_version v ON v.id=t.division_grid_version_id "
            "JOIN public.division_grid g ON g.id=v.grid_id WHERE t.id=%s",
            case.tournament_id,
        )
        assert row and row[0][0] == row[0][1] == case.discipline


def test_refused_requests_create_nothing(live: Live) -> None:
    before = live.baseline()
    main = live.cases["main"]
    doc = canonical(document(main, "refused-ext"))
    assert live.post(None, doc).status == 401
    assert live.post("off_revoked", doc).status == 401
    unknown = http(
        "POST",
        f"{live.stack.gateway}/api/v1/stats/matches",
        body=doc,
        headers={**JSON_HEADERS, "Authorization": "Bearer owt_sk_not_a_key"},
    )
    assert unknown.status == 401
    scope = live.post("off_no_scope", doc)
    assert scope.status == 403 and err(scope) == "scope_required"
    session = http(
        "POST",
        f"{live.stack.gateway}/api/v1/stats/matches",
        body=doc,
        headers={**JSON_HEADERS, "Authorization": f"Bearer {live.admin_token()}"},
    )
    assert session.status == 403 and err(session) == "api_key_required"
    assert live.post("off_ok", doc, content_type="text/plain").status == 415
    malformed = live.post("off_ok", b'{"protocol": "owt.match/1", ')
    assert malformed.status == 400 and err(malformed) == "invalid_json"
    duplicate = live.post("off_ok", b'{"protocol":"owt.match/1","protocol":"owt.match/1"}')
    assert duplicate.status == 400 and err(duplicate) == "invalid_document"
    protocol = live.post("off_ok", canonical({**document(main, "refused-ext"), "protocol": "owt.match/2"}))
    assert protocol.status == 422 and err(protocol) == "unsupported_protocol"
    unsupported = live.post("off_ok", canonical({**document(main, "refused-ext"), "discipline": "chess"}))
    assert unsupported.status == 422
    # Body cap: declared length is refused before the body is read; an undeclared (chunked) stream is cut at the cap.
    limit = 25 * 1024 * 1024
    with socket.create_connection(("127.0.0.1", live.stack.ports["gateway"]), timeout=15) as sock:
        sock.sendall(
            (
                f"POST /api/v1/stats/matches HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                f"Authorization: Bearer {live.key('off_ok')}\r\nContent-Length: {limit + 1}\r\nConnection: close\r\n\r\n"
            ).encode()
        )
        status_line = sock.recv(4096).split(b"\r\n", 1)[0].decode()
    assert " 413 " in status_line, status_line
    # An undeclared length (chunked) is cut at the cap: a 413, or the connection is dropped mid-stream; never accepted.
    with socket.create_connection(("127.0.0.1", live.stack.ports["gateway"]), timeout=15) as sock:
        sock.sendall(
            (
                f"POST /api/v1/stats/matches HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                f"Authorization: Bearer {live.key('off_ok')}\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
            ).encode()
        )
        frame = b"10000\r\n" + b"x" * 65536 + b"\r\n"
        try:
            for _ in range((limit + 1024 * 1024) // 65536):
                sock.sendall(frame)
            sock.sendall(b"0\r\n\r\n")
        except OSError:
            pass
        try:
            streamed = sock.recv(4096).split(b"\r\n", 1)[0].decode()
        except OSError:
            streamed = "connection dropped"
    assert streamed in ("", "connection dropped") or " 413 " in streamed, streamed
    after = live.baseline()
    assert after == before, (before, after)
    live.stack.evidence.record("job_ids", "refused_requests_rows_created", 0)


def test_valid_document_reaches_done_and_is_idempotent(live: Live) -> None:
    main = live.cases["main"]
    doc = document(main, "main-1")
    submitted = live.submit_ok("off_ok", doc)
    job_id = submitted["id"]
    assert submitted["status"] in {"pending", "processing", "done"} and submitted["external_id"] == "main-1"
    job, seen = live.settle("off_ok", job_id)
    assert job["status"] == "done", job
    assert job["binding"]["encounter_game_id"] == main.game_id and job["binding"]["revision"] == 1
    match = live.match(main.game_id)
    assert match["revision"] == 1 and match["ingest_job_id"] == job_id and match["id"] == job["binding"]["match_id"]
    counts = live.children(match["id"])
    assert counts["match_team"] == 2 and counts["match_player"] == 6 and counts["segment"] == 1
    assert counts["fact"] == 2 + 6 and counts["event"] == 1, counts
    live.drain()
    assert (
        live.s("SELECT status FROM public.event_outbox WHERE event_id=%s", f"match.ingested:{match['id']}:1")
        == "published"
    )
    # logs_official is off for this tournament: a receipt, and nothing official changes.
    receipts = live.wait_receipts(main.encounter_id, 1)
    assert [r["outcome"] for r in receipts] == ["logs_disabled"], receipts
    assert live.game(main.game_id)["result_version"] == 0 and live.game(main.game_id)["state"] != "confirmed"
    live.stack.evidence.record("job_ids", "main", job_id)
    live.stack.evidence.record("match_ids", "main", match["id"])
    live.stack.evidence.record("revisions", "main", [1])
    live.stack.evidence.record("observation_counts", "main", counts)
    live.stack.evidence.record("outbox_event_ids", "main", [f"match.ingested:{match['id']}:1"])
    live.stack.evidence.record("receipt_outcomes", "main", [r["outcome"] for r in receipts])

    # A foreign workspace's key cannot even see the job.
    assert live.get_job("on_ok", job_id).status == 404

    # Identical bytes: the existing job, no second row, no second revision.
    jobs_before = live.s("SELECT count(*) FROM stats.ingest_job")
    again = live.post("off_ok", canonical(doc))
    assert again.status == 200 and again.json()["id"] == job_id and again.json()["status"] == "done"
    assert live.s("SELECT count(*) FROM stats.ingest_job") == jobs_before
    assert live.match(main.game_id)["revision"] == 1

    # Same external id, changed content: refused and the existing job is untouched.
    changed = live.post("off_ok", canonical({**doc, "duration_s": 601}))
    assert changed.status == 409 and err(changed) == "idempotency_conflict", changed.raw[:300]
    assert live.s("SELECT count(*) FROM stats.ingest_job") == jobs_before


def test_new_content_replaces_the_observation_atomically(live: Live) -> None:
    main = live.cases["main"]
    first = live.match(main.game_id)
    second_doc = document(main, "main-2")
    second_doc["facts"] = [{**fact, "value": fact["value"] + 100} for fact in second_doc["facts"]]
    job_id = live.submit_ok("off_ok2", second_doc)["id"]
    job, seen = live.settle("off_ok2", job_id)
    assert job["status"] == "done" and job["binding"]["revision"] == 2
    match = live.match(main.game_id)
    assert match["id"] == first["id"] and match["revision"] == 2 and match["ingest_job_id"] == job_id
    # Every row is the new document's: no fact of revision 1 survives.
    values = sorted(row[0] for row in live.q("SELECT value FROM stats.fact WHERE match_id=%s", match["id"]))
    assert values == sorted(float(f["value"]) for f in second_doc["facts"]), values
    assert live.children(match["id"])["fact"] == len(second_doc["facts"])
    # The superseded job no longer claims the game.
    old = live.get_job("off_ok", live.s("SELECT id FROM stats.ingest_job WHERE external_id='main-1'")).json()
    assert old["status"] == "done" and old.get("binding") is None
    live.drain()
    assert (
        live.s("SELECT status FROM public.event_outbox WHERE event_id=%s", f"match.ingested:{match['id']}:2")
        == "published"
    )
    receipts = live.wait_receipts(main.encounter_id, 2)
    assert [r["outcome"] for r in receipts] == ["logs_disabled", "logs_disabled"]
    live.stack.evidence.record("revisions", "main", [1, 2])
    live.stack.evidence.record("job_ids", "main_replacement", job_id)
    live.stack.evidence.record("outbox_event_ids", "main", [f"match.ingested:{match['id']}:{n}" for n in (1, 2)])
    live.stack.evidence.record("receipt_outcomes", "main", [r["outcome"] for r in receipts])


def test_unbound_document_waits_for_an_admin_bind(live: Live) -> None:
    case = live.cases["awaiting"]
    doc = with_unknown_identities(document(case, "awaiting-1"))
    members_before = live.s("SELECT count(*) FROM public.workspace_member WHERE workspace_id=%s", case.workspace_id)
    job_id = live.submit_ok("off_ok", doc)["id"]
    job, seen = live.settle("off_ok", job_id)
    assert job["status"] == "awaiting_link", job
    assert live.match(case.game_id) is None
    assert live.s("SELECT count(*) FROM stats.match WHERE ingest_job_id=%s", job_id) == 0
    assert (
        live.s("SELECT count(*) FROM public.workspace_member WHERE workspace_id=%s", case.workspace_id)
        == members_before
    )
    live.drain()
    assert (
        live.s(
            "SELECT count(*) FROM public.event_outbox WHERE event_type='match_ingested' AND payload_json->>'ingest_job_id'=%s",
            str(job_id),
        )
        == 0
    )

    observation = live.admin("GET", f"/api/v1/admin/logs/games/{case.game_id}/observation")
    assert observation.status == 200 and observation.json()["revision"] == 0 and observation.json()["match_id"] is None
    teams = {team["key"]: seat for team, seat in zip(doc["teams"], case.team_ids, strict=True)}
    bound = live.admin(
        "POST",
        f"/api/v1/admin/logs/{job_id}/bind",
        {"encounter_game_id": case.game_id, "teams": teams, "expected_revision": observation.json()["revision"]},
    )
    assert bound.status == 200, bound.raw[:500]
    assert bound.json()["status"] == "done" and bound.json()["binding"]["revision"] == 1
    match = live.match(case.game_id)
    assert match["ingest_job_id"] == job_id and match["revision"] == 1
    assert live.children(match["id"])["match_player"] == 6
    # The six strangers exist only as observation anchors: no membership, no access.
    anchors = live.s(
        "SELECT count(*) FROM public.workspace_member WHERE workspace_id=%s AND observed_only", case.workspace_id
    )
    assert anchors == 6
    again = live.admin("GET", f"/api/v1/admin/logs/games/{case.game_id}/observation").json()
    assert again["revision"] == 1 and again["ingest_job_id"] == job_id
    live.settle("off_ok", job_id)  # the public status endpoint agrees
    live.stack.evidence.record("job_ids", "awaiting_bind", job_id)
    live.stack.evidence.record("match_ids", "awaiting_bind", match["id"])
    live.stack.evidence.record("observation_counts", "awaiting_bind", live.children(match["id"]))


def test_three_team_document_in_any_order_binds_every_seat(live: Live) -> None:
    case = live.cases["perm3"]
    doc = shuffled(document(case, "perm3-1"), seed=7)
    assert [t["key"] for t in doc["teams"]] != ["t1", "t2", "t3"]
    job_id = live.submit_ok("off_ok", doc)["id"]
    job, _ = live.settle("off_ok", job_id)
    assert job["status"] == "done", job
    match = live.match(case.game_id)
    position = {team["key"]: index for index, team in enumerate(doc["teams"], 1)}
    rows = live.q("SELECT encounter_team_id, source_position FROM stats.match_team WHERE match_id=%s", match["id"])
    # Document team t<i> is the roster of seat i, wherever the producer put it in the array.
    assert dict(rows) == {seat: position[f"t{index}"] for index, seat in enumerate(case.team_ids, 1)}
    members = live.q(
        "SELECT p.workspace_member_id, p.encounter_team_id FROM stats.match_player p WHERE p.match_id=%s", match["id"]
    )
    roster = dict(
        live.q(
            "SELECT workspace_member_id, encounter_team_id FROM encounter.team_member WHERE encounter_id=%s",
            case.encounter_id,
        )
    )
    assert dict(members) == roster
    live.stack.evidence.record("job_ids", "perm3", job_id)
    live.stack.evidence.record("match_ids", "perm3", match["id"])
    live.stack.evidence.record("observation_counts", "perm3", live.children(match["id"]))


def test_concurrent_identical_posts_make_one_job_and_one_revision(live: Live) -> None:
    case = live.cases["concurrent"]
    body = canonical(document(case, "concurrent-1"))
    results: list[Response] = []
    barrier = threading.Barrier(8)

    def fire(index: int) -> None:
        barrier.wait()
        results.append(live.post("off_ok" if index % 2 else "off_ok2", body))

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert {r.status for r in results} <= {200, 202}, [(r.status, r.raw[:200]) for r in results]
    ids = {r.json()["id"] for r in results}
    assert len(ids) == 1
    job_id = ids.pop()
    job, _ = live.settle("off_ok", job_id)
    assert job["status"] == "done"
    assert live.s("SELECT count(*) FROM stats.ingest_job WHERE external_id='concurrent-1'") == 1
    match = live.match(case.game_id)
    assert match["revision"] == 1 and match["ingest_job_id"] == job_id
    live.drain()
    assert live.s("SELECT count(*) FROM public.event_outbox WHERE event_id=%s", f"match.ingested:{match['id']}:1") == 1
    live.stack.evidence.record("job_ids", "concurrent", job_id)
    live.stack.evidence.record("revisions", "concurrent", [match["revision"]])


def test_unknown_stat_and_role_are_retained_as_diagnostics(live: Live) -> None:
    case = live.cases["unknown_codes"]
    doc = document(case, "unknown-1")
    doc["facts"].append({"team": "t1", "stat": "p5_unknown_stat", "value": 1})
    doc["participants"][0]["role"] = {"dimension": case.role["dimension"], "role": "p5_unknown_role"}
    response = live.post("off_ok", canonical(doc))
    assert response.status == 422, response.raw[:500]
    body = response.json()
    assert err(response) == "unknown_code" and body["ingest_job_id"] > 0 and body["issues"]
    job_id = body["ingest_job_id"]
    job, _ = live.settle("off_ok", job_id)
    assert job["status"] == "failed" and job["error"]["code"] == "unknown_code" and job["error"]["issues"]
    assert live.match(case.game_id) is None
    misses = {
        tuple(r)
        for r in live.q(
            "SELECT kind, raw_name FROM catalog.alias_miss WHERE discipline='overwatch' AND last_ingest_job_id=%s",
            job_id,
        )
    }
    assert ("stat", "p5_unknown_stat") in misses and ("role", f"{case.role['dimension']}:p5_unknown_role") in misses, (
        misses
    )
    live.drain()
    assert (
        live.s(
            "SELECT count(*) FROM public.event_outbox WHERE event_type='match_ingested' AND payload_json->>'ingest_job_id'=%s",
            str(job_id),
        )
        == 0
    )
    live.stack.evidence.record("job_ids", "unknown_codes", job_id)
    live.stack.evidence.record("observation_counts", "unknown_codes", {"matches": 0, "alias_misses": sorted(misses)})


def test_forged_hints_never_bind_or_replace(live: Live) -> None:
    hinted, other = live.cases["hinted"], live.cases["other"]
    foreign = live.cases["on_main"]
    jobs = live.s("SELECT count(*) FROM stats.ingest_job")
    # A hint at another workspace's game does not resolve for this key: refused, nothing persisted.
    forged = live.post("off_ok", canonical(document(hinted, "forged-1", hint={"encounter_game_id": foreign.game_id})))
    assert forged.status == 404 and err(forged) == "binding_target_not_found", forged.raw[:300]
    assert live.s("SELECT count(*) FROM stats.ingest_job") == jobs
    assert live.match(foreign.game_id) is None
    # A hint at an own game the participants do not belong to never overrides the roster evidence.
    job_id = live.submit_ok("off_ok", document(hinted, "forged-2", hint={"encounter_game_id": other.game_id}))["id"]
    job, _ = live.settle("off_ok", job_id)
    assert job["status"] in {"failed", "awaiting_link"}, job
    assert live.match(other.game_id) is None and live.match(hinted.game_id) is None
    live.stack.evidence.record("job_ids", "forged_hint", job_id)
    live.stack.evidence.record(
        "observation_counts",
        "forged_hint",
        {"status": job["status"], "code": (job.get("error") or {}).get("code"), "matches": 0},
    )


def test_workers_consume_only_their_own_discipline(live: Live) -> None:
    stack, case = live.stack, live.cases["lol"]
    stack.stop("worker_lol")
    wait_until(lambda: stack.consumers(ingest_queue("lol").name) == 0, "the lol ingest consumer to disappear")
    job_id = live.submit_ok("off_ok", document(case, "lol-1"))["id"]
    # The overwatch worker serves the overwatch queue only: the lol request waits, untouched.
    wait_until(
        lambda: (stack.queue(ingest_queue("lol").name) or {}).get("messages", 0) >= 1,
        "the lol request to queue",
        timeout=30,
    )
    time.sleep(6)
    assert live.job(job_id)["status"] == "pending" and live.job(job_id)["attempts"] == 0
    stack.faststream("worker_lol", "stats-service", "serve_worker", port=free_port(), **stack.worker_env("lol"))
    stack.ready("worker_lol", "/health 200", lambda: stack.health("worker_lol")[0] == 200)
    job, _ = live.settle("off_ok", job_id)
    assert job["status"] == "done", job
    assert live.job(job_id)["discipline"] == "lol" and live.match(case.game_id)["revision"] == 1
    # A lol job delivered to the overwatch queue is refused to its dead-letter queue and left as it was.
    dlq = ingest_dlq("overwatch").name
    dead_before = (stack.queue(dlq) or {}).get("messages", 0)

    async def publish() -> None:
        from faststream.rabbit import RabbitBroker

        broker = RabbitBroker(stack.vhost_url)
        await broker.start()
        try:
            await broker.publish(
                ProcessIngestJobEvent(ingest_job_id=job_id, source_service="p5-live-smoke").model_dump(),
                ingest_queue("overwatch").name,
            )
        finally:
            await broker.stop()

    asyncio.run(publish())
    wait_until(
        lambda: (stack.queue(dlq) or {}).get("messages", 0) == dead_before + 1,
        "the refused message in the overwatch DLQ",
        timeout=60,
    )
    assert live.job(job_id)["status"] == "done" and live.match(case.game_id)["revision"] == 1
    live.drain()
    live.stack.evidence.record("job_ids", "lol", job_id)
    live.stack.evidence.record(
        "observation_counts", "wrong_queue", {"dlq_messages": dead_before + 1, "lol_revision": 1}
    )


def test_logs_official_off_on_and_admin_precedence(live: Live) -> None:
    on_main, on_admin = live.cases["on_main"], live.cases["on_admin"]
    # ON tournament: the evidence becomes the official result.
    job_id = live.submit_ok("on_ok", document(on_main, "on-main-1"))["id"]
    job, _ = live.settle("on_ok", job_id)
    assert job["status"] == "done"
    receipts = live.wait_receipts(on_main.encounter_id, 1)
    assert [r["outcome"] for r in receipts] == ["accepted"], receipts
    game = live.game(on_main.game_id)
    assert game["state"] == "confirmed" and game["result_version"] == 1 and game["result_source"] == "admin_log", game
    winner = live.s(
        "SELECT encounter_team_id FROM encounter.game_team WHERE game_id=%s ORDER BY score DESC NULLS LAST LIMIT 1",
        on_main.game_id,
    )
    assert winner == on_main.team_ids[0]

    # An organizer's own result stands: later evidence that disagrees is journaled, never applied.
    live.stack.run_script(
        "_live_admin_result.py",
        "tournament-service",
        "__RESULT__",
        stdin={
            "encounter_id": on_admin.encounter_id,
            "game_id": on_admin.game_id,
            "scores": {str(on_admin.team_ids[0]): 3, str(on_admin.team_ids[1]): 1},
        },
    )
    admin_game = live.game(on_admin.game_id)
    assert admin_game["result_source"] == "admin"
    contradicting = document(on_admin, "on-admin-1")
    contradicting["teams"] = [{"key": "t1", "placement": 2}, {"key": "t2", "placement": 1}]
    admin_job = live.submit_ok("on_ok", contradicting)["id"]
    assert live.settle("on_ok", admin_job)[0]["status"] == "done"
    outcomes = [r["outcome"] for r in live.wait_receipts(on_admin.encounter_id, 1)]
    assert outcomes == ["result_locked"], outcomes
    assert live.game(on_admin.game_id) == admin_game
    scores = dict(live.q("SELECT encounter_team_id, score FROM encounter.game_team WHERE game_id=%s", on_admin.game_id))
    assert scores == {on_admin.team_ids[0]: 3, on_admin.team_ids[1]: 1}

    # An explicit reparse of the accepted evidence yields revision 2; the first accepted result still stands.
    reparse = live.admin("POST", f"/api/v1/admin/logs/{job_id}/retry", {"reparse": True, "expected_revision": 1})
    assert reparse.status == 200, reparse.raw[:400]
    wait_until(
        lambda: (live.match(on_main.game_id) or {}).get("revision") == 2, "revision 2 of the ON game", timeout=60
    )
    receipts = live.wait_receipts(on_main.encounter_id, 2)
    assert [r["outcome"] for r in receipts] == ["accepted", "result_locked"], receipts
    assert live.game(on_main.game_id) == game
    live.stack.evidence.record("job_ids", "on_main", job_id)
    live.stack.evidence.record("job_ids", "on_admin", admin_job)
    live.stack.evidence.record("receipt_outcomes", "on_main", [r["outcome"] for r in receipts])
    live.stack.evidence.record("receipt_outcomes", "on_admin", outcomes)
    live.stack.evidence.record("revisions", "on_main", [1, 2])


def _multipart(fields: dict[str, str], filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="files[]"; filename="{filename}"\r\n'
        "Content-Type: text/csv\r\n\r\n".encode()
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _observed(live: Live, game_id: int) -> dict:
    async def run() -> dict:
        engine, factory = async_session_factory(live.stack.db_url)
        try:
            return await observe(SimpleNamespace(sf=factory, game=game_id))
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_workshop_upload_matches_the_task0_reference(live: Live) -> None:
    shop = live.workshop
    raw = (DIRECTORY / "workshop.csv").read_bytes()
    body, content_type = _multipart(
        {"tournament_id": str(shop.tournament_id), "encounter_id": str(shop.encounter_id)}, "workshop.csv", raw
    )
    response = http(
        "POST",
        f"{live.stack.gateway}/api/v1/admin/logs/upload",
        body=body,
        headers={"Authorization": f"Bearer {live.admin_token()}", "Content-Type": content_type},
    )
    assert response.status == 200 and not response.json()["errors"], response.raw[:500]
    job_id = response.json()["uploaded"][0]["record_id"]
    wait_until(lambda: live.job(job_id)["status"] in TERMINAL, f"workshop job {job_id}", timeout=120)
    assert live.job(job_id)["status"] == "done", live.job(job_id)
    expected = json.loads((DIRECTORY / "expected.json").read_bytes())
    actual = _observed(live, shop.game_id)
    assert actual["match"]["map"] == expected["match"]["map"]
    assert actual["match"]["duration_s"] == expected["match"]["duration_s"]
    for section in ("segments", "team_scores", "players", "events"):
        assert actual[section] == expected[section], section
    assert len(actual["facts"]) == len(expected["facts"])
    for got, want in zip(actual["facts"], expected["facts"], strict=True):
        assert got == want, (got, want)
    live.drain()
    live.wait_receipts(shop.encounter_id, 1)
    live.stack.evidence.record("job_ids", "workshop", job_id)
    live.stack.evidence.record("match_ids", "workshop", live.match(shop.game_id)["id"])
    live.stack.evidence.record(
        "observation_counts", "workshop", {key: len(expected[key]) for key in ("facts", "events", "players")}
    )
    live.stack.evidence.record("receipt_outcomes", "workshop", [r["outcome"] for r in live.receipts(shop.encounter_id)])
    live.stack.evidence.record("revisions", "workshop", [live.match(shop.game_id)["revision"]])


def test_tournament_replay_runs_through_the_replay_queue(live: Live) -> None:
    shop, stack = live.workshop, live.stack
    before = live.match(shop.game_id)
    assert before["revision"] == 1
    replay = ingest_replay_queue("overwatch").name
    response = live.admin("POST", f"/api/v1/logs/{shop.tournament_id}")
    assert response.status in (200, 202), response.raw[:300]
    wait_until(
        lambda: (live.match(shop.game_id) or {}).get("revision") == 2, "the replayed reparse (revision 2)", timeout=90
    )
    assert live.match(shop.game_id)["ingest_job_id"] == before["ingest_job_id"]
    wait_until(lambda: (stack.queue(replay) or {}).get("messages", 1) == 0, "the replay queue to drain", timeout=30)
    assert stack.consumers(replay) == 1
    assert (stack.queue(ingest_replay_dlq("overwatch").name) or {}).get("messages", 0) == 0
    live.drain()
    stack.evidence.record("revisions", "workshop_replay", [1, 2])
    stack.evidence.record("job_ids", "workshop_replay", before["ingest_job_id"])


def _hold_encounter_lock(live: Live, encounter_id: int):
    """Hold the encounter row lock the writer takes first: the worker claims, then waits (as a stuck decode would)."""
    import psycopg

    connection = psycopg.connect(
        host=live.stack.pg["host"],
        port=int(live.stack.pg["port"]),
        user=live.stack.pg["user"],
        password=live.stack.pg["password"],
        dbname=live.stack.db,
        autocommit=False,
    )
    connection.execute("SELECT id FROM encounter.encounter WHERE id=%s FOR UPDATE", (encounter_id,))
    return connection


def _waiting_on_lock(live: Live) -> bool:
    return (
        live.s("SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND wait_event_type='Lock'", live.stack.db) >= 1
    )


def test_paused_worker_cannot_commit_a_reclaimed_attempt(live: Live) -> None:
    stack, case = live.stack, live.cases["stale"]
    observed: list[str] = []
    held = _hold_encounter_lock(live, case.encounter_id)
    try:
        job_id = live.submit_ok("off_ok", document(case, "stale-1"))["id"]
        wait_until(lambda: live.job(job_id)["status"] == "processing", "worker_overwatch to claim the job")
        wait_until(lambda: _waiting_on_lock(live), "the claimed attempt to wait on the encounter lock")
        first = live.job(job_id)
        assert first["attempts"] == 1
        observed.append(f"{first['status']} (attempts {first['attempts']})")
        # Slow decode: the worker is stuck mid-job, the RPC process is another process and keeps answering.
        started = time.monotonic()
        status = live.get_job("off_ok", job_id)
        assert status.status == 200 and status.json()["status"] == "processing" and time.monotonic() - started < 3
        stack.pause("worker_overwatch")  # the claim can no longer be heartbeated: a frozen process
        stack.faststream(
            "worker_overwatch_2", "stats-service", "serve_worker", port=free_port(), **stack.worker_env("overwatch")
        )
        stack.ready("worker_overwatch_2", "/health 200", lambda: stack.health("worker_overwatch_2")[0] == 200)
        wait_until(
            lambda: live.job(job_id)["attempts"] == 2,
            "the reaper to reclaim and a second worker to re-claim",
            timeout=120,
        )
        second = live.job(job_id)
        observed.append(f"{second['status']} (attempts {second['attempts']})")
        assert second["status"] == "processing"
        started = time.monotonic()
        assert live.get_job("off_ok", job_id).status == 200 and time.monotonic() - started < 3
    finally:
        held.rollback()
        held.close()
    stack.resume("worker_overwatch")  # the stale attempt wakes up holding a superseded claim
    job, seen = live.settle("off_ok", job_id, timeout=120)
    final = live.job(job_id)
    observed.append(f"{final['status']} (attempts {final['attempts']})")
    assert job["status"] == "done" and final["attempts"] == 2
    match = live.match(case.game_id)
    assert match["revision"] == 1 and match["ingest_job_id"] == job_id
    live.drain()
    assert (
        live.s("SELECT count(*) FROM public.event_outbox WHERE event_id LIKE %s", f"match.ingested:{match['id']}:%")
        == 1
    )
    stack.stop("worker_overwatch")
    stack.stop("worker_overwatch_2")
    stack.evidence.record("job_ids", "stale_attempt", job_id)
    stack.evidence.record("revisions", "stale_attempt", [match["revision"]])
    stack.evidence.record("status_transitions", f"stale_attempt_db:{job_id}", observed)


def test_killed_worker_is_reclaimed_after_restart(live: Live) -> None:
    stack, case = live.stack, live.cases["killed"]
    stack.faststream(
        "worker_overwatch_3", "stats-service", "serve_worker", port=free_port(), **stack.worker_env("overwatch")
    )
    stack.ready(
        "worker_overwatch_3", "consuming the ingest queue", lambda: stack.consumers(ingest_queue("overwatch").name) == 1
    )
    held = _hold_encounter_lock(live, case.encounter_id)
    try:
        job_id = live.submit_ok("off_ok", document(case, "killed-1"))["id"]
        wait_until(lambda: live.job(job_id)["status"] == "processing", "the worker to claim the job")
        wait_until(lambda: _waiting_on_lock(live), "the claimed attempt to wait on the encounter lock")
        stack.kill("worker_overwatch_3")  # hard kill after the claim was committed
        assert live.job(job_id)["status"] == "processing"
    finally:
        held.rollback()
        held.close()
    stack.faststream(
        "worker_overwatch_4", "stats-service", "serve_worker", port=free_port(), **stack.worker_env("overwatch")
    )
    stack.ready(
        "worker_overwatch_4", "consuming the ingest queue", lambda: stack.consumers(ingest_queue("overwatch").name) >= 1
    )
    job, seen = live.settle("off_ok", job_id, timeout=120)
    assert job["status"] == "done", job
    assert live.job(job_id)["attempts"] == 2
    match = live.match(case.game_id)
    assert match["revision"] == 1 and match["ingest_job_id"] == job_id
    live.drain()
    assert (
        live.s("SELECT count(*) FROM public.event_outbox WHERE event_id LIKE %s", f"match.ingested:{match['id']}:%")
        == 1
    )
    stack.evidence.record("job_ids", "killed_worker", job_id)
    stack.evidence.record("revisions", "killed_worker", [match["revision"]])


def test_frozen_worker_leaves_rpc_responsive_and_the_queue_catches_up(live: Live) -> None:
    stack, case = live.stack, live.cases["frozen"]
    stack.pause("worker_overwatch_4")
    try:
        job_id = live.submit_ok("off_ok", document(case, "frozen-1"))["id"]
        for _ in range(5):
            started = time.monotonic()
            response = live.get_job("off_ok", job_id)
            assert response.status == 200 and response.json()["status"] == "pending" and time.monotonic() - started < 3
            time.sleep(0.5)
    finally:
        stack.resume("worker_overwatch_4")
    job, _ = live.settle("off_ok", job_id)
    assert job["status"] == "done"
    live.stack.evidence.record("job_ids", "frozen_worker", job_id)


# --- P6: achievement evaluation scoped to the owning discipline, driven by the real ingest events ---------------------


def _runs(live: Live, tournament_id: int) -> list[dict]:
    rows = live.q(
        "SELECT id::text, status, trigger, rules_evaluated, results_created, results_removed, error_message "
        "FROM achievements.evaluation_run WHERE tournament_id=%s ORDER BY started_at, id",
        tournament_id,
    )
    keys = ("id", "status", "trigger", "rules_evaluated", "results_created", "results_removed", "error")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def _results(live: Live, rule_id: int) -> list[dict]:
    rows = live.q(
        "SELECT id, workspace_member_id, tournament_id, match_id, rule_version, evidence_json "
        "FROM achievements.evaluation_result WHERE achievement_rule_id=%s ORDER BY workspace_member_id",
        rule_id,
    )
    keys = ("id", "member", "tournament", "match", "rule_version", "evidence")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def _finished_runs(live: Live, tournament_id: int, count: int) -> list[dict]:
    wait_until(
        lambda: len([r for r in _runs(live, tournament_id) if r["status"] in ("done", "partial")]) >= count,
        f"{count} finished achievement run(s) on tournament {tournament_id}",
        timeout=90,
    )
    return _runs(live, tournament_id)


def _publish_achievement_event(live: Live, event) -> None:
    async def publish() -> None:
        from faststream.rabbit import RabbitBroker

        from shared.messaging.config import ACHIEVEMENT_EVALUATE_QUEUE

        broker = RabbitBroker(live.stack.vhost_url)
        await broker.start()
        try:
            await broker.publish(event.model_dump(), ACHIEVEMENT_EVALUATE_QUEUE.name)
        finally:
            await broker.stop()

    asyncio.run(publish())


def test_overwatch_ingest_awards_once_and_the_other_game_is_never_evaluated_with_it(live: Live) -> None:
    from tests.live_smoke_world import ACH_THRESHOLD, seed_achievement_rules

    ow, wait, failed, lol = (live.cases[name] for name in ("ach_ow", "ach_wait", "ach_failed", "ach_lol"))
    seeded = asyncio.run(seed_achievement_rules(live.stack.db_url, live.cases))
    ow_rule, wait_rule, failed_rule = (seeded["rules"][name] for name in ("ach_ow", "ach_wait", "ach_failed"))
    lol_rule, lol_award = seeded["lol_rule"], seeded["lol_result"]
    assert _results(live, ow_rule) == [] and _runs(live, ow.tournament_id) == []

    # An awaiting-link document and a failed document write no observation: nothing can be awarded for them.
    waiting_id = live.submit_ok("off_ok", with_unknown_identities(document(wait, "ach-wait-1")))["id"]
    assert live.settle("off_ok", waiting_id)[0]["status"] == "awaiting_link"
    bad = document(failed, "ach-failed-1")
    bad["facts"].append({"team": "t1", "stat": "p6_unknown_stat", "value": 1})
    response = live.post("off_ok", canonical(bad))
    assert response.status == 422 and err(response) == "unknown_code", response.raw[:400]
    assert live.settle("off_ok", response.json()["ingest_job_id"])[0]["status"] == "failed"
    live.drain()

    # The real ingest: stored observations -> the writer's success events -> achievement evaluation in the worker.
    job_id = live.submit_ok("off_ok", document(ow, "ach-ow-1"))["id"]
    job, _ = live.settle("off_ok", job_id)
    assert job["status"] == "done", job
    match = live.match(ow.game_id)
    live.drain()
    wait_until(lambda: len(_results(live, ow_rule)) == 3, "three awards for the Overwatch rule", timeout=90)
    runs = _finished_runs(live, ow.tournament_id, 1)
    assert all(r["trigger"] == "parse_complete" and r["status"] == "done" for r in runs), runs
    expected_members = {ow.member_ids[0][2], ow.member_ids[1][1], ow.member_ids[1][2]}  # eliminations 5, 5, 6
    assert ACH_THRESHOLD == 5
    awards = _results(live, ow_rule)
    assert {a["member"] for a in awards} == expected_members
    for award in awards:
        assert (award["tournament"], award["match"], award["rule_version"]) == (ow.tournament_id, match["id"], 1)
        assert award["evidence"]["rule_slug"] == "live-hero-elims-ach_ow", award
    # The same ingest wrote one observation event and the standings invalidation reached its original consumer
    # (tournament-service turns it into a recalculation job); neither replaced the other.
    event_types = {
        r[0]
        for r in live.q(
            "SELECT DISTINCT event_type FROM public.event_outbox WHERE payload_json->>'tournament_id'=%s "
            "OR payload_json->>'encounter_id'=%s",
            str(ow.tournament_id),
            str(ow.encounter_id),
        )
    }
    assert {"achievement_evaluate", "match_ingested"} <= event_types, event_types
    wait_until(
        lambda: live.s("SELECT count(*) FROM tournament.computation_job WHERE tournament_id=%s", ow.tournament_id) >= 1,
        "the standings recalculation job the original consumer creates",
        timeout=60,
    )
    assert (live.stack.queue("tournament_standings_invalidated") or {}).get("messages", 0) == 0
    # Awaiting-link and failed ingests awarded nothing and observed nothing.
    for case, rule in ((wait, wait_rule), (failed, failed_rule)):
        assert _results(live, rule) == []
        assert live.s("SELECT count(*) FROM stats.match WHERE encounter_id=%s", case.encounter_id) == 0
        assert all(r["results_created"] == 0 for r in _runs(live, case.tournament_id))

    # Encounter completed: a best-of-3 series is decided by the organizer's second map win. The completed-encounter
    # trigger evaluates again and converges on the same awards (same rows, no duplicates).
    async def second_game() -> int:
        engine, factory = async_session_factory(live.stack.db_url)
        try:
            async with factory() as session:
                game_id = await add_game(session, ow)
                await session.commit()
                return game_id
        finally:
            await engine.dispose()

    games = [ow.game_id, asyncio.run(second_game())]
    before_runs = len(_runs(live, ow.tournament_id))
    for game_id in games:
        live.stack.run_script(
            "_live_admin_result.py",
            "tournament-service",
            "__RESULT__",
            stdin={
                "encounter_id": ow.encounter_id,
                "game_id": game_id,
                "scores": {str(ow.team_ids[0]): 3, str(ow.team_ids[1]): 1},
            },
        )
    live.drain()
    assert (
        live.s(
            "SELECT count(*) FROM public.event_outbox WHERE event_type='encounter_completed' "
            "AND payload_json->>'encounter_id'=%s AND status='published'",
            str(ow.encounter_id),
        )
        == 1
    )
    _finished_runs(live, ow.tournament_id, before_runs + 1)
    assert _results(live, ow_rule) == awards

    # Redelivering the same event is idempotent: another run, zero created, zero removed, identical rows.
    finished = len([r for r in _runs(live, ow.tournament_id) if r["status"] in ("done", "partial")])
    event = AchievementEvaluateEvent(
        workspace_id=ow.workspace_id,
        tournament_id=ow.tournament_id,
        changed_tables=["stats.match", "stats.fact", "stats.event"],
        source_service="p6-live-smoke",
    )
    for _ in range(2):
        _publish_achievement_event(live, event)
    runs = _finished_runs(live, ow.tournament_id, finished + 2)
    wait_until(
        lambda: (
            (q := live.stack.queue("achievement_evaluate") or {}).get("messages", 1) == 0
            and q.get("messages_unacknowledged", 1) == 0
        ),
        "the achievement queue to go idle",
        timeout=60,
    )
    runs = _runs(live, ow.tournament_id)
    assert _results(live, ow_rule) == awards
    # Exactly one run ever created the three awards and no run removed anything: every redelivery converged.
    assert sum(r["results_created"] for r in runs) == 3 and sum(r["results_removed"] for r in runs) == 0, runs
    assert all(r["status"] == "done" for r in runs), runs

    # A LoL canonical ingest reaches its existing success state and evaluates only LoL's own (condition-less) rules.
    lol_job = live.submit_ok("off_ok", document(lol, "ach-lol-1"))["id"]
    assert live.settle("off_ok", lol_job)[0]["status"] == "done"
    live.drain()
    wait_until(
        lambda: any(r["status"] == "partial" for r in _runs(live, lol.tournament_id)),
        "the writer's achievement run on the LoL tournament",
        timeout=90,
    )
    lol_runs = _finished_runs(live, lol.tournament_id, 1)
    # The writer's event selects LoL's one rule, which cannot run (LoL declares no conditions) and is reported on the
    # run; any other trigger on this tournament (standings) selects nothing. No run evaluates, creates or removes.
    assert any(
        r["status"] == "partial" and "discipline 'lol' has no achievement conditions" in (r["error"] or "")
        for r in lol_runs
    ), lol_runs
    assert all(r["rules_evaluated"] == 0 and r["results_created"] == 0 and r["results_removed"] == 0 for r in lol_runs)
    # The LoL sentinel award survives untouched, no Overwatch rule produced an award for a LoL tournament, member or
    # match, and the Overwatch awards are exactly what they were.
    sentinel = _results(live, lol_rule)
    assert [s["id"] for s in sentinel] == [lol_award] and sentinel[0]["evidence"]["sentinel"] is True
    assert (
        live.s(
            "SELECT count(*) FROM achievements.evaluation_result r JOIN achievements.rule u ON u.id=r.achievement_rule_id "
            "WHERE u.discipline='overwatch' AND (r.tournament_id=%s OR r.match_id IN "
            "(SELECT id FROM stats.match WHERE discipline='lol'))",
            lol.tournament_id,
        )
        == 0
    )
    assert _results(live, ow_rule) == awards
    # No Overwatch workload of any kind was addressed to the LoL tournament or its encounter.
    assert (
        live.s(
            "SELECT count(*) FROM public.event_outbox WHERE (payload_json->>'tournament_id'=%s "
            "OR payload_json->>'encounter_id'=%s) AND payload_json->>'discipline'='overwatch'",
            str(lol.tournament_id),
            str(lol.encounter_id),
        )
        == 0
    )
    assert (live.stack.queue("achievement_evaluate.dlq") or {}).get("messages", 0) == 0
    live.stack.evidence.record("job_ids", "ach_ow", job_id)
    live.stack.evidence.record("job_ids", "ach_lol", lol_job)
    live.stack.evidence.record(
        "observation_counts",
        "achievements",
        {
            "ow_awards": len(awards),
            "ow_runs": [(r["status"], r["results_created"], r["results_removed"]) for r in runs],
            "lol_runs": [(r["status"], r["rules_evaluated"]) for r in lol_runs],
            "lol_sentinel_ids": [s["id"] for s in sentinel],
        },
    )


def test_nothing_unexpected_was_dead_lettered_and_every_process_exits(live: Live) -> None:
    stack = live.stack
    for slug in ("overwatch", "lol"):
        assert (stack.queue(ingest_replay_dlq(slug).name) or {}).get("messages", 0) == 0
    assert (stack.queue(MATCH_INGESTED_TOURNAMENT_DLQ.name) or {}).get("messages", 0) == 0
    assert (stack.queue("achievement_evaluate.dlq") or {}).get("messages", 0) == 0
    assert live.s("SELECT count(*) FROM stats.ingest_job WHERE status='processing'") == 0
    stack.evidence.append("ready_checks", {"check": "final", "jobs": live.s("SELECT count(*) FROM stats.ingest_job")})
    for name in ("worker_overwatch_4", "worker_lol", "stats_rpc", "tournament", "identity", "gateway"):
        assert stack.stop(name) == 0, f"{name} did not exit cleanly"
