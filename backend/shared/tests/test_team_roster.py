"""Slot accounting for a registering team.

The two asymmetries are the whole point of this module, so they are pinned
explicitly: a pending invite reserves a slot for *offering* but must not block its
own *acceptance*. Getting either backwards produces a bug that only shows up under
concurrency or as an opaque failure for a real invitee.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.domain.roster_shape import RosterShapeError, parse_roster_slots  # noqa: E402
from shared.domain.team_roster import RosterMember, RosterOccupancy  # noqa: E402

FIVE_STACK = parse_roster_slots({"tank": 1, "damage": 2, "support": 2})
FLEX_SIX = parse_roster_slots({"flex": 6})


def _starters(*codes: str) -> tuple[RosterMember, ...]:
    return tuple(RosterMember(slot_code=code) for code in codes)


class OpenSlotTests(TestCase):
    def test_an_empty_roster_needs_the_whole_shape(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK)
        self.assertEqual({"tank": 1, "damage": 2, "support": 2}, occupancy.open_slots)
        self.assertFalse(occupancy.is_complete)

    def test_accepted_members_consume_their_slots(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK, accepted=_starters("tank", "damage"))
        self.assertEqual({"tank": 0, "damage": 1, "support": 2}, occupancy.open_slots)
        self.assertEqual({"tank": 1, "damage": 1, "support": 0}, occupancy.filled_slots)

    def test_a_full_roster_is_complete(self) -> None:
        occupancy = RosterOccupancy(
            shape=FIVE_STACK,
            accepted=_starters("tank", "damage", "damage", "support", "support"),
        )
        self.assertTrue(occupancy.is_complete)
        self.assertEqual("roster complete", occupancy.describe_shortfall())

    def test_substitutes_do_not_make_a_roster_complete(self) -> None:
        """A bench player fills no starter slot — the same rule the export uses."""
        occupancy = RosterOccupancy(
            shape=FIVE_STACK,
            accepted=(*_starters("tank", "damage", "damage", "support"), RosterMember("support", is_substitute=True)),
            max_substitutes=2,
        )
        self.assertFalse(occupancy.is_complete)
        self.assertEqual({"tank": 0, "damage": 0, "support": 1}, occupancy.open_slots)
        self.assertEqual(1, occupancy.accepted_substitutes)

    def test_shortfall_names_what_is_missing(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK, accepted=_starters("tank", "damage"))
        self.assertEqual("1x damage, 2x support", occupancy.describe_shortfall())


class OfferVersusAcceptTests(TestCase):
    def test_a_pending_invite_reserves_the_slot_for_offering(self) -> None:
        """Otherwise ten offers can be held open for one slot."""
        occupancy = RosterOccupancy(shape=FIVE_STACK, pending=_starters("tank"))
        self.assertFalse(occupancy.can_offer("tank"))
        self.assertEqual({"tank": 0, "damage": 2, "support": 2}, occupancy.unoffered_slots)

    def test_a_pending_invite_does_not_block_its_own_acceptance(self) -> None:
        """The mirror-image mistake: reserving on accept makes every invite
        un-acceptable."""
        occupancy = RosterOccupancy(shape=FIVE_STACK, pending=_starters("tank"))
        self.assertTrue(occupancy.can_accept("tank"))

    def test_an_accepted_slot_blocks_both(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK, accepted=_starters("tank"))
        self.assertFalse(occupancy.can_offer("tank"))
        self.assertFalse(occupancy.can_accept("tank"))

    def test_partially_offered_slots_still_offer(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK, pending=_starters("damage"))
        self.assertTrue(occupancy.can_offer("damage"))
        occupancy = RosterOccupancy(shape=FIVE_STACK, pending=_starters("damage", "damage"))
        self.assertFalse(occupancy.can_offer("damage"))


class SubstituteTests(TestCase):
    def test_substitutes_are_capped_independently_of_the_shape(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK, max_substitutes=1)
        self.assertTrue(occupancy.can_offer("damage", is_substitute=True))
        occupancy = RosterOccupancy(
            shape=FIVE_STACK,
            accepted=(RosterMember("damage", is_substitute=True),),
            max_substitutes=1,
        )
        self.assertFalse(occupancy.can_offer("damage", is_substitute=True))
        self.assertFalse(occupancy.can_accept("damage", is_substitute=True))

    def test_zero_substitutes_allowed_by_default(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK)
        self.assertFalse(occupancy.can_offer("damage", is_substitute=True))

    def test_pending_substitute_invites_reserve_bench_capacity(self) -> None:
        occupancy = RosterOccupancy(
            shape=FIVE_STACK,
            pending=(RosterMember("damage", is_substitute=True),),
            max_substitutes=1,
        )
        self.assertFalse(occupancy.can_offer("damage", is_substitute=True))
        # ...but the pending one can still be accepted.
        self.assertTrue(occupancy.can_accept("damage", is_substitute=True))

    def test_a_substitute_may_sit_on_a_slot_that_is_already_full(self) -> None:
        """The bench is not a starter slot, so a full tank slot does not stop a
        tank substitute."""
        occupancy = RosterOccupancy(
            shape=FIVE_STACK,
            accepted=_starters("tank"),
            max_substitutes=1,
        )
        self.assertTrue(occupancy.can_accept("tank", is_substitute=True))


class RoleLessRosterTests(TestCase):
    def test_a_flex_shape_tracks_one_undifferentiated_pool(self) -> None:
        occupancy = RosterOccupancy(shape=FLEX_SIX, accepted=_starters("flex", "flex"))
        self.assertEqual({"flex": 4}, occupancy.open_slots)
        self.assertTrue(occupancy.can_offer("flex"))

    def test_a_role_slot_is_rejected_on_a_flex_shape(self) -> None:
        """Guards the case decision 18 exists for: a role-less tournament has no
        tank slot to put anyone in."""
        occupancy = RosterOccupancy(shape=FLEX_SIX)
        with self.assertRaises(RosterShapeError) as caught:
            occupancy.can_accept("tank")
        self.assertEqual("slot_not_in_shape", caught.exception.code)

    def test_flex_is_rejected_on_a_role_shape(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK)
        with self.assertRaises(RosterShapeError) as caught:
            occupancy.can_offer("flex")
        self.assertEqual("slot_not_in_shape", caught.exception.code)

    def test_an_unknown_code_is_rejected_before_the_shape_lookup(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK)
        with self.assertRaises(RosterShapeError) as caught:
            occupancy.can_accept("healer")
        self.assertEqual("roster_slots_unknown_code", caught.exception.code)
