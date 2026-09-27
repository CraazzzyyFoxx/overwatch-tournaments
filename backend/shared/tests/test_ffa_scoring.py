"""FFA scoring: which game is valid, what it pays, and what a season totals to.

Pure, no session and no ORM row::

    uv run pytest shared/tests/test_ffa_scoring.py -v
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.domain.ffa_formula import compile_formula
from shared.domain.ffa_scoring import (
    FfaColumn,
    FfaGameLine,
    FfaResultError,
    FfaRules,
    ffa_rules,
    game_points,
    normalize_game_lines,
    team_totals,
)


def rules(formula: str, *columns: FfaColumn, placement_points: tuple[float, ...] = ()) -> FfaRules:
    used = columns or (FfaColumn(key="score", label="Счёт"),)
    return FfaRules(
        columns=used,
        placement_points=placement_points,
        formula=compile_formula(formula, [column.key for column in used]),
    )


KILLS = FfaColumn(key="kills", label="Kills")
DEATHS = FfaColumn(key="deaths", label="Deaths", public=False, better="lower")

BATTLE_ROYALE = rules("place_pts + kills", KILLS, placement_points=(10, 6, 5))
BY_SCORE = rules("kills * 2 - deaths", KILLS, DEATHS)


def line(team_id: int, placement: int | None = None, **stats: float) -> FfaGameLine:
    return FfaGameLine(team_id=team_id, placement=placement, stats=stats)


def test_placement_is_required_exactly_when_the_formula_reads_it() -> None:
    assert BATTLE_ROYALE.requires_placement is True
    assert BY_SCORE.requires_placement is False
    assert rules("teams - place").requires_placement is True


def test_places_are_derived_from_game_points_with_shared_places() -> None:
    # 10, 7, 7, 3 -> 1, 2, 2, 4: the points the formula paid, not a raw column.
    lines = normalize_game_lines(
        [
            line(1, kills=5, deaths=0),
            line(2, kills=3, deaths=1),
            line(3, kills=3, deaths=1),
            line(4, kills=1, deaths=0),
        ],
        [1, 2, 3, 4],
        BY_SCORE,
    )

    assert [(item.team_id, item.placement) for item in lines] == [(1, 1), (2, 2), (3, 2), (4, 4)]


def test_a_formula_that_pays_for_placement_needs_every_place_exactly_once() -> None:
    with pytest.raises(FfaResultError) as missing:
        normalize_game_lines([line(1, kills=3), line(2, kills=1)], [1, 2], BATTLE_ROYALE)
    with pytest.raises(FfaResultError) as shared_place:
        normalize_game_lines([line(1, 1, kills=3), line(2, 1, kills=1)], [1, 2], BATTLE_ROYALE)

    assert missing.value.code == "ffa_result_placement_required"
    assert shared_place.value.code == "ffa_result_invalid_placement"


def test_a_formula_that_ignores_placement_accepts_given_places_including_ties() -> None:
    lines = normalize_game_lines([line(1, 1, kills=5, deaths=0), line(2, 1, kills=5, deaths=0)], [1, 2], BY_SCORE)

    assert [item.placement for item in lines] == [1, 1]


@pytest.mark.parametrize(
    ("lines", "code"),
    [
        (
            [line(1, kills=1, deaths=0), line(2, kills=1, deaths=0), line(9, kills=1, deaths=0)],
            "ffa_result_unknown_team",
        ),
        (
            [line(1, kills=1, deaths=0), line(1, kills=2, deaths=0), line(2, kills=1, deaths=0)],
            "ffa_result_duplicate_team",
        ),
        ([line(1, kills=1, deaths=0)], "ffa_result_missing_team"),
        ([line(1, kills=1, deaths=0, assists=2), line(2, kills=1, deaths=0)], "ffa_result_unknown_stat"),
        ([line(1, kills=1), line(2, kills=1, deaths=0)], "ffa_result_missing_stat"),
        ([line(1, kills=-1, deaths=0), line(2, kills=1, deaths=0)], "ffa_result_invalid_stat"),
        ([line(1, kills=float("inf"), deaths=0), line(2, kills=1, deaths=0)], "ffa_result_invalid_stat"),
        ([line(1, kills=2e9, deaths=0), line(2, kills=1, deaths=0)], "ffa_result_invalid_stat"),
        ([line(1, 1, kills=1, deaths=0), line(2, kills=1, deaths=0)], "ffa_result_mixed_placement"),
        ([line(1, 3, kills=1, deaths=0), line(2, 1, kills=1, deaths=0)], "ffa_result_invalid_placement"),
    ],
)
def test_a_game_is_refused_with_the_code_the_client_branches_on(lines: list[FfaGameLine], code: str) -> None:
    with pytest.raises(FfaResultError) as exc_info:
        normalize_game_lines(lines, [1, 2], BY_SCORE)

    assert exc_info.value.code == code


def test_game_points_are_the_formula_rounded_to_four_places() -> None:
    thirds = rules("kills / 3", KILLS)

    assert game_points(line(1, 1, kills=10), thirds, 4) == 3.3333
    assert game_points(line(1, 2, kills=4), BATTLE_ROYALE, 4) == 10.0
    # A place past the end of the table pays nothing; kills still count.
    assert game_points(line(1, 9, kills=2), BATTLE_ROYALE, 4) == 2.0


def test_a_key_with_no_value_counts_as_zero() -> None:
    # A column added mid-stage must not break the games already played.
    later = rules("kills + assists", KILLS, FfaColumn(key="assists", label="Assists"))

    assert game_points(FfaGameLine(team_id=1, placement=1, stats={"kills": 4}), later, 3) == 4.0


def test_totals_sum_every_column_and_seed_the_whole_roster() -> None:
    games = [
        normalize_game_lines([line(1, 1, kills=3), line(2, 2, kills=5), line(3, 3, kills=0)], [1, 2, 3], BATTLE_ROYALE),
        normalize_game_lines([line(1, 3, kills=0), line(2, 1, kills=2), line(3, 2, kills=1)], [1, 2, 3], BATTLE_ROYALE),
    ]

    totals = team_totals([1, 2, 3, 4], games, BATTLE_ROYALE)

    assert totals[1].points == 13 + 5 and totals[1].wins == 1 and totals[1].last_placement == 3
    assert totals[2].points == 11 + 12 and totals[2].best_placement == 1
    assert totals[2].stats == {"kills": 7.0}
    assert totals[4].games == 0 and totals[4].points == 0 and totals[4].stats == {"kills": 0.0}


def test_no_stage_reads_as_one_score_column() -> None:
    default = ffa_rules(None)

    assert default.column_keys == ("score",)
    assert default.requires_placement is False
    assert game_points(FfaGameLine(team_id=1, placement=1, stats={"score": 7}), default, 3) == 7.0


def test_a_stage_without_columns_scores_placement_only() -> None:
    # An empty column list is a legal stage, not a missing one: a placement-only
    # league must not fall back to the score column and score everyone zero.
    stage = SimpleNamespace(ffa_columns=[], ffa_placement_points=[10, 6, 3], ffa_formula="place_pts")

    rules = ffa_rules(stage)

    assert rules.column_keys == ()
    assert rules.requires_placement is True
    assert game_points(FfaGameLine(team_id=1, placement=2, stats={}), rules, 3) == 6.0


def test_rules_read_the_stage_columns() -> None:
    stage = SimpleNamespace(
        ffa_columns=[
            {"key": "kills", "label": "Убийства"},
            {"key": "deaths", "label": "Смерти", "public": False, "better": "lower"},
        ],
        ffa_placement_points=[10, 6, 5],
        ffa_formula="place_pts + kills * 2 - deaths",
    )

    parsed = ffa_rules(stage)

    assert parsed.columns == (
        FfaColumn(key="kills", label="Убийства"),
        FfaColumn(key="deaths", label="Смерти", public=False, better="lower"),
    )
    assert parsed.placement_points == (10.0, 6.0, 5.0)
    assert parsed.requires_placement is True
    assert game_points(FfaGameLine(team_id=1, placement=2, stats={"kills": 3, "deaths": 1}), parsed, 4) == 11.0
