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

from src.core import auth  # noqa: E402

module_path = backend_root / "parser-service" / "src" / "routes" / "admin" / "user.py"
module_spec = importlib.util.spec_from_file_location("parser_admin_user_routes", module_path)
assert module_spec and module_spec.loader
admin_user_routes = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(admin_user_routes)


class AdminUserMergeRoutePermissionTests(TestCase):
    def test_merge_preview_requires_superuser(self) -> None:
        route = next(route for route in admin_user_routes.router.routes if route.path == "/users/merge/preview")
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        self.assertIn(auth.get_current_superuser, dependency_calls)

    def test_merge_execute_requires_superuser(self) -> None:
        route = next(route for route in admin_user_routes.router.routes if route.path == "/users/merge/execute")
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        self.assertIn(auth.get_current_superuser, dependency_calls)
