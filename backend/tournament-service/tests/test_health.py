from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")


class TournamentServiceSmokeTests(IsolatedAsyncioTestCase):
    # The HTTP service (main.py) is decommissioned — the worker (serve.py) is the
    # only entrypoint. Former smoke tests for the FastAPI app's health payload and
    # registered routes are gone; route coverage now lives in the gateway's Go
    # route/guard tests (gateway/internal/edge). The worker-entrypoint regressions
    # below remain the meaningful smoke checks.

    async def test_worker_queue_handlers_are_registered(self) -> None:
        worker = importlib.import_module("serve")

        self.assertTrue(callable(worker.drain_outbox))
        self.assertTrue(callable(worker.sync_registration_google_sheet_feeds))
        self.assertTrue(callable(worker.consume_bracket_job))
        self.assertTrue(callable(worker.consume_standings_job))

    async def test_worker_entrypoint_configures_cache(self) -> None:
        # Regression: the cashews cache is a process-global singleton. The API
        # (main) configures it, but the worker (serve) runs in its own process
        # where it was left unconfigured. After-commit cache invalidation then
        # raised cashews NotConfiguredError on every bracket/standings job.
        # The worker entrypoint must configure the cache like the API does.
        from cashews import cache

        recorded_prefixes: list[str | None] = []
        real_setup = cache.setup

        def _record_setup(*args: object, **kwargs: object) -> None:
            recorded_prefixes.append(kwargs.get("prefix"))  # type: ignore[arg-type]

        cache.setup = _record_setup  # type: ignore[assignment]
        try:
            worker = importlib.import_module("serve")
            importlib.reload(worker)
        finally:
            cache.setup = real_setup  # type: ignore[assignment]

        self.assertIn("fastapi:", recorded_prefixes)
        self.assertIn("backend:", recorded_prefixes)
