from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

from src.domain.mix_stats import SeatOutcome, aggregate_mix_stats, outcome_for  # noqa: E402

_EPOCH = datetime(2026, 1, 1, 20, 0)


def _seat(member_id: int, match_id: int, outcome: str, role: str | None = None) -> SeatOutcome:
    return SeatOutcome(
        member_id=member_id,
        role=role,
        match_id=match_id,
        played_at=_EPOCH + timedelta(minutes=match_id),
        outcome=outcome,
    )


def _only(seats):
    stats = aggregate_mix_stats(seats)
    assert len(stats) == 1
    return stats[0]


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
    # Rows arrive match-ordered from SQL, but the streak reads match ids, so a
    # shuffled input answers the same.
    shuffled = [_seat(7, 3, "win"), _seat(7, 1, "loss"), _seat(7, 2, "win")]
    assert _only(shuffled).streak == 2


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
