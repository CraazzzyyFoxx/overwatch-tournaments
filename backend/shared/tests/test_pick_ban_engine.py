"""Unit tests for the generic pick-ban engine (``shared.domain.pick_ban_engine``).

Pure-function tests, no DB — see the module docstring for why. Covers the
behavior that is NEW relative to the existing map-veto engine: ledger
exclusion, role-uniqueness, protect immunity, result-dependent rotation
(including the ``elect_opener`` gate) and per-map report reconciliation.
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


# ── parse_step_token / resolve_sequence_tokens ──────────────────────────────


def test_parse_step_token_decider():
    parsed = engine.parse_step_token("decider")
    assert parsed.action == "decider"
    assert parsed.side is None


@pytest.mark.parametrize(
    ("token", "action", "side"),
    [
        ("ban_home", "ban", "home"),
        ("ban_away", "ban", "away"),
        ("pick_home", "pick", "home"),
        ("protect_away", "protect", "away"),
    ],
)
def test_parse_step_token_actions(token, action, side):
    parsed = engine.parse_step_token(token)
    assert parsed.action == action
    assert parsed.side == side


def test_resolve_sequence_tokens_maps_first_second_to_home_away():
    resolved = engine.resolve_sequence_tokens(
        ["ban_first", "ban_second", "protect_second", "decider"], enums.MapPickSide.AWAY
    )
    assert resolved == ["ban_away", "ban_home", "protect_home", "decider"]


def test_parse_step_token_without_separator_defaults_to_ban_home():
    """A poll used to 500 here: ``action, side = token.split('_', 1)`` on ``'ban'``."""
    parsed = engine.parse_step_token("ban")
    assert parsed.action == "ban"
    assert parsed.side == "home"


def test_resolve_sequence_tokens_rejects_a_token_without_separator():
    with pytest.raises(ValueError, match="invalid sequence token"):
        engine.resolve_sequence_tokens(["ban"], enums.MapPickSide.HOME)


def test_resolve_sequence_tokens_rejects_a_non_string_token():
    with pytest.raises(ValueError, match="invalid sequence token"):
        engine.resolve_sequence_tokens([None], enums.MapPickSide.HOME)  # type: ignore[list-item]


# ── current_round / in_current_round / is_entry_bannable ────────────────────


def test_current_round_is_lowest_round_with_an_available_entry():
    pool = [entry(1, round=2), entry(2, round=1), entry(3, round=1, status="banned")]
    assert engine.current_round(pool) == 1


def test_current_round_none_for_flat_pool():
    pool = [entry(1, round=None), entry(2, round=None, status="banned")]
    assert engine.current_round(pool) is None


def test_is_entry_bannable_false_when_protected():
    e = entry(1, round=1, protected_by="home")
    assert engine.is_entry_bannable(e, active_round=1) is False


def test_is_entry_bannable_false_outside_active_round():
    e = entry(1, round=2)
    assert engine.is_entry_bannable(e, active_round=1) is False


def test_is_entry_bannable_true_when_available_unprotected_in_round():
    e = entry(1, round=1)
    assert engine.is_entry_bannable(e, active_round=1) is True


# ── undoable_entries (both captains agree to take the last action back) ──────


def test_undoable_entries_is_empty_without_a_committed_action():
    assert engine.undoable_entries([]) == []
    assert engine.undoable_entries([entry(1, round=1)]) == []


def test_undoable_entries_returns_only_the_last_action():
    first = entry(1, round=1, status="banned", picked_by="home", action_index=0)
    last = entry(2, round=1, status="banned", picked_by="away", action_index=1)
    assert engine.undoable_entries([first, last, entry(3, round=1)]) == [last]


def test_undoable_entries_carries_the_decider_it_triggered():
    # The decider is not an action anybody took: the engine resolves it the
    # moment the sequence reaches that step, so undoing the ban without it
    # would leave the next read resolving the decider straight back.
    ban = entry(1, round=1, status="banned", picked_by="home", action_index=0)
    decided = entry(2, round=1, status="picked", picked_by="decider", action_index=1)
    assert engine.undoable_entries([ban, decided]) == [decided, ban]


def test_undoable_entries_is_empty_when_only_deciders_were_committed():
    decided = entry(1, round=1, status="picked", picked_by="decider", action_index=0)
    assert engine.undoable_entries([decided]) == []


def test_undoable_entries_no_longer_knows_about_played_maps():
    # "this map already has a result" is the undo service's call now (it reads
    # the game's state/claims), not the pool's business: a picked entry with a
    # trailing action in the same round is undoable while no later round exists.
    picked = entry(1, round=1, status="picked", picked_by="home", action_index=0)
    ban = entry(2, round=1, status="banned", picked_by="away", action_index=1)
    assert engine.undoable_entries([picked, ban]) == [ban]


def test_undoable_entries_is_empty_when_a_later_round_is_open():
    # Round 2 only exists because round 1's map was played and reported, so
    # round 1's trailing ban is behind that barrier even though round 2 has
    # nothing committed yet.
    ban = entry(1, round=1, status="banned", picked_by="home", action_index=0)
    assert engine.undoable_entries([ban, entry(2, round=2)]) == []


def test_undoable_entries_works_on_a_flat_pool():
    ban = entry(1, status="banned", picked_by="home", action_index=0)
    assert engine.undoable_entries([ban, entry(2)]) == [ban]


# ── excluded_item_ids (ledger no-repeat) ─────────────────────────────────────


def test_excluded_item_ids_none_scope_excludes_nothing():
    ledger = [engine.LedgerRow(item_id=1, banned_by_side="home")]
    assert engine.excluded_item_ids(ledger, scope=enums.PickBanNoRepeatScope.NONE) == set()


def test_excluded_item_ids_encounter_scope_is_global():
    ledger = [
        engine.LedgerRow(item_id=1, banned_by_side="home"),
        engine.LedgerRow(item_id=2, banned_by_side="away"),
    ]
    excluded = engine.excluded_item_ids(ledger, scope=enums.PickBanNoRepeatScope.ENCOUNTER)
    assert excluded == {1, 2}


def test_excluded_item_ids_same_side_scope_filters_by_side():
    ledger = [
        engine.LedgerRow(item_id=1, banned_by_side="home"),
        engine.LedgerRow(item_id=2, banned_by_side="away"),
    ]
    excluded = engine.excluded_item_ids(ledger, scope=enums.PickBanNoRepeatScope.ENCOUNTER_SAME_SIDE, side="home")
    assert excluded == {1}


def test_excluded_item_ids_same_side_scope_requires_side():
    with pytest.raises(ValueError, match="side is required"):
        engine.excluded_item_ids([], scope=enums.PickBanNoRepeatScope.ENCOUNTER_SAME_SIDE)


# ── violates_unique_attribute (role uniqueness) ──────────────────────────────


def test_violates_unique_attribute_true_for_same_side_same_round_same_attr():
    committed = [("home", 1, "support")]
    assert (
        engine.violates_unique_attribute(
            candidate_attribute="support", acting_side="home", round_number=1, committed_this_round=committed
        )
        is True
    )


def test_violates_unique_attribute_false_for_different_attribute():
    committed = [("home", 1, "support")]
    assert (
        engine.violates_unique_attribute(
            candidate_attribute="tank", acting_side="home", round_number=1, committed_this_round=committed
        )
        is False
    )


def test_violates_unique_attribute_false_for_opposing_side():
    # Doc 1's example: A bans Zenyatta (support), B bans Kiriko (support) —
    # both support, but different SIDES, so this must not reject B's ban.
    committed = [("home", 1, "support")]
    assert (
        engine.violates_unique_attribute(
            candidate_attribute="support", acting_side="away", round_number=1, committed_this_round=committed
        )
        is False
    )


def test_violates_unique_attribute_none_attribute_never_violates():
    assert (
        engine.violates_unique_attribute(
            candidate_attribute=None, acting_side="home", round_number=1, committed_this_round=[("home", 1, None)]
        )
        is False
    )


# ── committed_attributes (bans and protects are separate histories) ─────────

ROLES = {1: "tank", 2: "tank", 3: "support"}


def _pool_with_home_tank_ban_and_protect():
    return [
        entry(1, round=1, status="banned", picked_by="home"),
        entry(2, round=1, status="protected", protected_by="home"),
        entry(3, round=1),
    ]


def test_committed_attributes_for_a_ban_reads_bans_only():
    committed = engine.committed_attributes(
        _pool_with_home_tank_ban_and_protect(), action="ban", attribute_lookup=ROLES
    )
    assert committed == [("home", 1, "tank")]


def test_committed_attributes_for_a_protect_reads_protects_only():
    committed = engine.committed_attributes(
        _pool_with_home_tank_ban_and_protect(), action="protect", attribute_lookup=ROLES
    )
    assert committed == [("home", 1, "tank")]


@pytest.mark.parametrize("action", ["pick", "decider"])
def test_committed_attributes_is_empty_for_actions_without_the_rule(action):
    pool = _pool_with_home_tank_ban_and_protect()
    assert engine.committed_attributes(pool, action=action, attribute_lookup=ROLES) == []


def test_own_tank_ban_does_not_bar_that_side_from_protecting_a_tank():
    # The bug this pairing fixes: the room counted a protect as a ban, so home
    # banning a tank spent home's tank protect too. Protects and bans never
    # restrict each other.
    pool = [entry(1, round=1, status="banned", picked_by="home"), entry(2, round=1)]
    assert (
        engine.violates_unique_attribute(
            candidate_attribute="tank",
            acting_side="home",
            round_number=1,
            committed_this_round=engine.committed_attributes(pool, action="protect", attribute_lookup=ROLES),
        )
        is False
    )


def test_own_tank_ban_still_bars_a_second_tank_ban():
    pool = [entry(1, round=1, status="banned", picked_by="home"), entry(2, round=1)]
    assert (
        engine.violates_unique_attribute(
            candidate_attribute="tank",
            acting_side="home",
            round_number=1,
            committed_this_round=engine.committed_attributes(pool, action="ban", attribute_lookup=ROLES),
        )
        is True
    )


def test_own_tank_protect_still_bars_a_second_tank_protect():
    pool = [entry(1, round=1, status="protected", protected_by="home"), entry(2, round=1)]
    assert (
        engine.violates_unique_attribute(
            candidate_attribute="tank",
            acting_side="home",
            round_number=1,
            committed_this_round=engine.committed_attributes(pool, action="protect", attribute_lookup=ROLES),
        )
        is True
    )


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
