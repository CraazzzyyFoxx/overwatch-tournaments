from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))


mapping = importlib.import_module("src.services.overwatch_rank.mapping")
from shared.schemas.settings import RankMappingConfig, RankMappingEntry  # noqa: E402


class MappingTests(IsolatedAsyncioTestCase):
    def test_default_lookup_is_sr_aligned(self) -> None:
        lookup = mapping.build_default_lookup()
        # Tier 5 = bottom of division, tier 1 = top (+400).
        self.assertEqual(lookup[("bronze", 5)], 500)
        self.assertEqual(lookup[("bronze", 1)], 900)
        self.assertEqual(lookup[("emerald", 5)], 2500)
        # Diamond and above keep their v1 anchors: emerald took the band that
        # platinum vacated, so only bronze..platinum moved down by 500.
        self.assertEqual(lookup[("diamond", 3)], 3200)
        self.assertEqual(lookup[("ultimate", 1)], 4900)
        # 9 divisions x 5 tiers.
        self.assertEqual(len(lookup), 45)

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
        self.assertEqual(lookup[("bronze", 1)], 900)  # default kept

    async def test_get_rank_mapping_defaults_when_empty(self) -> None:
        with patch.object(
            mapping.settings_provider,
            "get_rank_mapping_config",
            # A stored version from an older table must not stamp default-derived rows.
            AsyncMock(return_value=RankMappingConfig(version="ow2-default-v1")),
        ):
            lookup, version = await mapping.get_rank_mapping(session=object())
        self.assertEqual(version, "ow2-default-v2")
        self.assertEqual(lookup[("gold", 5)], 1500)
