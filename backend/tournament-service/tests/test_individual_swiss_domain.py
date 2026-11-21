"""Individual Swiss pure domain: pool shape, ordering, splits, personal totals."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from src.domain.individual_swiss import (  # noqa: E402
    MatchResult,
    PoolError,
    PoolPlayer,
    SeatResult,
    StandingLine,
    check_playoff_team_count,
    compute_totals,
    order_role,
    pair_closest,
    pick_captains,
    qualify,
    round_captain,
    score_lobbies,
    split_two,
    teams_from_ids,
    teams_per_round,
)

SHAPE = {"tank": 1, "damage": 2, "support": 2}


def _pool(tanks: int, damage: int, support: int, role_override: str | None = None) -> list[PoolPlayer]:
    players: list[PoolPlayer] = []
    for role, n in (("tank", tanks), ("damage", damage), ("support", support)):
        for _ in range(n):
            i = len(players) + 1
            players.append(PoolPlayer(i, None, f"p{i}", role_override or role, i))
    return players


def test_teams_per_round_valid() -> None:
    assert teams_per_round(_pool(4, 8, 8), SHAPE) == 4


@pytest.mark.parametrize(
    ("counts", "code"),
    [((3, 6, 6), "odd_team_count"), ((4, 8, 7), "role_count_mismatch"), ((0, 0, 0), "too_few_players")],
)
def test_teams_per_round_errors(counts: tuple[int, int, int], code: str) -> None:
    with pytest.raises(PoolError) as exc:
        teams_per_round(_pool(*counts), SHAPE)
    assert exc.value.code == code
    assert str(exc.value)


def test_teams_per_round_odd_message() -> None:
    with pytest.raises(PoolError, match="Нужно чётное число команд: сейчас 3"):
        teams_per_round(_pool(3, 6, 6), SHAPE)


def test_flex_player_is_outside_shape() -> None:
    players = [*_pool(4, 8, 8), PoolPlayer(99, None, "flex", "flex", 1)]
    with pytest.raises(PoolError) as exc:
        teams_per_round(players, SHAPE)
    assert exc.value.code == "role_outside_shape"


def test_check_playoff_team_count() -> None:
    check_playoff_team_count(4, 4, SHAPE)
    with pytest.raises(PoolError) as exc:
        check_playoff_team_count(5, 4, SHAPE)
    assert exc.value.code == "playoff_too_large"


def _line(member: int, points: float = 0, diff: float = 0, buchholz: float = 0, rank: int = 0) -> StandingLine:
    return StandingLine(member, "tank", rank, points, diff, buchholz)


def test_order_role_tie_chain() -> None:
    lines = [
        _line(1, points=3, diff=0, buchholz=0, rank=1),
        _line(2, points=3, diff=1, buchholz=0, rank=1),  # map diff beats 1
        _line(3, points=3, diff=1, buchholz=2, rank=1),  # buchholz beats 2
        _line(4, points=3, diff=1, buchholz=2, rank=5),  # rank beats 3
        _line(5, points=3, diff=1, buchholz=2, rank=5),  # member id loses to 4
        _line(6, points=4),  # points beat everything
    ]
    assert order_role(lines, {}) == [6, 4, 5, 3, 2, 1]


def test_order_role_pin_moves_third_to_first() -> None:
    lines = [_line(1, points=3), _line(2, points=2), _line(3, points=1), _line(4, points=0)]
    assert order_role(lines, {3: 1}) == [3, 1, 2, 4]
    assert order_role(lines, {1: 9}) == [2, 3, 4, 1]  # beyond the length clamps to the end
    assert order_role(lines, {1: 9, 2: 9}) == [3, 4, 2, 1]  # a clash takes the nearest free slot before


def test_score_lobbies_slices_each_role() -> None:
    pool = _pool(4, 8, 8)
    order = {role: [p for p in pool if p.role == role] for role in SHAPE}
    lobbies = score_lobbies(order, SHAPE)
    assert len(lobbies) == 2
    assert [p.member_id for p in lobbies[1] if p.role == "tank"] == [3, 4]
    assert [p.member_id for p in lobbies[0] if p.role == "damage"] == [5, 6, 7, 8]
    assert len(lobbies[0]) == 10


def _ranked_lobby() -> list[PoolPlayer]:
    ranks = {"tank": [10, 1], "damage": [5, 5, 5, 5], "support": [4, 4, 4, 4]}
    out: list[PoolPlayer] = []
    for role, rs in ranks.items():
        for r in rs:
            out.append(PoolPlayer(len(out) + 1, None, f"p{len(out) + 1}", role, r))
    return out


def test_split_two_minimises_gap_and_is_seeded() -> None:
    lobby = _ranked_lobby()
    a, b = split_two(lobby, SHAPE, random.Random("1:1"))
    for team in (a, b):
        assert sorted(p.role for p in team) == ["damage", "damage", "support", "support", "tank"]
    assert abs(sum(p.rank for p in a) - sum(p.rank for p in b)) == 9
    assert split_two(lobby, SHAPE, random.Random("1:1")) == (a, b)


def test_split_two_flex_shape() -> None:
    lobby = [PoolPlayer(i, None, f"p{i}", "flex", i) for i in range(1, 13)]
    a, b = split_two(lobby, {"flex": 6}, random.Random(0))
    assert len(a) == len(b) == 6
    assert abs(sum(p.rank for p in a) - sum(p.rank for p in b)) == 0  # 1..12 splits evenly: total 78


def test_split_two_single_slot_roles() -> None:
    shape = dict.fromkeys("abcde", 1)
    lobby = [PoolPlayer(i, None, f"p{i}", "abcde"[i % 5], i) for i in range(10)]
    a, b = split_two(lobby, shape, random.Random(0))
    assert sorted(p.role for p in a) == sorted("abcde") == sorted(p.role for p in b)


def test_teams_from_ids_takes_only_a_whole_pool_in_the_teams_shape() -> None:
    roles = ["tank", "damage", "damage", "support", "support"] * 2
    players = [PoolPlayer(i, None, f"p{i}", role, 10) for i, role in enumerate(roles, 1)]
    teams = teams_from_ids([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]], players, SHAPE, 2)
    assert [[p.member_id for p in team] for team in teams] == [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]]
    for bad in (
        [[1, 2, 3, 4, 5], [6, 7, 8, 9]],  # a player left out
        [[1, 2, 3, 4, 5], [5, 7, 8, 9, 10]],  # a player twice
        [[1, 2, 3, 4, 6], [5, 7, 8, 9, 10]],  # two tanks on one team
    ):
        with pytest.raises(PoolError):
            teams_from_ids(bad, players, SHAPE, 2)


def test_pair_closest_meets_the_teams_nearest_in_total_and_captain() -> None:
    teams = [[PoolPlayer(i, None, f"p{i}", "tank", rank)] for i, rank in ((1, 100), (2, 40), (3, 95), (4, 45))]
    pairs = pair_closest(teams)
    assert [sorted(t[0].member_id for t in pair) for pair in pairs] == [[2, 4], [1, 3]]
    with pytest.raises(PoolError):
        pair_closest(teams[:3])
    team = [
        PoolPlayer(5, None, "a", "tank", 7),
        PoolPlayer(2, None, "b", "damage", 7),
        PoolPlayer(1, None, "c", "damage", 3),
    ]
    assert round_captain(team).member_id == 2


def _match(
    a: tuple[int, ...], a_score: float, a_place: int | None, b: tuple[int, ...], b_score: float, b_place: int | None
) -> MatchResult:
    return MatchResult((SeatResult(a, a_score, a_place), SeatResult(b, b_score, b_place)))


def test_compute_totals_win_and_loss() -> None:
    totals = compute_totals([1, 2, 3, 4, 9], [_match((1, 2), 2, 1, (3, 4), 1, 2)], win=3, draw=1, loss=0)
    for m in (1, 2):
        assert (totals[m].points, totals[m].wins, totals[m].maps_won, totals[m].maps_lost) == (3, 1, 2, 1)
        assert totals[m].map_diff == 1
    for m in (3, 4):
        assert (totals[m].points, totals[m].losses, totals[m].maps_won, totals[m].maps_lost) == (0, 1, 1, 2)
    assert totals[9].matches_played == 0
    assert totals[9].points == 0


def test_compute_totals_draw() -> None:
    totals = compute_totals([1, 2], [_match((1,), 1, 1, (2,), 1, 1)], win=3, draw=1, loss=0)
    assert totals[1].points == totals[2].points == 1
    assert totals[1].draws == totals[2].draws == 1


def test_compute_totals_buchholz_is_sum_of_opponent_means() -> None:
    # 1 beats {2,3}, then loses to 4: final points 1 -> 3, 4 -> 3, 2 and 3 -> 0.
    results = [
        _match((1,), 2, 1, (2, 3), 0, 2),
        _match((4,), 2, 1, (1,), 0, 2),
    ]
    totals = compute_totals([1, 2, 3, 4], results, win=3, draw=1, loss=0)
    # points: 1 -> 3, 2 -> 0, 3 -> 0, 4 -> 3
    assert totals[1].buchholz == 0 + 3
    assert totals[4].buchholz == 3
    assert totals[2].buchholz == 3


def test_compute_totals_buchholz_ties_exactly_across_different_opponent_means() -> None:
    # 1 beats a five whose points total 1 (mean 0.2) and one whose total 2 (mean 0.4); 2 beats a five
    # totalling 3 (mean 0.6). In floats 0.2 + 0.4 != 0.6, which would split this tie.
    x, y, z = (10, 11, 12, 13, 14), (20, 21, 22, 23, 24), (30, 31, 32, 33, 34)
    results = [
        _match((1,), 2, 1, x, 0, 2),
        _match((1,), 2, 1, y, 0, 2),
        _match((2,), 2, 1, z, 0, 2),
        _match((10,), 2, 1, (99,), 0, 2),
        _match((20,), 2, 1, (98,), 0, 2),
        _match((21,), 2, 1, (97,), 0, 2),
        _match((30,), 2, 1, (96,), 0, 2),
        _match((31,), 2, 1, (95,), 0, 2),
        _match((32,), 2, 1, (94,), 0, 2),
    ]
    totals = compute_totals([1, 2], results, win=1, draw=0.5, loss=0)
    assert totals[1].buchholz == totals[2].buchholz == 0.6


def test_qualify_and_captains() -> None:
    order = {"tank": [1, 2, 3, 4], "damage": [5, 6, 7, 8, 9, 10, 11, 12], "support": [13, 14, 15, 16, 17, 18, 19, 20]}
    q = qualify(order, SHAPE, 2)
    assert q == {1, 2, 5, 6, 7, 8, 13, 14, 15, 16}
    pool = [PoolPlayer(m, None, f"p{m}", "tank", r) for m, r in [(1, 5), (2, 9), (3, 9), (4, 1)]]
    assert pick_captains(pool, 2) == [2, 3]
