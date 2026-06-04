from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import TestCase

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ["DEBUG"] = "false"

from src.routes.admin import router as organizer_router  # noqa: E402


class BalancerRoutePrefixTests(TestCase):
    def test_organizer_routes_are_exposed_without_admin_prefix(self) -> None:
        paths = {route.path for route in organizer_router.routes}

        self.assertIn("/balancer/tournaments/{tournament_id}/sheet", paths)
        self.assertIn("/ws/{workspace_id}/balancer-statuses", paths)
        self.assertTrue(all(not path.startswith("/admin") for path in paths))

    def test_draft_routes_are_exposed(self) -> None:
        paths = {route.path for route in organizer_router.routes}
        # Public reads + admin lifecycle + pick actions, all under /draft.
        self.assertIn("/draft/tournaments/{tournament_id}/draft", paths)
        self.assertIn("/draft/sessions/{session_id}/board", paths)
        self.assertIn("/draft/tournaments/{tournament_id}/sessions/{session_id}/start", paths)
        self.assertIn("/draft/picks/{pick_id}/select", paths)
        self.assertIn("/draft/picks/{pick_id}/autopick", paths)
