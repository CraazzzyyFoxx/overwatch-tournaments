"""Unit tests for normalising raw OW2 SR values into a workspace division grid."""

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

from shared.division_grid import DivisionGrid, DivisionTier  # noqa: E402
from src.services.admin.balancer import normalize_ow_ranks_to_grid  # noqa: E402


def _grid_with_ow_mapping() -> DivisionGrid:
    tiers = [
        DivisionTier(
            id=1, slug="gold-3", number=3, name="Gold 3", rank_min=2000, rank_max=2499,
            icon_url="", ow_rank_min=2000, ow_rank_max=2499,
        ),
        DivisionTier(
            id=2, slug="diamond-5", number=5, name="Diamond 5", rank_min=3000, rank_max=3499,
            icon_url="", ow_rank_min=3000, ow_rank_max=3499,
        ),
    ]
    return DivisionGrid(version_id=None, tiers=tiers)


class NormalizeOwRanksToGridTests(TestCase):
    def test_maps_raw_ow_sr_to_tier_rank_min(self) -> None:
        grid = _grid_with_ow_mapping()
        raw = {1: {"tank": 3200, "dps": 2100}}

        result = normalize_ow_ranks_to_grid(raw, grid)

        # 3200 -> Diamond 5 (rank_min 3000); 2100 -> Gold 3 (rank_min 2000).
        self.assertEqual(result, {1: {"tank": 3000, "dps": 2000}})

    def test_drops_ranks_outside_any_tier(self) -> None:
        grid = _grid_with_ow_mapping()
        raw = {1: {"support": 9999}}

        # Unmapped SR is dropped so ow_rank_value stays null and no delta is computed.
        self.assertEqual(normalize_ow_ranks_to_grid(raw, grid), {})

    def test_grid_without_ow_mapping_yields_nothing(self) -> None:
        tiers = [
            DivisionTier(
                id=1, slug="gold-3", number=3, name="Gold 3", rank_min=2000, rank_max=2499,
                icon_url="", ow_rank_min=None, ow_rank_max=None,
            )
        ]
        grid = DivisionGrid(version_id=None, tiers=tiers)

        self.assertEqual(normalize_ow_ranks_to_grid({1: {"tank": 2100}}, grid), {})

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(normalize_ow_ranks_to_grid({}, _grid_with_ow_mapping()), {})
