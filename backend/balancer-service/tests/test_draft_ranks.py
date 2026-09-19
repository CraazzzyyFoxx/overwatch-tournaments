"""The one draft-side rank rule: what a roster SLOT is worth.

``draftreg1`` deleted the draft's own rank columns, so there is nothing left to
fall back to: a role either carries a resolved rank (and is playable) or it does
not (and the player cannot be drafted on it at all). ``slot_rank`` is therefore
one function over ``PlayerRoster``, and the only question it still answers is
the SHAPE question -- a role-slot roster values a player on the role they fill,
a role-less (all-flex) one on their strongest.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.core.enums import HeroClass  # noqa: E402
from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from src.domain.draft import ranks  # noqa: E402
from tests.factories import roster  # noqa: E402

ROLE_SHAPE = parse_roster_slots({"tank": 1, "damage": 2, "support": 2})
FLEX_SHAPE = parse_roster_slots({"flex": 5})


def test_a_role_is_worth_its_own_rank_not_the_lead_role_s() -> None:
    r = roster(1, ranks={"damage": 4000, "support": 2800})
    assert r.rank_on(HeroClass.damage) == 4000
    assert r.rank_on(HeroClass.support) == 2800


def test_a_declared_role_without_a_rank_is_not_playable_and_has_no_rank() -> None:
    # The deleted contract said this role "falls back to rank_value". There is
    # no rank_value any more and there never was an honest number here: a role
    # no layer ranked cannot be drafted, so it answers None and stays out of the
    # playable set. Borrowing a neighbour's number is what used to invent a
    # rating the captain then picked on.
    r = roster(1, ranks={"damage": 4000, "tank": None})

    assert r.rank_on(HeroClass.tank) is None
    assert r.playable_roles == frozenset({HeroClass.damage})
    assert r.covers(HeroClass.tank) is False
    assert ranks.slot_rank(r, HeroClass.tank, ROLE_SHAPE) is None


def test_a_role_the_registration_never_declared_has_no_rank() -> None:
    r = roster(1, ranks={"damage": 4000})
    assert r.rank_on(HeroClass.tank) is None


def test_no_role_at_all_answers_the_best_playable_rank() -> None:
    r = roster(1, ranks={"support": 2800, "damage": 4000})
    assert r.rank_on(None) == 4000
    assert r.best_rank == 4000


def test_accepts_a_slot_code_next_to_the_enum() -> None:
    r = roster(1, ranks={"damage": 4000, "support": 2800})
    assert r.rank_on("support") == 2800
    assert ranks.slot_rank(r, "support", ROLE_SHAPE) == 2800


def test_best_rank_is_the_strongest_role_not_the_lead_one() -> None:
    r = roster(1, ranks={"support": 2800, "damage": 4000}, primary="support")
    assert r.primary is not None and r.primary.role is HeroClass.support
    assert r.best_rank == 4000


def test_best_rank_ignores_a_declared_role_carrying_no_rank() -> None:
    r = roster(1, ranks={"support": 2800, "tank": None})
    assert r.best_rank == 2800


def test_best_rank_is_none_without_any_ranked_role() -> None:
    r = roster(1, ranks={"damage": None})
    assert r.best_rank is None
    assert r.is_draftable is False


def test_slot_rank_stays_role_specific_under_role_slots() -> None:
    r = roster(1, ranks={"damage": 4000, "support": 2800})
    assert ranks.slot_rank(r, HeroClass.support, ROLE_SHAPE) == 2800


def test_slot_rank_ignores_the_role_under_an_all_flex_shape() -> None:
    # The shape assigns nobody a role, so the requested one cannot lower the rank.
    r = roster(1, ranks={"damage": 4000, "support": 2800})
    assert ranks.slot_rank(r, HeroClass.support, FLEX_SHAPE) == 4000


def test_slot_rank_without_a_role_is_the_best_rank_under_either_shape() -> None:
    r = roster(1, ranks={"support": 2800, "damage": 4000}, primary="support")
    assert ranks.slot_rank(r, None, ROLE_SHAPE) == 4000
    assert ranks.slot_rank(r, None, FLEX_SHAPE) == 4000


def test_slot_rank_of_a_seat_with_no_roster_is_none() -> None:
    # A registration soft-deleted mid-draft, or one the engine could not resolve:
    # the export and the board both hit this and must not invent a 0.
    assert ranks.slot_rank(None, HeroClass.tank, ROLE_SHAPE) is None
    assert ranks.slot_rank(None, None, FLEX_SHAPE) is None


def test_slot_rank_without_any_role_ranks_is_none_on_role_slots() -> None:
    r = roster(1, ranks={})
    assert ranks.slot_rank(r, None, ROLE_SHAPE) is None
    assert ranks.slot_rank(r, None, FLEX_SHAPE) is None
