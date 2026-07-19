"""Unit tests for OW2 rank -> division resolution on a workspace grid."""

from __future__ import annotations

from shared.division_grid import DivisionGrid, DivisionTier
from shared.services.rank_snapshots import normalize_ow_ranks_to_grid


def _tier(number: int, name: str, rank_min: int, ow_lo: int, ow_hi: int) -> DivisionTier:
    return DivisionTier(
        id=number,
        slug=name.lower().replace(" ", "-"),
        number=number,
        name=name,
        rank_min=rank_min,
        rank_max=rank_min + 99,
        icon_url="",
        ow_rank_min=ow_lo,
        ow_rank_max=ow_hi,
    )


def _grid_with_inverted_top() -> DivisionGrid:
    # Mirrors a real workspace grid: the top divisions (Ultimate/Champion) were
    # entered high->low, so ow_rank_min > ow_rank_max; the diamond rows are low->high.
    tiers = [
        _tier(1, "Division 1", rank_min=2000, ow_lo=4900, ow_hi=4700),  # inverted: Ultimate 1 -> 3
        _tier(2, "Division 2", rank_min=1900, ow_lo=4700, ow_hi=4500),  # inverted: Ultimate 3 -> 5
        _tier(14, "Division 14", rank_min=700, ow_lo=3200, ow_hi=3300),  # normal: Diamond 3 -> 2
    ]
    return DivisionGrid(version_id=None, tiers=tiers)


def test_resolves_champion_rank_in_inverted_top_division() -> None:
    grid = _grid_with_inverted_top()

    # Champion 1 (SR 4900), Champion 2 (4800), Champion 3 (4700) all live in Division 1.
    for sr in (4900, 4800, 4700):
        tier = grid.resolve_division_from_ow_rank(sr)
        assert tier is not None
        assert tier.number == 1


def test_resolves_lower_ultimate_in_second_division() -> None:
    grid = _grid_with_inverted_top()
    tier = grid.resolve_division_from_ow_rank(4500)  # Ultimate 5
    assert tier is not None
    assert tier.number == 2


def test_resolves_normal_low_to_high_division() -> None:
    grid = _grid_with_inverted_top()
    tier = grid.resolve_division_from_ow_rank(3300)  # Diamond 2
    assert tier is not None
    assert tier.number == 14


def test_returns_none_outside_all_ranges() -> None:
    grid = _grid_with_inverted_top()
    assert grid.resolve_division_from_ow_rank(2000) is None  # below every OW range


def test_inverted_top_division_produces_ow_rank_value_for_delta() -> None:
    # End-to-end: a Champion player normalises to the top division's rank_min (2000),
    # so the rank-delta against a 700 registration is computed instead of dropped.
    grid = _grid_with_inverted_top()
    mapped = normalize_ow_ranks_to_grid({42: {"support": 4900}}, grid)
    assert mapped == {42: {"support": 2000}}


def _grid_without_ow_mapping() -> DivisionGrid:
    # A grid cloned from the default OW2 scale where the admin never configured
    # the per-tier OW ranges (ow_rank_min/max all NULL) — the common real case.
    tiers = [
        DivisionTier(id=n, slug=f"d{n}", number=n, name=f"D{n}", rank_min=rank_min, rank_max=rank_max, icon_url="")
        for n, (rank_min, rank_max) in enumerate(
            [(4900, None), (3000, 3099), (1000, 1099)],
            start=1,
        )
    ]
    return DivisionGrid(version_id=None, tiers=tiers)


def test_unconfigured_grid_falls_back_to_native_rank_containment() -> None:
    # No tier has an OW range: the OW rank_value shares the grid scale (the
    # parser's default mapping is SR-aligned), so it resolves by rank_min/max.
    grid = _grid_without_ow_mapping()
    assert grid.resolve_division_from_ow_rank(3050).number == 2  # inside 3000-3099
    assert grid.resolve_division_from_ow_rank(5200).number == 1  # unbounded top tier


def test_partially_configured_grid_does_not_fall_back() -> None:
    # One configured tier means the admin owns the OW mapping: ranks outside the
    # configured ranges return None instead of being misread as native-scale.
    tiers = list(_grid_without_ow_mapping().tiers)
    tiers[0] = _tier(1, "Top", rank_min=4900, ow_lo=4500, ow_hi=5000)
    grid = DivisionGrid(version_id=None, tiers=tiers)
    assert grid.resolve_division_from_ow_rank(4700).number == 1  # configured range wins
    assert grid.resolve_division_from_ow_rank(3050) is None  # unconfigured tier stays unreachable


def test_unconfigured_default_scale_maps_ow_ranks() -> None:
    # End-to-end with the shared normalizer: an unconfigured grid no longer
    # drops every OW rank (the regression behind the empty rank-autofill).
    grid = _grid_without_ow_mapping()
    mapped = normalize_ow_ranks_to_grid({42: {"support": 3050}}, grid)
    assert mapped == {42: {"support": 3000}}
