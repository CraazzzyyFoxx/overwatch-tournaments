from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.schemas.identity import PersonDisplayRead  # noqa: E402
from src.domain.mix_stats import FORM_LENGTH, SeatOutcome, aggregate_mix_stats, outcome_for  # noqa: E402
from src.services.custom_game import _stats_display  # noqa: E402
from src.services.workspace_roster import RosterMember  # noqa: E402

_EPOCH = datetime(2026, 1, 1, 20, 0)


def _seat(
    member_id: int, match_id: int, outcome: str, role: str | None = None, *, recorded: int | None = None
) -> SeatOutcome:
    """A seat of match ``match_id``, started at minute ``match_id`` and recorded at minute ``recorded`` (by default
    right after it started, so recording order is match order)."""
    return SeatOutcome(
        member_id=member_id,
        role=role,
        match_id=match_id,
        played_at=_EPOCH + timedelta(minutes=match_id),
        recorded_at=_EPOCH + timedelta(minutes=match_id if recorded is None else recorded, seconds=30),
        outcome=outcome,
    )


def _only(seats):
    stats = aggregate_mix_stats(seats)
    assert len(stats) == 1
    return stats[0]


def test_a_scoreboard_row_is_named_in_its_game_or_canonically_across_games() -> None:
    game_name = PersonDisplayRead.build(canonical="Canon#1", provider="riot", handle="Mid#EUW")
    member = RosterMember(
        member_id=7, player_id=70, identity=None, display_name="Canon#1", display=game_name, player_name="Canon#1"
    )
    assert _stats_display(7, member, "lol") == game_name
    assert _stats_display(7, member, None).name == "Canon" and _stats_display(7, member, None).canonical == "Canon#1"
    # A member who left keeps their record, named by id and linked to nobody.
    assert _stats_display(8, None, "lol") == PersonDisplayRead(name="#8")


def test_outcome_for_compares_the_two_sides() -> None:
    assert outcome_for(3, 2) == "win"
    assert outcome_for(2, 3) == "loss"
    assert outcome_for(2, 2) == "draw"
    # A scoreless match is still a draw, not an absent result.
    assert outcome_for(0, 0) == "draw"


def test_totals_and_win_rate_count_every_seat() -> None:
    entry = _only(
        [
            _seat(7, 1, "win"),
            _seat(7, 2, "loss"),
            _seat(7, 3, "win"),
            _seat(7, 4, "draw"),
        ]
    )

    assert (entry.games, entry.wins, entry.losses, entry.draws) == (4, 2, 1, 1)
    assert entry.win_rate == 0.5
    # Newest match, not the last row handed in.
    assert entry.last_played_at == _EPOCH + timedelta(minutes=4)


def test_role_buckets_skip_a_role_less_seat_but_totals_do_not() -> None:
    entry = _only(
        [
            _seat(7, 1, "win", role="tank"),
            _seat(7, 2, "loss", role="tank"),
            _seat(7, 3, "win", role="support"),
            _seat(7, 4, "draw", role=None),
        ]
    )

    assert entry.games == 4
    assert set(entry.by_role) == {"tank", "support"}
    tank = entry.by_role["tank"]
    assert (tank.games, tank.wins, tank.losses, tank.draws) == (2, 1, 1, 0)
    support = entry.by_role["support"]
    assert (support.games, support.wins, support.losses, support.draws) == (1, 1, 0, 0)
    # The role-less seat is the only draw, and no bucket claims it.
    assert sum(tally.draws for tally in entry.by_role.values()) == 0


def test_streak_counts_wins_back_from_the_newest_match() -> None:
    entry = _only([_seat(7, 1, "loss"), _seat(7, 2, "win"), _seat(7, 3, "win")])
    assert entry.streak == 2


def test_streak_flips_negative_after_a_loss_ends_a_win_run() -> None:
    entry = _only([_seat(7, 1, "win"), _seat(7, 2, "win"), _seat(7, 3, "loss")])
    assert entry.streak == -1


def test_streak_is_zero_when_the_newest_match_was_a_draw() -> None:
    entry = _only([_seat(7, 1, "win"), _seat(7, 2, "win"), _seat(7, 3, "draw")])
    assert entry.streak == 0


def test_seat_order_does_not_decide_the_streak() -> None:
    # Rows arrive recording-ordered from SQL, but the streak reads recording times, so a
    # shuffled input answers the same.
    shuffled = [_seat(7, 3, "win"), _seat(7, 1, "loss"), _seat(7, 2, "win")]
    assert _only(shuffled).streak == 2


def test_the_newest_result_is_the_last_recorded_not_the_last_started() -> None:
    # Match 2 started after match 1 (in another lobby, or another mix) but its result landed first.
    entry = _only([_seat(7, 1, "win", recorded=5), _seat(7, 2, "loss", recorded=3)])
    assert [seat.match_id for seat in entry.form] == [1, 2]
    assert entry.streak == 1
    # ``played_at`` stays when the newest-recorded match started.
    assert entry.last_played_at == _EPOCH + timedelta(minutes=1)


def test_form_is_the_newest_ten_results_newest_first() -> None:
    # Twelve matches, shuffled: the strip reads recording times, not input order.
    outcomes = ["win", "loss", "draw"] * 4
    seats = [_seat(7, match_id, outcomes[match_id - 1]) for match_id in (5, 12, 1, 9, 3, 11, 2, 8, 4, 10, 6, 7)]
    form = _only(seats).form
    assert FORM_LENGTH == 10
    assert [seat.match_id for seat in form] == list(range(12, 2, -1))
    assert [seat.outcome for seat in form] == [outcomes[match_id - 1] for match_id in range(12, 2, -1)]
    assert form[0].played_at == _EPOCH + timedelta(minutes=12)


def test_a_short_record_is_the_whole_form() -> None:
    assert [seat.outcome for seat in _only([_seat(7, 1, "loss"), _seat(7, 2, "win")]).form] == ["win", "loss"]


def test_members_rank_by_wins_then_win_rate() -> None:
    seats = [
        # 3 wins, 1 loss -> most wins overall.
        *[_seat(1, m, "win") for m in (1, 2, 3)],
        _seat(1, 4, "loss"),
        # 2 wins, no losses -> perfect rate but fewer wins.
        *[_seat(2, m, "win") for m in (5, 6)],
        # 2 wins, 2 losses -> same wins as 2, worse rate.
        *[_seat(3, m, "win") for m in (7, 8)],
        *[_seat(3, m, "loss") for m in (9, 10)],
        # 2 wins, 2 losses and a draw -> same wins again, and the draw drags the
        # rate below member 3's.
        *[_seat(4, m, "win") for m in (11, 12)],
        *[_seat(4, m, "loss") for m in (13, 14)],
        _seat(4, 15, "draw"),
    ]

    order = [entry.member_id for entry in aggregate_mix_stats(seats)]
    assert order[:2] == [1, 2]
    # 3 and 4 both hold 2 wins, so the rate decides: .5 over .4.
    assert order[2:] == [3, 4]


def test_equal_records_fall_back_to_member_id() -> None:
    seats = [_seat(9, 1, "win"), _seat(2, 2, "win"), _seat(5, 3, "win")]
    assert [entry.member_id for entry in aggregate_mix_stats(seats)] == [2, 5, 9]


def test_no_seats_is_an_empty_scoreboard() -> None:
    assert aggregate_mix_stats([]) == []
