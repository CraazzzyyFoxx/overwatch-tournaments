"""What rank, sub-role and name a registered team's members export with.

None of it is derived here any more: ``shared.services.roster`` resolves roles and
ranks once for every surface, and ``registered.py`` only picks the *slot's* role
out of that answer. These tests pin the picking, and in particular the deliberate
break with the old local implementation: a player standing on a role slot they
carry no rank for exports at ``0``, never at another role's rank.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.core.enums import HeroClass  # noqa: E402
from shared.domain.roster import PlayerRoster, RosterRole  # noqa: E402
from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from shared.services.team_export import registered  # noqa: E402
from shared.services.team_export.registered import build_registered_export  # noqa: E402

ROLE_SHAPE = parse_roster_slots({"tank": 1, "damage": 2, "support": 2})
FLEX_SHAPE = parse_roster_slots({"flex": 6})
MIXED_SHAPE = parse_roster_slots({"tank": 1, "flex": 4})


def _role(
    role: HeroClass,
    rank: int | None,
    *,
    primary: bool = False,
    priority: int = 0,
    subrole: str | None = None,
) -> RosterRole:
    return RosterRole(
        role=role,
        rank=rank,
        source="registration" if rank is not None else "none",
        is_primary=primary,
        priority=priority,
        subrole=subrole,
    )


def _roster(
    registration_id: int = 1,
    *,
    roles: tuple[RosterRole, ...] = (),
    battle_tag: str | None = "Player#1111",
    display_name: str | None = None,
) -> PlayerRoster:
    return PlayerRoster(
        registration_id=registration_id,
        battle_tag=battle_tag,
        display_name=display_name,
        player_id=None,
        auth_user_id=None,
        workspace_member_id=None,
        roles=roles,
        is_full_flex=False,
    )


def _registration(registration_id: int = 1, *, slot_code: str | None = "tank") -> SimpleNamespace:
    return SimpleNamespace(
        id=registration_id,
        registration_team_id=7,
        team_slot_code=slot_code,
        battle_tag="Player#1111",
        display_name=None,
        workspace_member_id=None,
        is_substitute=False,
    )


class _FakeSession:
    """Serves the export's three reads; the engine itself is patched out."""

    def __init__(self, *, teams: list[object], registrations: list[object]) -> None:
        self._queued: list[list[object]] = [teams, registrations]

    async def scalars(self, statement: object) -> list[object]:
        return self._queued.pop(0)

    async def scalar(self, statement: object) -> int:
        return 42  # workspace_id

    async def execute(self, statement: object) -> Mock:
        result = Mock()
        result.all.return_value = []
        return result


def _team() -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        name="Registered Five",
        status="complete",
        captain_registration_id=None,
        exported_team_id=None,
    )


async def _export(shape, roster: PlayerRoster, *, slot_code: str | None = "tank"):
    """Run the export for a one-member team and hand back that member."""
    registration = _registration(roster.registration_id, slot_code=slot_code)
    session = _FakeSession(teams=[_team()], registrations=[registration])
    with patch.object(
        registered.roster_engine,
        "resolve",
        AsyncMock(return_value={roster.registration_id: roster}),
    ):
        payload = await build_registered_export(session, 1, shape)
    assert len(payload.teams) == 1
    return payload.teams[0].members[0]


class RoleShapeRankTests(IsolatedAsyncioTestCase):
    async def test_the_slots_own_role_rank_wins(self) -> None:
        member = await _export(
            ROLE_SHAPE,
            _roster(roles=(_role(HeroClass.tank, 3000, primary=True), _role(HeroClass.damage, 2000, priority=1))),
            slot_code="tank",
        )
        self.assertEqual(3000, member.rank)

    async def test_a_role_without_its_own_rank_is_zero_not_another_roles_rank(self) -> None:
        """The deliberate behaviour change. The old local helper fell back to the
        primary role's number, so a player placed on ``support`` with only a damage
        rank exported at their damage rank -- a rating for a role nobody verified.
        The engine's rule is that such a role is not playable at all, so the export
        says ``0`` and the organizer sees the gap instead of a plausible number."""
        member = await _export(
            ROLE_SHAPE,
            _roster(roles=(_role(HeroClass.damage, 2500, primary=True),)),
            slot_code="support",
        )
        self.assertEqual(0, member.rank)

    async def test_an_inactive_role_is_not_a_rank_source(self) -> None:
        """A role the engine resolved no rank for (inactive row, or a number no
        layer supplied) is unplayable, so standing on it exports ``0``."""
        member = await _export(
            ROLE_SHAPE,
            _roster(roles=(_role(HeroClass.tank, None), _role(HeroClass.damage, 3900, priority=1))),
            slot_code="tank",
        )
        self.assertEqual(0, member.rank)

    async def test_a_flex_slot_on_a_role_shape_takes_the_best_rank(self) -> None:
        """A flex slot names no role, which is ``rank_on(None)`` -- the best rank
        the player demonstrably holds, since any of their roles may be played."""
        member = await _export(
            MIXED_SHAPE,
            _roster(roles=(_role(HeroClass.support, 1000, primary=True), _role(HeroClass.tank, 4000, priority=1))),
            slot_code="flex",
        )
        self.assertEqual(4000, member.rank)

    async def test_no_ranks_at_all_is_zero_not_an_error(self) -> None:
        """Tournaments that never collect ranks must still be able to export;
        raising here would make the whole feature unusable for them."""
        member = await _export(ROLE_SHAPE, _roster(roles=()), slot_code="tank")
        self.assertEqual(0, member.rank)

    async def test_a_member_with_no_slot_takes_the_best_rank(self) -> None:
        member = await _export(
            ROLE_SHAPE,
            _roster(roles=(_role(HeroClass.damage, 3300, primary=True), _role(HeroClass.tank, 1200, priority=1))),
            slot_code=None,
        )
        self.assertEqual(3300, member.rank)


class RoleLessShapeRankTests(IsolatedAsyncioTestCase):
    async def test_a_flex_roster_takes_the_best_rank(self) -> None:
        """With no role for rank to be a function of, anything lower would
        understate a rank the member has on a playable role."""
        member = await _export(
            FLEX_SHAPE,
            _roster(
                roles=(
                    _role(HeroClass.tank, 1500, primary=True),
                    _role(HeroClass.damage, 3800, priority=1),
                    _role(HeroClass.support, 2200, priority=2),
                )
            ),
            slot_code="flex",
        )
        self.assertEqual(3800, member.rank)

    async def test_an_empty_flex_roster_member_is_zero(self) -> None:
        member = await _export(FLEX_SHAPE, _roster(roles=()), slot_code="flex")
        self.assertEqual(0, member.rank)

    async def test_the_slot_code_is_irrelevant_on_a_role_less_roster(self) -> None:
        """Guards against a future refactor reintroducing a role lookup here: on an
        all-flex shape there is no role slot to look up, so even a stale ``tank``
        slot code still answers the maximum."""
        roles = (_role(HeroClass.tank, 1000, primary=True), _role(HeroClass.damage, 3000, priority=1))
        for slot in ("flex", None, "tank"):
            with self.subTest(slot=slot):
                member = await _export(FLEX_SHAPE, _roster(roles=roles), slot_code=slot)
                self.assertEqual(3000, member.rank)


class SubRoleTests(IsolatedAsyncioTestCase):
    async def test_the_sub_role_of_the_slots_own_role_is_taken(self) -> None:
        member = await _export(
            ROLE_SHAPE,
            _roster(
                roles=(
                    _role(HeroClass.tank, 3000, primary=True, subrole="main_tank"),
                    _role(HeroClass.damage, 2000, priority=1, subrole="hitscan"),
                )
            ),
            slot_code="tank",
        )
        self.assertEqual("main_tank", member.sub_role)

    async def test_a_role_less_slot_takes_the_lead_sub_role(self) -> None:
        """No role to look up, so the player's primary role's sub-role stands."""
        member = await _export(
            FLEX_SHAPE,
            _roster(roles=(_role(HeroClass.damage, 3000, primary=True, subrole="hitscan"),)),
            slot_code="flex",
        )
        self.assertEqual("hitscan", member.sub_role)

    async def test_a_slot_whose_role_declares_none_has_none(self) -> None:
        member = await _export(
            ROLE_SHAPE,
            _roster(roles=(_role(HeroClass.support, 2000, primary=True),)),
            slot_code="support",
        )
        self.assertIsNone(member.sub_role)


class MemberNameTests(TestCase):
    """The name is the roster's identity, not a second read of the registration."""

    def test_the_battle_tag_leads(self) -> None:
        roster = _roster(battle_tag="Tag#1", display_name="Nick")
        self.assertEqual("Tag#1", registered._member_name(roster))

    def test_the_display_name_stands_in_for_a_missing_tag(self) -> None:
        roster = _roster(battle_tag=None, display_name="Nick")
        self.assertEqual("Nick", registered._member_name(roster))

    def test_a_nameless_registration_falls_back_to_its_id(self) -> None:
        roster = _roster(9, battle_tag=None, display_name=None)
        self.assertEqual("registration-9", registered._member_name(roster))


class EngineIsTheOnlySourceTests(TestCase):
    """The point of this cutover: no second implementation may creep back in."""

    def test_no_raw_registration_role_reads_remain(self) -> None:
        source = (BACKEND_ROOT / "shared" / "services" / "team_export" / "registered.py").read_text(encoding="utf-8")
        for forbidden in ("rank_value", "is_active", "is_primary", "BalancerRegistrationRole"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_engine_is_what_the_export_asks(self) -> None:
        source = (BACKEND_ROOT / "shared" / "services" / "team_export" / "registered.py").read_text(encoding="utf-8")
        self.assertIn("roster_engine.resolve(", source)
        self.assertIn("registration_load_options()", source)
