from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

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

from shared.core.enums import DraftCaptainOrder, DraftFormat  # noqa: E402
from src.services.draft.lifecycle import order_captain_ids  # noqa: E402
from src.services.draft.snake_order import PickSlot, generate_pick_order  # noqa: E402


def test_snake_12x4_produces_48_slots() -> None:
    slots = generate_pick_order(12, 4, DraftFormat.SNAKE)
    assert len(slots) == 48
    assert [s.overall_no for s in slots] == list(range(1, 49))


def test_snake_round_directions() -> None:
    slots = generate_pick_order(12, 4, DraftFormat.SNAKE)
    by_round: dict[int, list[PickSlot]] = {}
    for s in slots:
        by_round.setdefault(s.round_no, []).append(s)

    # Round 1 ascending team seats 0..11
    assert [s.team_index for s in by_round[1]] == list(range(12))
    # Round 2 descending (snake) 11..0
    assert [s.team_index for s in by_round[2]] == list(range(11, -1, -1))
    # Round 3 ascending again
    assert [s.team_index for s in by_round[3]] == list(range(12))
    # Round 4 descending
    assert [s.team_index for s in by_round[4]] == list(range(11, -1, -1))


def test_pick_in_round_resets_each_round() -> None:
    slots = generate_pick_order(12, 4, DraftFormat.SNAKE)
    for round_no in (1, 2, 3, 4):
        picks = [s.pick_in_round for s in slots if s.round_no == round_no]
        assert picks == list(range(1, 13))


def test_round_no_is_one_indexed_and_contiguous() -> None:
    slots = generate_pick_order(12, 4, DraftFormat.SNAKE)
    assert {s.round_no for s in slots} == {1, 2, 3, 4}


def test_linear_format_does_not_reverse() -> None:
    slots = generate_pick_order(12, 4, DraftFormat.LINEAR)
    for round_no in (1, 2, 3, 4):
        seats = [s.team_index for s in slots if s.round_no == round_no]
        assert seats == list(range(12))


def test_each_team_picks_once_per_round() -> None:
    slots = generate_pick_order(8, 5, DraftFormat.SNAKE)
    for round_no in range(1, 6):
        seats = sorted(s.team_index for s in slots if s.round_no == round_no)
        assert seats == list(range(8))


@pytest.mark.parametrize(("teams", "rounds"), [(0, 4), (12, 0), (0, 0)])
def test_empty_when_no_teams_or_rounds(teams: int, rounds: int) -> None:
    assert generate_pick_order(teams, rounds, DraftFormat.SNAKE) == []


def test_single_team() -> None:
    slots = generate_pick_order(1, 3, DraftFormat.SNAKE)
    assert len(slots) == 3
    assert all(s.team_index == 0 for s in slots)
    assert [s.overall_no for s in slots] == [1, 2, 3]


def test_deterministic() -> None:
    a = generate_pick_order(12, 4, DraftFormat.SNAKE)
    b = generate_pick_order(12, 4, DraftFormat.SNAKE)
    assert a == b


# ---- captain seat ordering ----

_ENTRIES = [(10, 3000), (11, 3500), (12, 2800), (13, None)]


def test_captain_order_manual_keeps_selection_order() -> None:
    assert order_captain_ids(_ENTRIES, DraftCaptainOrder.MANUAL) == [10, 11, 12, 13]


def test_captain_order_weakest_first_sorts_ascending_rank() -> None:
    # None rank treated as weakest -> id 13 first, then 12 (2800), 10 (3000), 11 (3500)
    assert order_captain_ids(_ENTRIES, DraftCaptainOrder.WEAKEST_FIRST) == [13, 12, 10, 11]


def test_captain_order_strongest_first_sorts_descending_rank() -> None:
    assert order_captain_ids(_ENTRIES, DraftCaptainOrder.STRONGEST_FIRST)[:3] == [11, 10, 12]


def test_captain_order_random_is_deterministic_for_seed() -> None:
    a = order_captain_ids(_ENTRIES, DraftCaptainOrder.RANDOM, seed=42)
    b = order_captain_ids(_ENTRIES, DraftCaptainOrder.RANDOM, seed=42)
    assert a == b
    assert sorted(a) == [10, 11, 12, 13]  # permutation of all ids


def test_captain_order_weakest_first_tiebreak_by_id() -> None:
    entries = [(20, 3000), (5, 3000), (9, 3000)]
    assert order_captain_ids(entries, DraftCaptainOrder.WEAKEST_FIRST) == [5, 9, 20]
