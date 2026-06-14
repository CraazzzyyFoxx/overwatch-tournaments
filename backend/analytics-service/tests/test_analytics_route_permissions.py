from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["PROJECT_URL"] = "http://localhost"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["POSTGRES_USER"] = "postgres"
os.environ["POSTGRES_PASSWORD"] = "postgres"
os.environ["POSTGRES_DB"] = "postgres"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["DEBUG"] = "false"
os.environ["ENVIRONMENT"] = "development"
os.environ["S3_ACCESS_KEY"] = "test"
os.environ["S3_SECRET_KEY"] = "test"
os.environ["S3_ENDPOINT_URL"] = "http://localhost"
os.environ["S3_BUCKET_NAME"] = "test"
os.environ["CHALLONGE_USERNAME"] = "test"
os.environ["CHALLONGE_API_KEY"] = "test"

module_path = backend_root / "parser-service" / "src" / "routes" / "analytics.py"
module_spec = importlib.util.spec_from_file_location("parser_analytics_routes", module_path)
assert module_spec and module_spec.loader
analytics_routes = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(analytics_routes)


class AnalyticsRoutePermissionTests(TestCase):
    def test_recalculate_requires_analytics_update_permission(self) -> None:
        route = next(route for route in analytics_routes.router.routes if route.path == "/analytics/recalculate")
        dependency = route.dependant.dependencies[0].call
        closure_values = {cell.cell_contents for cell in dependency.__closure__ or []}

        self.assertIn("analytics", closure_values)
        self.assertIn("update", closure_values)
