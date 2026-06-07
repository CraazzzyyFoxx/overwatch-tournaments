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
    async def test_live_health_payload(self) -> None:
        main = importlib.import_module("main")

        response = await main.live_health_check()

        self.assertEqual("tournament-service", response.service)
        self.assertEqual("ok", response.status)

    async def test_public_read_routes_are_registered(self) -> None:
        main = importlib.import_module("main")

        paths = {getattr(route, "path", "") for route in main.app.routes}

        self.assertIn("/tournaments/{id}", paths)
        self.assertIn("/tournaments/{id}/standings", paths)
        self.assertIn("/encounters/{id}", paths)
        self.assertIn("/encounters/{encounter_id}/submit-result", paths)
        self.assertIn("/encounters/{encounter_id}/map-pool/ws", paths)
        self.assertIn("/teams/{id}", paths)
        self.assertIn(
            "/tournaments/{tournament_id}/registration/form",
            paths,
        )
        self.assertIn(
            "/tournaments/{tournament_id}/registration/me",
            paths,
        )
        self.assertIn("/admin/tournaments", paths)
        self.assertIn("/admin/stages/tournament/{tournament_id}", paths)
        self.assertIn("/admin/stages/{stage_id}/merge-group-stages", paths)
        self.assertIn("/admin/tournament-jobs/{job_id}", paths)
        self.assertIn("/admin/teams", paths)
        self.assertIn("/admin/encounters/bulk", paths)
        self.assertIn("/admin/standings/recalculate/{tournament_id}", paths)
        self.assertIn("/admin/player-sub-roles", paths)
        self.assertIn("/admin/challonge/sync/import/{tournament_id}", paths)
        self.assertIn("/admin/balancer/tournaments/{tournament_id}/registration-form", paths)
        self.assertIn("/admin/balancer/tournaments/{tournament_id}/registrations", paths)
        self.assertIn("/admin/balancer/registrations/{registration_id}/approve", paths)
        self.assertIn("/admin/balancer/registrations/{registration_id}/check-in", paths)
        self.assertIn("/admin/balancer/tournaments/{tournament_id}/sheet/sync", paths)
        self.assertIn("/admin/balancer/tournaments/{tournament_id}/players/export", paths)
        self.assertIn("/admin/ws/{workspace_id}/balancer-statuses/catalog", paths)

    async def test_worker_queue_handlers_are_registered(self) -> None:
        worker = importlib.import_module("serve")
        bracket_worker = importlib.import_module("serve_bracket")
        standings_worker = importlib.import_module("serve_standings")

        self.assertTrue(callable(worker.drain_outbox))
        self.assertTrue(callable(worker.sync_registration_google_sheet_feeds))
        self.assertTrue(callable(bracket_worker.consume_bracket_job))
        self.assertTrue(callable(standings_worker.consume_standings_job))
