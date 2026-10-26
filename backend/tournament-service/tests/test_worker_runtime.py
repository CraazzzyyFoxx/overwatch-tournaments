"""The worker entrypoint's runtime guarantees (``serve.py``).

- At most 4 compute jobs run at once, across all three compute queues. The jobs channel's prefetch is per consumer,
  so bracket, standings and division-grid import could each hold 4 deliveries: 12 CPU-heavy jobs on the RPC event
  loop. One shared semaphore in the consumers is the process cap.
- Shutdown closes the Redis/quota clients only after the broker has stopped: the handlers it lets finish still
  publish through them. They used to be closed before ``broker.stop()``.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


class WorkerRuntimeTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.worker = importlib.import_module("serve")

    async def test_three_compute_queues_share_four_running_slots(self) -> None:
        worker = self.worker
        release = asyncio.Event()
        running = 0
        peak = 0

        async def job(_job_id: int) -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await release.wait()
            running -= 1

        with (
            patch.object(worker, "process_bracket_job", job),
            patch.object(worker, "process_standings_job", job),
            patch.object(worker, "process_import_job", job),
        ):
            consumers = (
                worker.consume_bracket_job,
                worker.consume_standings_job,
                worker.consume_division_grid_import_job,
            )
            tasks = [asyncio.create_task(consume({"job_id": n}, None)) for n in range(4) for consume in consumers]
            for _ in range(20):
                await asyncio.sleep(0)
            self.assertEqual(4, running)

            release.set()
            await asyncio.gather(*tasks)

        self.assertEqual(4, peak)
        self.assertEqual(0, running)

    async def test_clients_close_after_the_broker_stopped(self) -> None:
        worker = self.worker
        order: list[str] = []

        def record(name: str):
            async def step(*_args: object, **_kwargs: object) -> None:
                order.append(name)

            return step

        with (
            patch.object(worker.scheduler, "shutdown", lambda **_kwargs: order.append("scheduler")),
            patch.object(worker.broker, "stop", record("broker")),
            patch.object(worker, "close_realtime_redis", record("realtime_redis")),
            patch.object(worker.challonge_sync, "close_redis", record("challonge_redis")),
            patch.object(worker, "close_quota", record("quota")),
        ):
            await worker.app.stop()

        self.assertEqual(["scheduler", "broker", "realtime_redis", "challonge_redis", "quota"], order)
