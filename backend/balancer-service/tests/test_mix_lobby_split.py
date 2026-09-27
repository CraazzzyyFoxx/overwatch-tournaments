from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.domain.mix_lobby_split import LobbySplitError, SplitCandidate, split_into_lobbies  # noqa: E402

#: 1 танк на команду -> 2 места в лобби, 4 игрока на два лобби.
MASK_TANK = {"tank": 1}
#: 1 танк + 1 дамаг на команду -> 4 места в лобби (2 танковых + 2 дамажных).
MASK_TANK_DAMAGE = {"tank": 1, "damage": 1}


def _candidate(
    member_id: int,
    strength: int,
    *,
    roles: tuple[str, ...] = ("tank", "damage", "support"),
    pin: int | None = None,
    must_play: bool = False,
    rotation_priority: float = 0.0,
) -> SplitCandidate:
    return SplitCandidate(
        member_id=member_id,
        ratings=dict.fromkeys(roles, strength),
        strength=strength,
        pin=pin,
        must_play=must_play,
        rotation_priority=rotation_priority,
    )


def test_pinned_players_land_in_their_own_lobby() -> None:
    candidates = [
        _candidate(1, 3000, pin=1),
        _candidate(2, 2900),
        _candidate(3, 2800, pin=0),
        _candidate(4, 2700),
    ]

    split = split_into_lobbies(candidates, mask=MASK_TANK)

    assert 1 in split.lobbies[1]
    assert 3 in split.lobbies[0]
    assert sorted(split.lobbies[0] + split.lobbies[1]) == [1, 2, 3, 4]
    assert split.waiting == ()


def test_more_pins_than_seats_in_one_lobby_is_refused() -> None:
    candidates = [
        _candidate(1, 3000, pin=0),
        _candidate(2, 2900, pin=0),
        _candidate(3, 2800, pin=0),
        _candidate(4, 2700),
    ]

    with pytest.raises(LobbySplitError) as exc:
        split_into_lobbies(candidates, mask=MASK_TANK)

    assert exc.value.code == "too_many_pinned"


def test_two_lobbies_need_a_full_pool_for_both() -> None:
    candidates = [_candidate(member_id, 2500) for member_id in (1, 2, 3)]

    with pytest.raises(LobbySplitError) as exc:
        split_into_lobbies(candidates, mask=MASK_TANK)

    assert exc.value.code == "not_enough_for_two_lobbies"


def test_more_must_play_than_seats_in_both_lobbies_is_refused() -> None:
    """Пин обещает место: 21 обещание на 20 мест двух лобби -- не тихий waiting."""
    candidates = [_candidate(member_id, 2500, must_play=True) for member_id in range(1, 22)]

    with pytest.raises(LobbySplitError) as exc:
        split_into_lobbies(candidates, mask={"tank": 1, "damage": 2, "support": 2})

    assert exc.value.code == "too_many_must_play"


def test_five_tank_only_players_do_not_fit_four_tank_slots() -> None:
    # Два лобби дают 4 танковых слота; пятый «только танк» не сядет никуда,
    # как бы ни делили остальных.
    candidates = [_candidate(member_id, 3000 - member_id, roles=("tank",)) for member_id in (1, 2, 3, 4, 5)]
    candidates += [_candidate(member_id, 2000 - member_id, roles=("tank", "damage")) for member_id in (6, 7, 8)]

    with pytest.raises(LobbySplitError) as exc:
        split_into_lobbies(candidates, mask=MASK_TANK_DAMAGE)

    assert exc.value.code == "roles_infeasible"


def test_must_play_takes_a_seat_over_a_rested_pool() -> None:
    candidates = [
        _candidate(1, 3000, rotation_priority=-5.0),
        _candidate(2, 2900, rotation_priority=-4.0),
        _candidate(3, 2800, rotation_priority=-3.0),
        _candidate(4, 2700, rotation_priority=-2.0),
        _candidate(5, 2600, must_play=True, rotation_priority=9.0),
    ]

    split = split_into_lobbies(candidates, mask=MASK_TANK)

    assert 5 in split.lobbies[0] + split.lobbies[1]
    # Место отдаёт тот, кто по ротации должен его меньше всех.
    assert split.waiting == (4,)


def test_waiting_are_the_players_least_owed_a_seat() -> None:
    candidates = [
        _candidate(1, 2500, rotation_priority=4.0),
        _candidate(2, 2500, rotation_priority=-1.0),
        _candidate(3, 2500, rotation_priority=0.0),
        _candidate(4, 2500, rotation_priority=-3.0),
        _candidate(5, 2500, rotation_priority=3.0),
        _candidate(6, 2500, rotation_priority=-2.0),
    ]

    split = split_into_lobbies(candidates, mask=MASK_TANK)

    assert split.waiting == (1, 5)
    assert sorted(split.lobbies[0] + split.lobbies[1]) == [2, 3, 4, 6]


def test_role_bound_greedy_is_repaired_by_swaps() -> None:
    """Жадный шаг обязан слушаться ролевых слотов и потому перекашивается.

    Танки 100/60/50/40, дамаги 90/80/20/10, по два танковых и два дамажных
    слота на лобби. Жадно (сильнейший -- в лобби полегче, где он помещается)
    получается 190 против 260, разрыв 70: как только танковые слоты лобби
    заполнены, следующий танк вынужден идти в тяжёлое. Обмены, сохраняющие
    заполнимость, закрывают разрыв до 10 -- лучшего эта ролевая структура не
    допускает (танки делятся только как 100+40 против 60+50).
    """
    candidates = [
        _candidate(1, 100, roles=("tank",)),
        _candidate(2, 90, roles=("damage",)),
        _candidate(3, 80, roles=("damage",)),
        _candidate(4, 60, roles=("tank",)),
        _candidate(5, 50, roles=("tank",)),
        _candidate(6, 40, roles=("tank",)),
        _candidate(7, 20, roles=("damage",)),
        _candidate(8, 10, roles=("damage",)),
    ]

    split = split_into_lobbies(candidates, mask=MASK_TANK_DAMAGE)

    strength = {candidate.member_id: candidate.strength for candidate in candidates}
    totals = [sum(strength[member_id] for member_id in lobby) for lobby in split.lobbies]
    assert abs(totals[0] - totals[1]) == 10
    assert set(split.lobbies[0]) == {1, 3, 6, 8}
    assert set(split.lobbies[1]) == {2, 4, 5, 7}


def test_identical_players_split_by_input_order() -> None:
    """Ни RNG, ни обхода множеств: равные игроки ложатся так, как их подали."""
    candidates = [_candidate(member_id, 2500) for member_id in (1, 2, 3, 4)]

    first = split_into_lobbies(candidates, mask=MASK_TANK)
    second = split_into_lobbies(candidates, mask=MASK_TANK)

    assert first == second
    assert first.lobbies == ((1, 3), (2, 4))


def test_a_flex_slot_takes_any_ranked_player() -> None:
    """Воркспейс может держать all-flex форму; ранга с именем "flex" нет ни у кого."""
    candidates = [_candidate(member_id, 2500, roles=("support",)) for member_id in (1, 2, 3, 4)]

    split = split_into_lobbies(candidates, mask={"flex": 1})

    assert sorted(split.lobbies[0] + split.lobbies[1]) == [1, 2, 3, 4]
