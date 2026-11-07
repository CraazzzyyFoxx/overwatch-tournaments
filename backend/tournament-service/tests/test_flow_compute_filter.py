"""Filter node in every mode, boundary ties and lower-bracket starters (spec §5.4, §8.2)."""

from dataclasses import replace

import pytest

from shared.domain.flow.config import FilterNodeConfig
from src.domain.flow.compute import ResultRow, compute_filter

ORDER = {100: 0, 101: 1}


def row(team, item, item_rank, tie=None, status=None):
    return ResultRow(
        workspace_member_id=None,
        team_id=team,
        stage_item_id=item,
        item_rank=item_rank,
        tie_group=tie,
        breakdown={"swiss_status": status} if status else None,
    )


# Overall rank order of the input: 10, 20, 11, 21, 12, 22.
ROWS = [row(10, 100, 1), row(20, 101, 1), row(11, 100, 2), row(21, 101, 2), row(12, 100, 3), row(22, 101, 3)]
# The shared tie_group of each mode's straddling pair.
TIE = {"top": 3, "range": 3, "per_item_top": 1}


@pytest.mark.parametrize(
    ("config", "expected", "tie"),
    [
        ({"mode": "top", "n": 3}, [10, 20, 11], False),
        ({"mode": "range", "from": 2, "to": 4}, [20, 11, 21], False),
        ({"mode": "per_item_top", "n": 2}, [10, 20, 11, 21], False),
        ({"mode": "per_item_top", "n": 2, "per_item": {101: 1}}, [10, 20, 11], False),
        ({"mode": "manual", "manual": [21, 10]}, [10, 21], False),
    ],
)
def test_filter_modes(config, expected, tie):
    out = compute_filter(FilterNodeConfig.model_validate(config), ROWS, item_order=ORDER)
    assert [r.team_id for r in out.ports["passed"]] == expected
    assert out.boundary_tie is tie


def test_swiss_status_keeps_the_status():
    rows = [row(10, 100, 1, status="qualified"), row(11, 100, 2), row(12, 100, 3, status="eliminated")]
    out = compute_filter(FilterNodeConfig(mode="swiss_status", swiss_status="qualified"), rows, item_order=ORDER)
    assert [r.team_id for r in out.ports["passed"]] == [10]


def test_top_n_past_the_end_keeps_everything():
    out = compute_filter(FilterNodeConfig(mode="top", n=10), ROWS, item_order=ORDER)
    assert len(out.ports["passed"]) == 6 and out.boundary_tie is False


@pytest.mark.parametrize(
    ("config", "tied_pair"),
    [
        ({"mode": "top", "n": 3}, (11, 21)),  # rank 3 and 4 share tie_group 3
        ({"mode": "range", "from": 4, "to": 6}, (11, 21)),
        ({"mode": "per_item_top", "n": 1}, (10, 11)),  # item 100 ranks 1 and 2 share tie_group 1
    ],
)
def test_a_tie_straddling_the_cut_is_a_boundary_tie(config, tied_pair):
    rows = [replace(r, tie_group=TIE[config["mode"]] if r.team_id in tied_pair else r.tie_group) for r in ROWS]
    out = compute_filter(FilterNodeConfig.model_validate(config), rows, item_order=ORDER)
    assert out.boundary_tie is True
    assert all(r.tie_group is not None for r in out.ports["passed"] if r.team_id in tied_pair)


def test_a_tie_inside_the_cut_is_not_a_boundary_tie():
    rows = [replace(r, tie_group=1) if r.team_id in (10, 20) else r for r in ROWS]
    assert compute_filter(FilterNodeConfig(mode="top", n=3), rows, item_order=ORDER).boundary_tie is False


def test_per_item_upper_flags_lower_starters():
    config = FilterNodeConfig(mode="per_item_top", n=3, upper=1, per_item_upper={101: 2})
    out = compute_filter(config, ROWS, item_order=ORDER).ports["passed"]
    lower = [r.team_id for r in out if (r.breakdown or {}).get("bracket") == "lower"]
    assert lower == [11, 12, 22]


def test_top_upper_sends_the_rest_of_the_passed_to_the_lower_bracket():
    out = compute_filter(FilterNodeConfig(mode="top", n=5, upper=3), ROWS, item_order=ORDER).ports["passed"]
    assert [r.team_id for r in out] == [10, 20, 11, 21, 12]
    assert [r.team_id for r in out if (r.breakdown or {}).get("bracket") == "lower"] == [21, 12]
