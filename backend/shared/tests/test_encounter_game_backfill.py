from datetime import UTC, datetime

from shared.domain.encounter_game_backfill import (
    EncounterSides,
    LegacyCaptainMatch,
    LegacyReport,
    plan_games,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
SIDES = {1: EncounterSides(home_team_id=10, away_team_id=20)}


def test_positioned_agreeing_reports_become_one_confirmed_game() -> None:
    plan = plan_games(
        [
            LegacyReport(id=1, encounter_id=1, map_id=5, map_index=1, team_id=10, home_score=2, away_score=1, created_at=T0),
            LegacyReport(id=2, encounter_id=1, map_id=5, map_index=1, team_id=20, home_score=2, away_score=1, created_at=T0),
        ],
        [],
        SIDES,
    )
    assert plan.conflicts == []
    [game] = plan.games
    assert (game.encounter_id, game.position, game.map_id, game.state) == (1, 1, 5, "confirmed")
    assert (game.accepted_home_score, game.accepted_away_score) == (2, 1)
    assert plan.report_keys == {1: (game.key, "home"), 2: (game.key, "away")}


def test_disagreeing_reports_make_a_disputed_game_and_one_side_awaits() -> None:
    plan = plan_games(
        [
            LegacyReport(id=1, encounter_id=1, map_id=5, map_index=1, team_id=10, home_score=2, away_score=1, created_at=T0),
            LegacyReport(id=2, encounter_id=1, map_id=5, map_index=1, team_id=20, home_score=1, away_score=2, created_at=T0),
            LegacyReport(id=3, encounter_id=1, map_id=6, map_index=2, team_id=10, home_score=2, away_score=0, created_at=T0),
        ],
        [],
        SIDES,
    )
    assert [g.state for g in plan.games] == ["disputed", "awaiting_result"]


def test_captain_only_match_without_reports_becomes_a_confirmed_game() -> None:
    plan = plan_games(
        [],
        [LegacyCaptainMatch(id=77, encounter_id=1, map_id=5, map_index=2, home_score=1, away_score=0, created_at=T0)],
        SIDES,
    )
    [game] = plan.games
    assert (game.position, game.state, game.accepted_home_score) == (2, "confirmed", 1)
    assert plan.deleted_match_ids == [77]


def test_one_report_plus_captain_match_is_confirmed_from_the_match() -> None:
    plan = plan_games(
        [
            LegacyReport(id=1, encounter_id=1, map_id=5, map_index=2, team_id=10, home_score=0, away_score=1, created_at=T0),
        ],
        [LegacyCaptainMatch(id=77, encounter_id=1, map_id=5, map_index=2, home_score=1, away_score=0, created_at=T0)],
        SIDES,
    )
    assert plan.conflicts == []
    [game] = plan.games
    assert (game.state, game.accepted_home_score, game.accepted_away_score) == ("confirmed", 1, 0)
    assert game.confirmed_at == T0
    assert plan.report_keys == {1: (game.key, "home")}
    assert plan.deleted_match_ids == [77]


def test_legacy_zero_index_rows_are_ordered_after_explicit_positions_by_creation() -> None:
    plan = plan_games(
        [
            LegacyReport(id=1, encounter_id=1, map_id=5, map_index=0, team_id=10, home_score=1, away_score=0, created_at=T0),
            LegacyReport(id=2, encounter_id=1, map_id=5, map_index=0, team_id=20, home_score=1, away_score=0, created_at=T0),
            LegacyReport(id=3, encounter_id=1, map_id=6, map_index=0, team_id=10, home_score=0, away_score=1, created_at=T0.replace(day=2)),
        ],
        [],
        SIDES,
    )
    assert [(g.position, g.map_id) for g in plan.games] == [(1, 5), (2, 6)]


def test_same_map_twice_without_positions_is_a_conflict_not_a_guess() -> None:
    plan = plan_games(
        [
            LegacyReport(id=1, encounter_id=1, map_id=5, map_index=0, team_id=10, home_score=1, away_score=0, created_at=T0),
            LegacyReport(id=2, encounter_id=1, map_id=5, map_index=0, team_id=10, home_score=0, away_score=1, created_at=T0.replace(day=2)),
        ],
        [],
        SIDES,
    )
    assert plan.conflicts and "encounter 1" in plan.conflicts[0]


def test_report_from_a_team_no_longer_in_the_encounter_is_an_orphan() -> None:
    plan = plan_games(
        [LegacyReport(id=9, encounter_id=1, map_id=5, map_index=1, team_id=99, home_score=1, away_score=0, created_at=T0)],
        [],
        SIDES,
    )
    assert plan.orphan_report_ids == [9]
    assert plan.games == []
