"""Seat plans from flow result rows: source / cross / snake (spec §5.3). Goldens are today's ``wire_from_groups`` orders."""

from types import SimpleNamespace

import pytest

from shared.core import enums
from shared.domain.flow.config import FilterNodeConfig
from src.domain.flow.compute import ResultRow, compute_filter
from src.domain.stage.seeds import SeatSource, SeedRanking, apply_seed_ranking, plan_seats

UB = SimpleNamespace(id=200, type=enums.StageItemType.BRACKET_UPPER, order=0)
LB = SimpleNamespace(id=201, type=enums.StageItemType.BRACKET_LOWER, order=1)


def standings(groups: int, per_group: int) -> list[ResultRow]:
    """A finished group stage: team = item*10 + place, ranked place-major like a stage output."""
    return [
        ResultRow(None, (100 + g) * 10 + r, stage_item_id=100 + g, item_rank=r)
        for r in range(1, per_group + 1)
        for g in range(groups)
    ]


def seat(filter_config: dict, groups: int, ranking: SeedRanking, *, de=False, items=(UB,)):
    order = {100 + g: g for g in range(groups)}
    passed = compute_filter(FilterNodeConfig.model_validate(filter_config), standings(groups, 6), item_order=order)
    sources = [
        SeatSource(i, r.team_id, r.stage_item_id, r.item_rank, (r.breakdown or {}).get("bracket") == "lower")
        for i, r in enumerate(passed.ports["passed"], 1)
    ]
    plan = plan_seats(
        sources,
        ranking=ranking,
        target_items=items,
        double_elimination=de,
        arrange_groups=True,
        source_item_order=order,
        rng_seed=1,
    )
    return {item: [(s.stage_item_id, s.item_rank) for s in seats] for item, seats in plan.items()}


GOLDEN = [
    (2, 2, SeedRanking.CROSS, [(100, 1), (101, 1), (100, 2), (101, 2)]),
    (2, 2, SeedRanking.SNAKE, [(100, 1), (101, 1), (100, 2), (101, 2)]),
    (2, 3, SeedRanking.CROSS, [(100, 1), (101, 1), (101, 2), (100, 2), (101, 3), (100, 3)]),
    (2, 3, SeedRanking.SNAKE, [(100, 1), (101, 1), (100, 2), (101, 2), (100, 3), (101, 3)]),
    (3, 2, SeedRanking.CROSS, [(100, 1), (101, 1), (102, 1), (102, 2), (101, 2), (100, 2)]),
    (
        4,
        2,
        SeedRanking.CROSS,
        [(100, 1), (101, 1), (102, 1), (103, 1), (102, 2), (101, 2), (100, 2), (103, 2)],
    ),
    (
        4,
        2,
        SeedRanking.SNAKE,
        [(100, 1), (101, 1), (102, 1), (103, 1), (100, 2), (101, 2), (102, 2), (103, 2)],
    ),
]


@pytest.mark.parametrize(("groups", "n", "ranking", "golden"), GOLDEN)
def test_filter_then_seat_matches_wire_from_groups(groups, n, ranking, golden):
    assert seat({"mode": "per_item_top", "n": n}, groups, ranking)[200] == golden


def test_uneven_groups_match_wire_from_groups():
    got = seat({"mode": "per_item_top", "n": 2, "per_item": {101: 1}}, 3, SeedRanking.CROSS)[200]
    assert got == [(100, 1), (101, 1), (102, 1), (102, 2), (100, 2)]


def test_double_elimination_split_matches_auto_wire():
    got = seat({"mode": "per_item_top", "n": 6, "upper": 2}, 2, SeedRanking.SNAKE, de=True, items=(UB, LB))
    assert got[200] == [(100, 1), (101, 1), (100, 2), (101, 2)]
    assert got[201] == [(100, 3), (101, 3), (100, 4), (101, 4), (100, 5), (101, 5), (100, 6), (101, 6)]


def test_double_elimination_without_a_lower_item_is_refused():
    with pytest.raises(ValueError, match="lower bracket item missing"):
        seat({"mode": "per_item_top", "n": 6, "upper": 2}, 2, SeedRanking.SNAKE, de=True)


def test_single_elimination_ignores_the_lower_flag():
    got = seat({"mode": "per_item_top", "n": 6, "upper": 2}, 2, SeedRanking.SNAKE)
    assert list(got) == [200] and len(got[200]) == 12


def test_source_keeps_the_input_order():
    got = seat({"mode": "per_item_top", "n": 2}, 2, SeedRanking.SOURCE)[200]
    assert got == [(100, 1), (101, 1), (100, 2), (101, 2)]


def test_group_targets_get_a_snake_deal():
    groups = [SimpleNamespace(id=300 + g, type=enums.StageItemType.GROUP, order=g) for g in range(2)]
    sources = [SeatSource(i, 10 + i, None, None) for i in range(1, 5)]
    plan = plan_seats(
        sources,
        ranking=SeedRanking.SOURCE,
        target_items=groups,
        double_elimination=False,
        arrange_groups=False,
        source_item_order={},
        rng_seed=1,
    )
    assert {k: [s.team_id for s in v] for k, v in plan.items()} == {300: [11, 14], 301: [12, 13]}


def test_generation_keeps_slot_order_for_seated_modes():
    for ranking in (SeedRanking.SOURCE, SeedRanking.CROSS, SeedRanking.SNAKE):
        assert apply_seed_ranking([3, 1, 2], {}, ranking, rng_seed=1) == [3, 1, 2]
