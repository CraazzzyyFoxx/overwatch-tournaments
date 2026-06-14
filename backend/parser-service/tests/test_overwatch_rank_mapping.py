from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "x")
os.environ.setdefault("CHALLONGE_API_KEY", "x")

mapping = importlib.import_module("src.services.overwatch_rank.mapping")
from shared.schemas.settings import RankMappingConfig, RankMappingEntry  # noqa: E402


class MappingTests(IsolatedAsyncioTestCase):
    def test_default_lookup_is_sr_aligned(self) -> None:
        lookup = mapping.build_default_lookup()
        # Tier 5 = bottom of division, tier 1 = top (+400).
        self.assertEqual(lookup[("bronze", 5)], 1000)
        self.assertEqual(lookup[("bronze", 1)], 1400)
        self.assertEqual(lookup[("diamond", 3)], 3200)
        self.assertEqual(lookup[("ultimate", 1)], 4900)
        # 8 divisions x 5 tiers.
        self.assertEqual(len(lookup), 40)

    def test_map_is_case_insensitive_and_null_safe(self) -> None:
        lookup = mapping.build_default_lookup()
        self.assertEqual(mapping.map_division_tier_to_rank_value("Diamond", 3, lookup), 3200)
        self.assertIsNone(mapping.map_division_tier_to_rank_value(None, None, lookup))
        self.assertIsNone(mapping.map_division_tier_to_rank_value("bronze", None, lookup))
        self.assertIsNone(mapping.map_division_tier_to_rank_value("unknown", 1, lookup))

    async def test_get_rank_mapping_overlays_overrides(self) -> None:
        override = RankMappingConfig(
            version="custom-v2",
            entries=[RankMappingEntry(division="Bronze", tier=5, rank_value=777)],
        )
        with patch.object(
            mapping.settings_provider,
            "get_rank_mapping_config",
            AsyncMock(return_value=override),
        ):
            lookup, version = await mapping.get_rank_mapping(session=object())

        self.assertEqual(version, "custom-v2")
        self.assertEqual(lookup[("bronze", 5)], 777)  # overridden
        self.assertEqual(lookup[("bronze", 1)], 1400)  # default kept

    async def test_get_rank_mapping_defaults_when_empty(self) -> None:
        with patch.object(
            mapping.settings_provider,
            "get_rank_mapping_config",
            AsyncMock(return_value=RankMappingConfig()),
        ):
            lookup, version = await mapping.get_rank_mapping(session=object())
        self.assertEqual(version, "ow2-default-v1")
        self.assertEqual(lookup[("gold", 5)], 2000)
