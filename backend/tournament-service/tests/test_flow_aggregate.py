"""``compute_aggregate``: modes, missing inputs, scoring presets, tie order, breakdown (spec §7.4)."""

from datetime import UTC, datetime

import pytest

from shared.domain.flow.config import AggregateNodeConfig
from src.domain.flow.aggregate import AggregateInput, compute_aggregate
from src.domain.flow.compute import ResultRow, participant_id


def p(member, score=None, **metrics):
    return ResultRow(workspace_member_id=member, team_id=None, score=score, breakdown=metrics or None)


def team(team_id, score=None, **metrics):
    return ResultRow(workspace_member_id=None, team_id=team_id, score=score, breakdown=metrics or None)


T1, T2, T3 = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 8, tzinfo=UTC), datetime(2026, 1, 15, tzinfo=UTC)
DAYS = [
    AggregateInput(11, [p(1), p(2), p(3)], True, T1),  # A1 B2 C3
    AggregateInput(12, [p(2), p(1), p(4)], True, T2),  # B1 A2 D3
    AggregateInput(13, [p(3), p(4)], True, T3),  # C1 D2 (A, B missing)
]
TABLE = {"preset": "placement_table", "table": {"1": 10, "2": 6, "3": 3}}


def agg(mode, n=None, score=TABLE, inputs=DAYS, members=None, unit="players"):
    config = AggregateNodeConfig.model_validate({"unit": unit, "score": score, "mode": mode, "n": n})
    out = compute_aggregate(config, inputs, members_by_team=members or {}).ports["ranking"]
    return [(participant_id(r), r.score, r.tie_group) for r in out]


@pytest.mark.parametrize(
    ("mode", "n", "expected"),
    [
        # A=10+6, B=6+10 are equal on best places (one 1st, one 2nd each) and both missing in the last completed
        # input (day 13), so they share tie_group 1.
        ("sum_all", None, [(1, 16, 1), (2, 16, 1), (3, 13, None), (4, 9, None)]),
        # Days 12 and 13 count: B=10, C=10; B has a 2nd place (day 11) C lacks, so B is first.
        ("sum_last_n", 2, [(2, 10, None), (3, 10, None), (4, 9, None), (1, 6, None)]),
        # Best 1: A, B and C score 10; C has no 2nd place, so it follows A and B, who tie.
        ("sum_best_n", 1, [(1, 10, 1), (2, 10, 1), (3, 10, None), (4, 6, None)]),
        ("average", None, [(1, 8, 1), (2, 8, 1), (3, 6.5, None), (4, 4.5, None)]),
    ],
)
def test_modes_with_missing_inputs(mode, n, expected):
    assert agg(mode, n) == expected


def test_formula_reads_place_and_participants():
    score = {"preset": "formula", "formula": "max(0, participants - place + 1) * 2"}
    assert agg("sum_all", score=score) == [(1, 10, 1), (2, 10, 1), (3, 6, None), (4, 4, None)]


def test_stage_points_reads_the_row_score():
    inputs = [AggregateInput(11, [p(1, score=9), p(2, score=4)], True, T1)]
    assert agg("sum_all", score={"preset": "stage_points"}, inputs=inputs) == [(1, 9, None), (2, 4, None)]


def test_formula_reads_stage_metrics_and_missing_ones_are_zero():
    inputs = [AggregateInput(11, [p(1, wins=3, buchholz=2.5), p(2, wins=1)], True, T1)]
    score = {"preset": "formula", "formula": "wins * 3 + buchholz + ffa_score"}
    assert agg("sum_all", score=score, inputs=inputs) == [(1, 11.5, None), (2, 3, None)]


def test_places_not_in_the_table_score_zero():
    inputs = [AggregateInput(11, [p(1), p(2), p(3), p(4)], True, T1)]
    assert agg("sum_all", inputs=inputs)[-1] == (4, 0, None)


def test_ties_break_on_best_places_then_last_input():
    table = {"preset": "placement_table", "table": {"1": 5, "2": 4, "3": 3}}
    inputs = [AggregateInput(11, [p(1), p(2), p(3)], True, T1), AggregateInput(12, [p(3), p(2), p(1)], True, T2)]
    # All total 8; B has no 1st, so last; A and C have one 1st and one 3rd each; C won the last day.
    assert [m for m, _, _ in agg("sum_all", score=table, inputs=inputs)] == [3, 1, 2]


def test_sum_last_n_puts_pending_inputs_last():
    inputs = [*DAYS, AggregateInput(14, [], False, None)]
    assert agg("sum_last_n", 2, inputs=inputs) == agg("sum_last_n", 2)


def test_teams_expand_to_non_substitute_members():
    inputs = [AggregateInput(11, [team(10), team(20)], True, T1)]
    out = agg(
        "sum_all",
        score={"preset": "placement_table", "table": {"1": 10, "2": 6}},
        inputs=inputs,
        members={10: [1, 2], 20: [4, 5]},
    )
    assert out == [(1, 10, 1), (2, 10, 1), (4, 6, 3), (5, 6, 3)]


def test_breakdown_marks_counted_inputs():
    config = AggregateNodeConfig.model_validate({"unit": "players", "score": TABLE, "mode": "sum_last_n", "n": 2})
    a = compute_aggregate(config, DAYS, members_by_team={}).ports["ranking"][-1]
    assert a.breakdown == [
        {"node_id": 11, "place": 1, "score": 10, "counted": False},
        {"node_id": 12, "place": 2, "score": 6, "counted": True},
    ]
