"""Unit tests for shared OW2 rank-snapshot grid normalisation."""

from __future__ import annotations

from shared.division_grid import DivisionGrid, DivisionTier
from shared.services.rank_snapshots import normalize_ow_ranks_to_grid


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


def test_maps_raw_ow_sr_to_tier_rank_min() -> None:
    grid = _grid_with_ow_mapping()
    raw = {1: {"tank": 3200, "dps": 2100}}

    # 3200 -> Diamond 5 (rank_min 3000); 2100 -> Gold 3 (rank_min 2000).
    assert normalize_ow_ranks_to_grid(raw, grid) == {1: {"tank": 3000, "dps": 2000}}


def test_drops_ranks_outside_any_tier() -> None:
    grid = _grid_with_ow_mapping()
    assert normalize_ow_ranks_to_grid({1: {"support": 9999}}, grid) == {}


def test_grid_without_ow_mapping_yields_nothing() -> None:
    tiers = [
        DivisionTier(
            id=1, slug="gold-3", number=3, name="Gold 3", rank_min=2000, rank_max=2499,
            icon_url="", ow_rank_min=None, ow_rank_max=None,
        )
    ]
    grid = DivisionGrid(version_id=None, tiers=tiers)
    assert normalize_ow_ranks_to_grid({1: {"tank": 2100}}, grid) == {}


def test_empty_input_returns_empty() -> None:
    assert normalize_ow_ranks_to_grid({}, _grid_with_ow_mapping()) == {}
