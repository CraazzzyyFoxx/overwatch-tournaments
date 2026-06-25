"""Tests for canonical OW division normalization (cross-workspace single scale).

See src/services/analytics/canonical_division.py: every analytics division is
mapped to the in-code standard grid (DEFAULT_GRID, 40-tier OW). Per source tier:
OW-rank binding when present, else proportional rescale of the division number.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

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
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

division_grid = importlib.import_module("shared.division_grid")
canonical = importlib.import_module("src.services.analytics.canonical_division")

DEFAULT_GRID = division_grid.DEFAULT_GRID


def _tier(tier_id, number, rank_min, rank_max, ow_min=None, ow_max=None):
    return division_grid.DivisionTier(
        id=tier_id,
        slug=f"t{tier_id}",
        number=number,
        name=f"T{number}",
        rank_min=rank_min,
        rank_max=rank_max,
        icon_url="",
        ow_rank_min=ow_min,
        ow_rank_max=ow_max,
    )


def _grid(version_id, tiers):
    return division_grid.DivisionGrid(version_id=version_id, tiers=tuple(tiers))


def _grid20(version_id=200):
    """20-tier ladder on a 100..2000 scale (like ws1 v2), no OW binding."""
    tiers = []
    for number in range(1, 21):
        rank_min = (21 - number) * 100  # number 1 -> 2000 (top), number 20 -> 100
        rank_max = None if number == 1 else rank_min + 99
        tiers.append(_tier(200 + number, number, rank_min, rank_max))
    return _grid(version_id, tiers)


def _grid_ow(version_id=300):
    """Single-tier grid whose tier carries an OW-rank binding (Gold-ish)."""
    return _grid(version_id, [_tier(301, 1, 1000, None, ow_min=2000, ow_max=2099)])


class CanonicalDivisionNumberTests(TestCase):
    def test_ow_binding_routes_through_canonical_ow_rank(self) -> None:
        expected = DEFAULT_GRID.resolve_division((2000 + 2099) // 2).number
        self.assertEqual(expected, canonical.canonical_division_number(_grid_ow(), 1500))

    def test_proportional_endpoints_span_full_canonical_range(self) -> None:
        grid = _grid20()
        # Top division (1) -> canonical top (1); bottom (20) -> canonical bottom (40).
        self.assertEqual(DEFAULT_GRID.min_division, canonical.canonical_division_number(grid, 2000))
        self.assertEqual(DEFAULT_GRID.max_division, canonical.canonical_division_number(grid, 150))

    def test_proportional_midpoint(self) -> None:
        grid = _grid20()
        # division number 10 of 20 -> round(1 + 9/19 * 39) = 19
        self.assertEqual(19, canonical.canonical_division_number(grid, 1150))

    def test_default_grid_is_identity(self) -> None:
        # A rank already on the OW SR scale resolves to its own OW division.
        for rank in (1000, 2500, 4900):
            self.assertEqual(
                DEFAULT_GRID.resolve_division(rank).number,
                canonical.canonical_division_number(DEFAULT_GRID, rank),
            )


class CanonicalDivForTests(TestCase):
    def test_none_and_unknown_version_fall_back_to_default_grid(self) -> None:
        expected = DEFAULT_GRID.resolve_division(2500).number
        self.assertEqual(expected, canonical.canonical_div_for({}, None, 2500))
        self.assertEqual(expected, canonical.canonical_div_for({}, 999, 2500))

    def test_uses_grid_for_known_version(self) -> None:
        grids = {200: _grid20()}
        self.assertEqual(
            canonical.canonical_division_number(_grid20(), 1150),
            canonical.canonical_div_for(grids, 200, 1150),
        )

    def test_assign_over_frame(self) -> None:
        grids = {200: _grid20(), 300: _grid_ow()}
        df = pd.DataFrame({"rank": [2000, 150, 1500], "version_id": [200, 200, 300]})
        canonical.assign_canonical_division(df, grids, rank_col="rank")
        self.assertEqual(
            [
                DEFAULT_GRID.min_division,
                DEFAULT_GRID.max_division,
                DEFAULT_GRID.resolve_division((2000 + 2099) // 2).number,
            ],
            df["div"].tolist(),
        )

    def test_div_stays_within_canonical_range(self) -> None:
        grids = {200: _grid20(), 300: _grid_ow()}
        valid = range(DEFAULT_GRID.min_division, DEFAULT_GRID.max_division + 1)
        for version_id, rank in [(200, 2000), (200, 150), (200, 1150), (300, 1500), (None, 2500)]:
            self.assertIn(canonical.canonical_div_for(grids, version_id, rank), valid)
