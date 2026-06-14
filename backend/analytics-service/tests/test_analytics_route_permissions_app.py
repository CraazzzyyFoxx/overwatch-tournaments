from __future__ import annotations

import importlib
import os
from unittest import TestCase

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

analytics_routes = importlib.import_module("src.routes.analytics")


class AnalyticsRoutePermissionTests(TestCase):
    def test_change_shift_requires_analytics_update_permission(self) -> None:
        route = next(route for route in analytics_routes.router.routes if route.path == "/analytics/shift")
        dependency = route.dependant.dependencies[0].call
        closure_values = {cell.cell_contents for cell in dependency.__closure__ or []}

        self.assertIn("analytics", closure_values)
        self.assertIn("update", closure_values)

