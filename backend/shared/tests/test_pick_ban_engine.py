"""Unit tests for what stayed in ``shared.domain.pick_ban_engine`` after the
ruleset-v2 cutover: the round arithmetic, result-dependent rotation (including
the ``elect_opener`` gate), per-map report reconciliation and series scoring.

The step vocabulary, cursor, undo target and eligibility moved to
``shared.domain.pick_ban_rules`` and are covered by that package's suites.
"""

from types import SimpleNamespace

import pytest

from shared.core import enums
from shared.domain import pick_ban_engine as engine


def entry(
    item_id: int,
    *,
    round: int | None = None,
    status: str = "available",
    picked_by: str | None = None,
    protected_by: str | None = None,
    action_index: int | None = None,
):
    return SimpleNamespace(
        item_id=item_id,
        round=round,
        status=status,
        picked_by=picked_by,
        protected_by=protected_by,
        action_index=action_index,
    )


# ── current_round ───────────────────────────────────────────────────────────


def test_current_round_is_lowest_round_with_an_available_entry():
    pool = [entry(1, round=2), entry(2, round=1), entry(3, round=1, status="banned")]
    assert engine.current_round(pool) == 1


def test_current_round_none_for_flat_pool():
    pool = [entry(1, round=None), entry(2, round=None, status="banned")]
    assert engine.current_round(pool) is None


# ── resolve_round_opener (result-dependent rotation) ────────────────────────


def test_round_one_always_uses_session_first_side_regardless_of_rotation():
    for rotation in enums.FirstBanRotation:
        side = engine.resolve_round_opener(
            rotation=rotation,
            round_number=1,
            session_first_side="away",
            previous_round_outcome=None,
            previous_round_loser_choice=None,
        )
        assert side == "away"


def test_fixed_rotation_keeps_the_same_opener_every_round():
    side = engine.resolve_round_opener(
        rotation=enums.FirstBanRotation.FIXED,
        round_number=3,
        session_first_side="home",
        previous_round_outcome="away",
        previous_round_loser_choice=None,
    )
    assert side == "home"


def test_alternate_rotation_flips_each_round():
    opener_r2 = engine.resolve_round_opener(
        rotation=enums.FirstBanRotation.ALTERNATE,
        round_number=2,
        session_first_side="home",
        previous_round_outcome=None,
        previous_round_loser_choice=None,
    )
    opener_r3 = engine.resolve_round_opener(
        rotation=enums.FirstBanRotation.ALTERNATE,
        round_number=3,
        session_first_side="home",
        previous_round_outcome=None,
        previous_round_loser_choice=None,
    )
    assert opener_r2 == "away"
    assert opener_r3 == "home"


def test_result_winner_first_uses_previous_winner():
    side = engine.resolve_round_opener(
        rotation=enums.FirstBanRotation.RESULT_WINNER_FIRST,
        round_number=2,
        session_first_side="home",
        previous_round_outcome="away",
        previous_round_loser_choice=None,
    )
    assert side == "away"


def test_result_loser_first_uses_opposite_of_previous_winner():
    side = engine.resolve_round_opener(
        rotation=enums.FirstBanRotation.RESULT_LOSER_FIRST,
        round_number=2,
        session_first_side="home",
        previous_round_outcome="away",
        previous_round_loser_choice=None,
    )
    assert side == "home"


def test_result_dependent_rotation_requires_a_previous_outcome():
    with pytest.raises(ValueError, match="previous_round_outcome is required"):
        engine.resolve_round_opener(
            rotation=enums.FirstBanRotation.RESULT_WINNER_FIRST,
            round_number=2,
            session_first_side="home",
            previous_round_outcome=None,
            previous_round_loser_choice=None,
        )


def test_result_rotations_fall_back_to_the_snapshot_side_on_a_draw() -> None:
    for rotation in (
        enums.FirstBanRotation.RESULT_WINNER_FIRST,
        enums.FirstBanRotation.RESULT_LOSER_FIRST,
        enums.FirstBanRotation.RESULT_LOSER_CHOICE,
    ):
        assert (
            engine.resolve_round_opener(
                rotation=rotation,
                round_number=2,
                session_first_side="away",
                previous_round_outcome="draw",
                previous_round_loser_choice=None,
            )
            == "away"
        )


def test_result_rotations_refuse_a_pending_outcome() -> None:
    with pytest.raises(ValueError):
        engine.resolve_round_opener(
            rotation=enums.FirstBanRotation.RESULT_LOSER_FIRST,
            round_number=2,
            session_first_side="home",
            previous_round_outcome=None,
            previous_round_loser_choice=None,
        )


def test_result_loser_choice_raises_needs_choice_when_unresolved():
    with pytest.raises(engine.RotationNeedsChoice):
        engine.resolve_round_opener(
            rotation=enums.FirstBanRotation.RESULT_LOSER_CHOICE,
            round_number=2,
            session_first_side="home",
            previous_round_outcome="away",
            previous_round_loser_choice=None,
        )


def test_result_loser_choice_returns_the_elected_side_once_chosen():
    side = engine.resolve_round_opener(
        rotation=enums.FirstBanRotation.RESULT_LOSER_CHOICE,
        round_number=2,
        session_first_side="home",
        previous_round_outcome="away",
        previous_round_loser_choice="home",
    )
    assert side == "home"


# ── reconcile_map_reports / map_outcome ──────────────────────────────────────


def test_reconcile_map_reports_waits_when_one_side_missing():
    result = engine.reconcile_map_reports(engine.MapReportPair(home_report=(2, 1), away_report=None))
    assert result.resolved is None
    assert result.disputed is False


def test_reconcile_map_reports_resolves_on_agreement():
    result = engine.reconcile_map_reports(engine.MapReportPair(home_report=(2, 1), away_report=(2, 1)))
    assert result.resolved == (2, 1)
    assert result.disputed is False


def test_reconcile_map_reports_disputes_on_mismatch():
    result = engine.reconcile_map_reports(engine.MapReportPair(home_report=(2, 1), away_report=(1, 2)))
    assert result.resolved is None
    assert result.disputed is True


def test_map_outcome_home():
    assert engine.map_outcome(2, 1) == "home"


def test_map_outcome_away():
    assert engine.map_outcome(0, 1) == "away"


def test_map_outcome_draw_on_a_level_score():
    assert engine.map_outcome(0, 0) == "draw"


# ── series_score / series_complete ───────────────────────────────────────────


def test_series_score_counts_wins_and_played_positions_separately() -> None:
    score = engine.series_score([(3, 1), (2, 2), (0, 2)])
    assert (score.home_wins, score.away_wins, score.played) == (1, 1, 3)


def test_series_complete_by_positions_and_by_majority() -> None:
    assert engine.series_complete(engine.SeriesScore(1, 1, 2), best_of=2)  # Bo2 1:1 ends
    assert engine.series_complete(engine.SeriesScore(2, 0, 2), best_of=3)  # majority
    assert not engine.series_complete(engine.SeriesScore(1, 1, 2), best_of=3)
    assert not engine.series_complete(engine.SeriesScore(1, 0, 1), best_of=2)  # Bo2 1:0 has a map left
    assert engine.series_complete(engine.SeriesScore(1, 1, 3), best_of=3)  # a draw used the last position
