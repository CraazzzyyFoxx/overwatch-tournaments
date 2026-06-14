from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import pandas as pd

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ["DEBUG"] = "false"
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

feature_cache = importlib.import_module("src.services.ml.features.cache")


class FeatureCacheTests(IsolatedAsyncioTestCase):
    async def test_dataframe_cache_survives_memory_clear(self) -> None:
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            calls = 0

            async def build() -> pd.DataFrame:
                nonlocal calls
                calls += 1
                return pd.DataFrame({"player_id": [1], "value": [42.0]})

            async def fail_build() -> pd.DataFrame:
                raise AssertionError("disk cache was not used")

            with (
                patch.object(feature_cache.settings, "analytics_feature_cache_enabled", True),
                patch.object(feature_cache.settings, "analytics_feature_cache_dir", str(cache_dir)),
                patch.object(feature_cache.settings, "analytics_feature_cache_namespace", "test"),
                patch.object(feature_cache.settings, "analytics_feature_cache_ttl_seconds", 3600),
            ):
                feature_cache.clear_memory_cache()
                first = await feature_cache.get_or_build_dataframe(
                    "demo",
                    {"tournament_ids": (1, 2)},
                    build,
                )
                first.loc[0, "value"] = 999.0

                feature_cache.clear_memory_cache()
                second = await feature_cache.get_or_build_dataframe(
                    "demo",
                    {"tournament_ids": (1, 2)},
                    fail_build,
                )

            feature_cache.clear_memory_cache()

        self.assertEqual(1, calls)
        self.assertEqual(42.0, float(second.loc[0, "value"]))
