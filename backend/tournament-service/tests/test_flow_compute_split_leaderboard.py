"""Split buckets and leaderboard pins (spec §5.4, §7.3)."""

import pytest
from pydantic import ValidationError

from shared.domain.flow.config import LeaderboardNodeConfig, LeaderboardPin, SplitNodeConfig
from src.domain.flow.compute import ResultRow, compute_leaderboard, compute_split

ROWS = [ResultRow(workspace_member_id=None, team_id=t) for t in (1, 2, 3, 4, 5, 6, 7)]


@pytest.mark.parametrize(
    ("buckets", "serpentine", "expected"),
    [
        ([{"name": "A", "size": 3}, {"name": "B", "size": None}], False, [[1, 2, 3], [4, 5, 6, 7]]),
        ([{"name": "A", "size": 2}, {"name": "B", "size": 2}], False, [[1, 2], [3, 4]]),
        (
            [{"name": "A", "size": None}, {"name": "B", "size": None}, {"name": "C", "size": None}],
            True,
            [[1, 6, 7], [2, 5], [3, 4]],
        ),
        ([{"name": "A", "size": 2}, {"name": "B", "size": None}], True, [[1, 4], [2, 3, 5, 6, 7]]),
    ],
)
def test_split(buckets, serpentine, expected):
    out = compute_split(SplitNodeConfig.model_validate({"buckets": buckets, "serpentine": serpentine}), ROWS)
    assert [[r.team_id for r in out.ports[f"bucket_{i}"]] for i in range(1, len(buckets) + 1)] == expected


def test_split_short_input_leaves_later_buckets_empty():
    config = SplitNodeConfig.model_validate({"buckets": [{"name": "A", "size": 8}, {"name": "B", "size": None}]})
    assert compute_split(config, ROWS).ports["bucket_2"] == []


def test_leaderboard_without_pins_passes_rows_through():
    rows = [ResultRow(None, 1, tie_group=1), ResultRow(None, 2, tie_group=1), ResultRow(None, 3)]
    out = compute_leaderboard(LeaderboardNodeConfig(), rows).ports["ranking"]
    assert [(r.team_id, r.tie_group) for r in out] == [(1, 1), (2, 1), (3, None)]


def test_a_pin_resolves_a_tie():
    rows = [ResultRow(None, 1, tie_group=1), ResultRow(None, 2, tie_group=1), ResultRow(None, 3)]
    config = LeaderboardNodeConfig(pins=[LeaderboardPin(participant_id=2, position=1)])
    out = compute_leaderboard(config, rows).ports["ranking"]
    assert [(r.team_id, r.tie_group) for r in out] == [(2, None), (1, None), (3, None)]


def test_pin_of_absent_participant_is_ignored():
    rows = [ResultRow(None, 1), ResultRow(None, 2)]
    config = LeaderboardNodeConfig(pins=[LeaderboardPin(participant_id=99, position=1)])
    assert [r.team_id for r in compute_leaderboard(config, rows).ports["ranking"]] == [1, 2]


def test_duplicate_pins_are_rejected():
    with pytest.raises(ValidationError, match="leaderboard_pin_duplicate"):
        LeaderboardNodeConfig.model_validate(
            {"pins": [{"participant_id": 1, "position": 1}, {"participant_id": 2, "position": 1}]}
        )
