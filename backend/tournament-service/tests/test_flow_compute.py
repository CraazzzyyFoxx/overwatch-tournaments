"""Pure flow node functions (spec §5.4: filter top / per_item_top, merge; the other modes: test_flow_compute_filter)."""

from shared.domain.flow.config import FilterNodeConfig
from src.domain.flow.compute import ResultRow, compute_filter, compute_merge

A, B = 10, 20
ROWS = [
    ResultRow(None, 1, A, 1),
    ResultRow(None, 3, B, 1),
    ResultRow(None, 2, A, 2),
    ResultRow(None, 4, B, 2),
    ResultRow(None, 5, A, 3),
]
ORDER = {A: 0, B: 1}


def teams(rows):
    return [r.team_id for r in rows]


def test_top_keeps_the_first_n_in_order() -> None:
    assert teams(compute_filter(FilterNodeConfig(mode="top", n=3), ROWS, item_order=ORDER).ports["passed"]) == [1, 3, 2]


def test_per_item_top_orders_by_item_rank_then_item_order() -> None:
    shuffled = [ROWS[4], ROWS[3], ROWS[2], ROWS[1], ROWS[0]]
    assert teams(
        compute_filter(FilterNodeConfig(mode="per_item_top", n=2), shuffled, item_order=ORDER).ports["passed"]
    ) == [1, 3, 2, 4]


def test_per_item_overrides_the_default_and_zero_sends_nobody() -> None:
    config = FilterNodeConfig.model_validate({"mode": "per_item_top", "n": 2, "per_item": {str(A): 3, str(B): 0}})
    assert teams(compute_filter(config, ROWS, item_order=ORDER).ports["passed"]) == [1, 2, 5]


def test_a_filter_keeps_tie_groups() -> None:
    tied = [ResultRow(None, 1, tie_group=1), ResultRow(None, 2, tie_group=1), ResultRow(None, 3)]
    assert [
        r.tie_group for r in compute_filter(FilterNodeConfig(mode="top", n=2), tied, item_order={}).ports["passed"]
    ] == [1, 1]


def test_merge_concatenates_in_order_and_drops_later_duplicates() -> None:
    merged = compute_merge([[ResultRow(None, 1), ResultRow(None, 2)], [ResultRow(None, 2), ResultRow(None, 3)]])
    assert teams(merged) == [1, 2, 3]
