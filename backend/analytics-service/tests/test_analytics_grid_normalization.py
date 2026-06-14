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
division_grid = importlib.import_module("shared.division_grid")


class AnalyticsGridNormalizationTests(TestCase):
    def test_division_delta_points_neutralizes_global_grid_shift(self) -> None:
        self.assertEqual(0, analytics_flows.division_delta_points(6, 6))
        self.assertEqual(100, analytics_flows.division_delta_points(6, 5))
        self.assertEqual(-100, analytics_flows.division_delta_points(5, 6))
        self.assertIsNone(analytics_flows.division_delta_points(None, 6))

    def test_rating_to_division_uses_runtime_grid_instead_of_legacy_formula(self) -> None:
        grid = division_grid.DivisionGrid(
            version_id=99,
            tiers=(
                division_grid.DivisionTier(
                    id=1,
                    slug="division-1",
                    number=1,
                    name="Division 1",
                    rank_min=2000,
                    rank_max=None,
                    icon_url="",
                ),
                division_grid.DivisionTier(
                    id=2,
                    slug="division-5",
                    number=5,
                    name="Division 5",
                    rank_min=1600,
                    rank_max=1999,
                    icon_url="",
                ),
                division_grid.DivisionTier(
                    id=3,
                    slug="division-8",
                    number=8,
                    name="Division 8",
                    rank_min=1400,
                    rank_max=1599,
                    icon_url="",
                ),
                division_grid.DivisionTier(
                    id=4,
                    slug="division-12",
                    number=12,
                    name="Division 12",
                    rank_min=0,
                    rank_max=1399,
                    icon_url="",
                ),
            ),
        )

        self.assertEqual(8, analytics_flows.rating_to_division(grid, 1500.0))
