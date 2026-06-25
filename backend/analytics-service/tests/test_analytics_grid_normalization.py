from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

analytics_flows = importlib.import_module("src.services.analytics.flows")


class AnalyticsGridNormalizationTests(TestCase):
    def test_division_delta_points_neutralizes_global_grid_shift(self) -> None:
        self.assertEqual(0, analytics_flows.division_delta_points(6, 6))
        self.assertEqual(100, analytics_flows.division_delta_points(6, 5))
        self.assertEqual(-100, analytics_flows.division_delta_points(5, 6))
        self.assertIsNone(analytics_flows.division_delta_points(None, 6))
