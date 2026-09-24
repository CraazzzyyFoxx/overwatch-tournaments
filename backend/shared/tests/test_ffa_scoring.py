from __future__ import annotations

import pytest

from shared.domain.ffa_scoring import (
    FfaGameLine,
    FfaResultError,
    FfaRules,
    game_points,
    normalize_game_lines,
    parse_ffa_rules,
    team_totals,
)

SCORE_ONLY = FfaRules()
BATTLE_ROYALE = FfaRules(placement_points=(10, 6, 5), score_points=1)


def line(team_id: int, score: int, placement: int | None = None) -> FfaGameLine:
    return FfaGameLine(team_id=team_id, placement=placement, score=score)


def test_score_only_game_ranks_by_score_and_ties_share_a_place() -> None:
    lines = normalize_game_lines([line(1, 7), line(2, 10), line(3, 7), line(4, 3)], [1, 2, 3, 4], SCORE_ONLY)

    assert [(item.team_id, item.placement) for item in lines] == [(2, 1), (1, 2), (3, 2), (4, 4)]


def test_a_formula_that_pays_for_placement_needs_every_place_exactly_once() -> None:
    with pytest.raises(FfaResultError) as missing:
        normalize_game_lines([line(1, 3), line(2, 1)], [1, 2], BATTLE_ROYALE)
    with pytest.raises(FfaResultError) as shared_place:
        normalize_game_lines([line(1, 3, 1), line(2, 1, 1)], [1, 2], BATTLE_ROYALE)

    assert missing.value.code == "ffa_result_placement_required"
    assert shared_place.value.code == "ffa_result_invalid_placement"


def test_score_only_lobby_accepts_given_places_including_ties() -> None:
    lines = normalize_game_lines([line(1, 5, 1), line(2, 5, 1)], [1, 2], SCORE_ONLY)

    assert [item.placement for item in lines] == [1, 1]


@pytest.mark.parametrize(
    ("lines", "code"),
    [
        ([line(1, 1), line(2, 1), line(9, 1)], "ffa_result_unknown_team"),
        ([line(1, 1), line(1, 2), line(2, 1)], "ffa_result_duplicate_team"),
        ([line(1, 1)], "ffa_result_missing_team"),
        ([line(1, -1), line(2, 1)], "ffa_result_invalid_score"),
        ([line(1, 1, 1), line(2, 1)], "ffa_result_mixed_placement"),
        ([line(1, 1, 3), line(2, 1, 1)], "ffa_result_invalid_placement"),
    ],
)
def test_every_participant_is_accounted_for_exactly_once(lines: list[FfaGameLine], code: str) -> None:
    with pytest.raises(FfaResultError) as exc_info:
        normalize_game_lines(lines, [1, 2], SCORE_ONLY)

    assert exc_info.value.code == code


def test_game_points_add_the_placement_table_and_the_score() -> None:
    assert game_points(line(1, 4, 2), BATTLE_ROYALE) == 10
    # A place past the end of the table pays nothing; kills still count.
    assert game_points(line(1, 2, 9), BATTLE_ROYALE) == 2


def test_totals_seed_every_participant_and_track_placement_metrics() -> None:
    games = [
        normalize_game_lines([line(1, 3, 1), line(2, 5, 2), line(3, 0, 3)], [1, 2, 3], BATTLE_ROYALE),
        normalize_game_lines([line(1, 0, 3), line(2, 2, 1), line(3, 1, 2)], [1, 2, 3], BATTLE_ROYALE),
    ]

    totals = team_totals([1, 2, 3, 4], games, BATTLE_ROYALE)

    assert totals[1].points == 13 + 5 and totals[1].wins == 1 and totals[1].last_placement == 3
    assert totals[2].points == 11 + 12 and totals[2].best_placement == 1 and totals[2].score == 7
    assert totals[4].games == 0 and totals[4].points == 0


def test_rules_parse_from_stage_settings_and_default_to_score_only() -> None:
    assert parse_ffa_rules(None) == SCORE_ONLY
    assert parse_ffa_rules({"ffa_scoring": {"placement_points": [10, 6, 5], "score_points": 1}}) == BATTLE_ROYALE
