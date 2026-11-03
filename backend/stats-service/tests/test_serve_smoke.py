"""The two stats processes: RPC handlers only in one, every consumer and schedule in the other."""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from faststream import FastStream

from shared.messaging.config import (
    ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE,
    ACHIEVEMENT_EVALUATE_QUEUE,
    RANK_PLAYER_REFRESH_QUEUE,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = BACKEND_ROOT / "stats-service"


def _import(module: str):
    sys.path.insert(0, str(BACKEND_ROOT))
    sys.path.insert(0, str(SERVICE_ROOT))

    return importlib.import_module(module)


def _subjects(process) -> set[str]:
    return {
        getattr(subscriber, "subject", None) or getattr(getattr(subscriber, "queue", None), "name", None)
        for subscriber in process.broker.subscribers
    }


def _fresh_interpreter(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a new interpreter (cwd = the service) with the test environment plus ``env``."""
    full_env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(BACKEND_ROOT), str(SERVICE_ROOT)])}
    full_env.pop("STATS_DISCIPLINES", None)
    full_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=SERVICE_ROOT,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_both_entry_points_expose_a_faststream_app() -> None:
    assert isinstance(_import("serve_rpc").app, FastStream)
    assert isinstance(_import("serve_worker").app, FastStream)


def test_the_rpc_process_registers_rpc_handlers_and_no_consumer() -> None:
    subjects = _subjects(_import("serve_rpc"))

    assert {"rpc.stats.logs.upload", "rpc.stats.logs.history", "rpc.stats.rank.user_history"} <= subjects
    assert {"rpc.stats.ach.calculate", "rpc.stats.ingest.submit", "rpc.stats.rank.collect"} <= subjects
    assert all(subject.startswith("rpc.stats.") for subject in subjects), sorted(subjects)


def test_the_worker_registers_consumers_and_no_rpc_handler() -> None:
    subjects = _subjects(_import("serve_worker"))

    assert not [subject for subject in subjects if subject.startswith("rpc.")], sorted(subjects)
    assert {"stats.ingest.overwatch", "stats.ingest.lol"} <= subjects
    assert {"stats.ingest.overwatch.replay", "stats.ingest.lol.replay"} <= subjects
    assert {
        "upload_match_log",
        "process_tournament_logs",
        ACHIEVEMENT_EVALUATE_QUEUE.name,
        ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE.name,
    } <= subjects
    assert "tournament_encounter_completed" in subjects
    # The OverFast module's own consumers: normal/priority fetch and the player refresh.
    assert {"rank_fetch", "rank_fetch_priority", RANK_PLAYER_REFRESH_QUEUE.name} <= subjects
    assert "process_match_log" not in subjects
    assert "swiss_next_round" not in subjects and "tournament_recalc" not in subjects


def test_each_ingest_queue_gets_its_own_amqp_channel() -> None:
    """A delivery that outlives RabbitMQ's consumer_timeout closes the channel it arrived on, taking every consumer
    sharing it down with it. A minutes-long parse must not share one with the short handlers or with another game's
    ingest, or a single slow log strands uploads on "Queued"."""
    worker = _import("serve_worker")

    channel_by_queue = {
        subscriber.queue.name: subscriber.channel
        for subscriber in worker.broker.subscribers
        if getattr(subscriber, "queue", None) is not None
    }

    ingest = {name: channel for name, channel in channel_by_queue.items() if name.startswith("stats.ingest.")}
    assert set(ingest) == {
        f"stats.ingest.{spec.code}{suffix}" for spec in worker.SELECTED for suffix in ("", ".replay")
    }
    assert len({id(channel) for channel in ingest.values()}) == len(ingest)
    for short_handler in ("upload_match_log", "process_tournament_logs", ACHIEVEMENT_EVALUATE_QUEUE.name):
        assert channel_by_queue[short_handler] is worker._JOBS_CHANNEL
        assert all(channel is not worker._JOBS_CHANNEL for channel in ingest.values())


def test_the_queue_depth_monitor_lists_the_selected_ingest_and_replay_queues() -> None:
    _import("serve_worker")
    admin_reads = importlib.import_module("src.services.match_logs.admin_reads")

    assert {"stats.ingest.overwatch", "stats.ingest.overwatch.replay", "stats.ingest.lol.replay"} <= set(
        admin_reads.MONITORED_QUEUES
    )
    assert "process_match_log" not in admin_reads.MONITORED_QUEUES


def test_only_the_selected_disciplines_get_an_ingest_consumer_and_module_jobs() -> None:
    done = _fresh_interpreter(
        """
        import serve_worker as w
        names = sorted(s.queue.name for s in w.broker.subscribers if getattr(s, "queue", None) is not None)
        print(names)
        print(sorted(d.name for d in w._OWNED_DLQS if d.name.startswith("stats.ingest.")))
        """,
        STATS_DISCIPLINES="lol",
    )

    assert done.returncode == 0, done.stderr
    names, dlqs = done.stdout.strip().splitlines()[-2:]
    assert "'stats.ingest.lol'" in names and "'stats.ingest.lol.replay'" in names
    assert "stats.ingest.overwatch" not in names
    assert "'rank_fetch'" not in names, "a LoL-only worker runs no Overwatch collector"
    assert "'lol_rank_fetch'" in names
    assert dlqs == "['stats.ingest.lol.dlq', 'stats.ingest.lol.replay.dlq']"


@pytest.mark.parametrize("value", ["", " ", "overwatch,", ",lol", "overwatch,,lol", "overwatch,overwatch", "chess"])
def test_an_invalid_selection_fails_startup_for_both_processes(value: str) -> None:
    for module in ("serve_rpc", "serve_worker"):
        done = _fresh_interpreter(f"import {module}", STATS_DISCIPLINES=value)

        assert done.returncode != 0, f"{module} started with STATS_DISCIPLINES={value!r}"
        assert "STATS_DISCIPLINES" in done.stderr


def test_the_rpc_process_wires_the_collection_runtime_without_starting_a_job() -> None:
    done = _fresh_interpreter(
        """
        import serve_rpc
        from shared.disciplines.overwatch.collector import runtime
        from src.services.match_logs import reaper, retention
        from src.services.subscription_collection import scheduler as subscription

        assert runtime.broker() is serve_rpc.broker
        runtime.session_factory(), runtime.redis()
        assert not (reaper._scheduler.running or retention._scheduler.running or subscription._scheduler.running)
        print("wired")
        """
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().endswith("wired")


def test_shutdown_keeps_rank_fetch_available_until_consumers_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    """Schedules stop when shutdown begins; the rank client closes only after the consumers drained."""
    serve = _import("serve_worker")
    lifecycle = importlib.import_module("src.core.lifecycle")
    client_module = importlib.import_module("shared.disciplines.overwatch.collector.client")
    tasks = importlib.import_module("shared.disciplines.overwatch.collector.tasks")
    scheduler = importlib.import_module("shared.disciplines.overwatch.collector.scheduler")
    client = client_module.OverFastRankClient("http://overfast.local")
    schedule_stops: list[str] = []
    monkeypatch.setattr(tasks, "rank_client", client)
    monkeypatch.setattr(scheduler, "shutdown_scheduler", lambda: schedule_stops.append("stopped"))
    monkeypatch.setattr(lifecycle.s3_client, "close", AsyncMock())
    monkeypatch.setattr(lifecycle.realtime_redis, "aclose", AsyncMock())
    monkeypatch.setattr(lifecycle, "close_quota", AsyncMock())

    async def exercise_shutdown() -> None:
        payload = {"competitive": {"pc": {"tank": {"division": "gold", "tier": 2}}}}
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(base_url=client.base_url, transport=transport) as http:
            client._http._client = http

            async def drain_consumers() -> None:
                assert schedule_stops == ["stopped"], "schedules must stop before the consumers drain"
                result = await client.fetch_summary("Name#1234")
                tank = next(rank for rank in result.ranks if rank.role == "tank")
                assert (result.status, tank.division, tank.tier) == ("ok", "gold", 2)

            monkeypatch.setattr(serve.broker, "stop", drain_consumers)
            await serve.app.stop()
            with pytest.raises(RuntimeError):
                await client.fetch_summary("Name#1234")
            assert schedule_stops == ["stopped"]

    asyncio.run(exercise_shutdown())
