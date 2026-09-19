"""Unit tests for shared OW2 rank-snapshot grid normalisation."""

from __future__ import annotations

from shared.division_grid import DivisionGrid, DivisionTier
from shared.services.rank_snapshots import normalize_ow_ranks_to_grid


def _grid_with_ow_mapping() -> DivisionGrid:
    tiers = [
        DivisionTier(
            id=1,
            slug="gold-3",
            number=3,
            name="Gold 3",
            rank_min=2000,
            rank_max=2499,
            icon_url="",
            ow_rank_min=2000,
            ow_rank_max=2499,
        ),
        DivisionTier(
            id=2,
            slug="diamond-5",
            number=5,
            name="Diamond 5",
            rank_min=3000,
            rank_max=3499,
            icon_url="",
            ow_rank_min=3000,
            ow_rank_max=3499,
        ),
    ]
    return DivisionGrid(version_id=None, tiers=tiers)


def test_maps_raw_ow_sr_to_tier_rank_min() -> None:
    grid = _grid_with_ow_mapping()
    raw = {1: {"tank": 3200, "damage": 2100}}

    # 3200 -> Diamond 5 (rank_min 3000); 2100 -> Gold 3 (rank_min 2000).
    assert normalize_ow_ranks_to_grid(raw, grid) == {1: {"tank": 3000, "damage": 2000}}


def test_drops_ranks_outside_any_tier() -> None:
    grid = _grid_with_ow_mapping()
    assert normalize_ow_ranks_to_grid({1: {"support": 9999}}, grid) == {}


def _tier(number: int, rank_min: int, rank_max: int, ow: tuple[int, int] | None) -> DivisionTier:
    return DivisionTier(
        id=number,
        slug=f"tier-{number}",
        number=number,
        name=f"Tier {number}",
        rank_min=rank_min,
        rank_max=rank_max,
        icon_url="",
        ow_rank_min=ow[0] if ow else None,
        ow_rank_max=ow[1] if ow else None,
    )


def test_grid_without_any_ow_mapping_falls_back_to_the_native_scale() -> None:
    """An unmapped grid is the common case: cloned from the default OW2 scale and
    never filled in. Dropping every rank there would leave the whole workspace with
    no OW delta at all, so ``resolve_division_from_ow_rank`` treats the SR as already
    living on the grid's own scale and resolves it by ``rank_min``/``rank_max``."""
    grid = DivisionGrid(version_id=None, tiers=[_tier(3, 2000, 2499, None)])

    assert normalize_ow_ranks_to_grid({1: {"tank": 2100}}, grid) == {1: {"tank": 2000}}


def test_one_configured_tier_makes_the_admin_own_the_whole_mapping() -> None:
    """The fallback is all-or-nothing on purpose. As soon as one tier carries an
    explicit OW range, an unconfigured tier stays unreachable — otherwise a
    half-filled mapping would silently mix two scales in one grid."""
    grid = DivisionGrid(
        version_id=None,
        tiers=[_tier(5, 3000, 3499, (3000, 3499)), _tier(3, 2000, 2499, None)],
    )

    assert normalize_ow_ranks_to_grid({1: {"tank": 3200}}, grid) == {1: {"tank": 3000}}
    assert normalize_ow_ranks_to_grid({1: {"tank": 2100}}, grid) == {}


def test_empty_input_returns_empty() -> None:
    assert normalize_ow_ranks_to_grid({}, _grid_with_ow_mapping()) == {}
