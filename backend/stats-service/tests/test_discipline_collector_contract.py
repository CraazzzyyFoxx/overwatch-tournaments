"""The Overwatch module (collector included) imports nothing from a service, and a worker runs only the jobs of the
disciplines it selected.

The import checks run in a fresh interpreter whose path contains the parser's ``src``: if any module under
``shared/disciplines/overwatch`` reached into it, ``src`` would appear in ``sys.modules``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "stats-service"))

from shared.disciplines import DISCIPLINES  # noqa: E402
from shared.disciplines import jobs as discipline_jobs  # noqa: E402
from shared.disciplines.overwatch.collector import handlers, runtime  # noqa: E402


def _run(script: str) -> dict:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(backend_root), str(backend_root / "stats-service")])}
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, cwd=backend_root, check=False
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_every_overwatch_module_imports_without_a_service() -> None:
    out = _run(
        """
import importlib, json, pkgutil, sys
import shared.disciplines.overwatch as ow

names = [m.name for m in pkgutil.walk_packages(ow.__path__, ow.__name__ + ".")]
for name in names:
    importlib.import_module(name)
print(json.dumps({
    "imported": sorted(n for n in names if n.startswith(ow.__name__ + ".collector")),
    "src": sorted(m for m in sys.modules if m == "src" or m.startswith("src.")),
}))
"""
    )
    assert out["src"] == []
    # The scan really reached the moved modules.
    assert {"admin", "client", "handlers", "jobs", "scheduler", "service", "tasks"} <= {
        name.rsplit(".", 1)[1] for name in out["imported"]
    }


def test_loading_the_registry_does_not_load_the_collector() -> None:
    out = _run(
        """
import json, sys
import shared.disciplines

# coverage (measuring subprocesses in CI) brings its own ``coverage.collector``: not a discipline collector.
print(json.dumps({"collector": sorted(m for m in sys.modules if ".collector" in m and not m.startswith("coverage."))}))
"""
    )
    assert out["collector"] == []


def test_a_lol_only_worker_runs_its_own_collector_and_never_loads_overwatchs() -> None:
    out = _run(
        """
import asyncio, json, sys
from shared.disciplines import DISCIPLINES, jobs


class Declared:
    async def bind(self, exchange, routing_key):
        return None


class Broker:
    def __init__(self):
        self.queues = []

    def subscriber(self, queue, **_):
        self.queues.append(queue.name)
        return lambda fn: fn

    async def declare_exchange(self, exchange):
        return exchange

    async def declare_queue(self, queue):
        return Declared()


async def main():
    selected = [DISCIPLINES["lol"]]
    broker = Broker()
    jobs.register_jobs(selected, broker, session_factory=object(), redis=object(), logger=type("L", (), {"info": lambda *a: None})())
    await jobs.start_jobs(selected, session_factory=object(), redis=object(), logger=type("L", (), {"info": lambda *a: None})())
    for closing in jobs.stop_jobs(selected):
        await closing
    return broker.queues


queues = asyncio.run(main())
print(json.dumps({"queues": sorted(queues), "overwatch": sorted(m for m in sys.modules if "overwatch.collector" in m)}))
"""
    )
    assert out == {
        "queues": sorted(
            [
                "lol_rank_fetch",
                "lol_rank_fetch_priority",
                "lol_rank_player_refresh",
            ]
        ),
        "overwatch": [],
    }


class _Broker:
    def __init__(self) -> None:
        self.subscribed: list[tuple[str, dict]] = []
        self.dlqs: list[str] = []

    async def declare_exchange(self, exchange):
        return exchange

    async def declare_queue(self, queue):
        name = queue.name
        dlqs = self.dlqs

        class _Declared:
            async def bind(self, exchange, routing_key):
                assert routing_key == name
                dlqs.append(name)

        return _Declared()

    def subscriber(self, queue, **kwargs):
        self.subscribed.append((queue.name, kwargs))
        return lambda fn: fn


class OverwatchJobsTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from shared.disciplines.overwatch.collector import scheduler, tasks

        self.closed: list[str] = []

        async def close() -> None:
            self.closed.append("closed")

        self.client = SimpleNamespace(start=AsyncMock(), close=close)
        for patcher in (
            patch.object(tasks, "rank_client", self.client),
            patch.object(scheduler, "start_scheduler", MagicMock()),
            patch.object(scheduler, "shutdown_scheduler", MagicMock()),
            patch.multiple(runtime, _session_factory=None, _redis=None, _broker=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scheduler = scheduler

    async def test_an_overwatch_worker_binds_the_rank_consumers_and_runs_the_collector(self) -> None:
        from shared.disciplines.overwatch.collector.settings import settings
        from shared.messaging.config import RANK_FETCH_PRIORITY_QUEUE, RANK_FETCH_QUEUE, RANK_PLAYER_REFRESH_QUEUE

        selected = [DISCIPLINES["overwatch"]]
        broker, session_factory, redis = _Broker(), object(), object()
        wiring = {"session_factory": session_factory, "redis": redis, "logger": MagicMock()}

        discipline_jobs.register_jobs(selected, broker, **wiring)
        by_queue = dict(broker.subscribed)
        self.assertEqual(
            set(by_queue),
            {
                RANK_FETCH_QUEUE.name,
                RANK_FETCH_PRIORITY_QUEUE.name,
                RANK_PLAYER_REFRESH_QUEUE.name,
            },
        )
        # OverFast-protective prefetch: both fetch queues share one channel sized by the collector setting.
        fetch_channel = by_queue[RANK_FETCH_QUEUE.name]["channel"]
        self.assertIs(fetch_channel, by_queue[RANK_FETCH_PRIORITY_QUEUE.name]["channel"])
        self.assertEqual(fetch_channel.prefetch_count, settings().rank_fetch_worker_prefetch)
        self.assertIs(runtime.session_factory(), session_factory)
        self.assertIs(runtime.redis(), redis)
        self.assertIs(runtime.broker(), broker)

        await discipline_jobs.start_jobs(selected, **wiring)
        # The module owns the dead-letter queues of the queues it consumes.
        self.assertEqual(
            set(broker.dlqs),
            {"rank_fetch.dlq", "rank_fetch_priority.dlq", RANK_PLAYER_REFRESH_QUEUE.name + ".dlq"},
        )
        self.client.start.assert_awaited_once()
        self.scheduler.start_scheduler.assert_called_once()

        closings = discipline_jobs.stop_jobs(selected)
        # Calling stop_jobs stops the schedules; the client stays open until the result is awaited.
        self.scheduler.shutdown_scheduler.assert_called_once()
        self.assertEqual(self.closed, [])
        for closing in closings:
            await closing
        self.assertEqual(self.closed, ["closed"])

    def test_collection_handlers_cover_the_module_handlers(self) -> None:
        self.assertEqual(
            set(DISCIPLINES["overwatch"].collection_handlers), {*handlers.HANDLERS, "impact.recompute_baselines"}
        )
        from shared.disciplines.lol import handlers as lol_handlers

        self.assertEqual(set(DISCIPLINES["lol"].collection_handlers), set(lol_handlers.HANDLERS))
