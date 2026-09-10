"""Tournament rank resolution: the registration's own layer, then what it inherits.

The resolver itself now lives in :mod:`shared.services.roster` -- this suite is
what is left of ``test_registration_workspace_player_write.py`` and guards the
regressions the tournament-service used to own: ``registration_role.rank_value``
is only the strongest of three layers, an empty one *inherits* instead of reading
as "unranked", and a role with no number anywhere is what makes the role
unplayable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase, mock


def _ensure_test_env() -> None:
    for key, value in {
        "DEBUG": "true",
    }.items():
        os.environ.setdefault(key, value)


_ensure_test_env()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core.enums import HeroClass  # noqa: E402
from shared.division_grid import load_runtime_grid  # noqa: E402
from shared.domain.member_rank import ResolvedRank  # noqa: E402
from shared.services.member_rank import TOURNAMENT_ORDER  # noqa: E402
from shared.services.roster import roster_engine  # noqa: E402

_GRID = load_runtime_grid(None)
#: An ``optional``-mode form, passed in so the engine never queries for one.
_FORM = SimpleNamespace(built_in_fields_json={})


class _Rows:
    def __init__(self, rows: list[tuple[int, int | None]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[int, int | None]]:
        return self._rows


class _Session:
    """Only what the engine touches here: the member->player scalar lookup."""

    def __init__(self, member_rows: list[tuple[int, int | None]] | None = None) -> None:
        self._rows = member_rows or []

    async def execute(self, *_args: Any, **_kwargs: Any) -> _Rows:
        return _Rows(self._rows)


def _registration(
    registration_id: int,
    roles: dict[str, int | None],
    *,
    member_id: int | None,
    inactive: frozenset[str] = frozenset(),
) -> SimpleNamespace:
    return SimpleNamespace(
        id=registration_id,
        tournament_id=7,
        workspace_member_id=member_id,
        workspace_member=SimpleNamespace(player_id=77, player=None) if member_id is not None else None,
        battle_tag="Player#1234",
        display_name="Player",
        is_flex_computed=False,
        notes=None,
        admin_notes=None,
        custom_fields_json=None,
        status="approved",
        balancer_status="in_balancer",
        exclude_reason=None,
        checked_in=False,
        registration_team_id=None,
        team_slot_code=None,
        is_substitute=False,
        discord_nick=None,
        twitch_nick=None,
        boosty_nick=None,
        stream_pov=False,
        smurf_tags_json=None,
        roles=[
            SimpleNamespace(
                id=index,
                role=role,
                rank_value=value,
                is_active=role not in inactive,
                is_primary=index == 0,
                priority=index,
                subrole=None,
                hero_entries=[],
            )
            for index, (role, value) in enumerate(roles.items())
        ],
    )


def _flex_form(mode: str, *, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(built_in_fields_json={"flex_role": {"enabled": enabled, "mode": mode}})


async def _resolve(
    session: Any,
    registration: SimpleNamespace,
    *,
    workspace_id: int | None,
    form: Any = _FORM,
) -> Any:
    rosters = await roster_engine.resolve(
        session,
        [registration],
        workspace_id=workspace_id,
        tournament_id=registration.tournament_id,
        form=form,
        grid=_GRID,
    )
    return rosters[registration.id]


class TestResolveRegistrationRanks(IsolatedAsyncioTestCase):
    async def test_registration_value_wins_over_everything_inherited(self) -> None:
        registration = _registration(1, {"tank": 2500}, member_id=9)
        resolve = mock.AsyncMock(return_value={(9, "tank"): ResolvedRank(2500, "registration")})
        with mock.patch.object(roster_engine.ranks, "resolve", resolve):
            roster = await _resolve(_Session([(9, 77)]), registration, workspace_id=1)
        self.assertEqual(roster.rank_on("tank"), 2500)
        self.assertEqual(roster.source_on("tank"), "registration")
        # The registration's own number is handed to the resolver as its layer
        # rather than compared against the others here.
        self.assertEqual(resolve.await_args.kwargs["registration_ranks"], {(9, "tank"): 2500})
        self.assertEqual(resolve.await_args.kwargs["order"], TOURNAMENT_ORDER)

    async def test_blank_role_inherits_the_workspace_canon(self) -> None:
        """The regression this refactor exists for: a blank rank used to read as
        ``none``, which dropped a canon-ranked player out of the balancer pool."""
        registration = _registration(1, {"tank": None}, member_id=9)
        resolve = mock.AsyncMock(return_value={(9, "tank"): ResolvedRank(3200, "workspace")})
        with mock.patch.object(roster_engine.ranks, "resolve", resolve):
            roster = await _resolve(_Session([(9, 77)]), registration, workspace_id=1)
        self.assertEqual(roster.rank_on("tank"), 3200)
        self.assertEqual(roster.source_on("tank"), "workspace")
        # A blank role contributes no registration layer, so it cannot pin itself.
        self.assertEqual(resolve.await_args.kwargs["registration_ranks"], {})

    async def test_unranked_everywhere_is_unplayable(self) -> None:
        registration = _registration(1, {"tank": None}, member_id=9)
        resolve = mock.AsyncMock(return_value={(9, "tank"): ResolvedRank(None, "none")})
        with mock.patch.object(roster_engine.ranks, "resolve", resolve):
            roster = await _resolve(_Session([(9, 77)]), registration, workspace_id=1)
        self.assertEqual(roster.rank_on("tank"), None)
        self.assertEqual(roster.playable_roles, frozenset())
        self.assertFalse(roster.is_ranked_complete)
        self.assertFalse(roster.is_draftable)

    async def test_no_member_anchor_answers_from_its_own_layer(self) -> None:
        """A manual registration with no identity keeps the number the organiser
        typed -- only the inherited layers need a member."""
        registration = _registration(1, {"tank": 2500, "dps": None}, member_id=None)
        resolve = mock.AsyncMock()
        with mock.patch.object(roster_engine.ranks, "resolve", resolve):
            roster = await _resolve(_Session(), registration, workspace_id=1)
        resolve.assert_not_awaited()
        self.assertEqual(roster.rank_on("tank"), 2500)
        self.assertEqual(roster.rank_on("dps"), None)
        # One rated role out of two: draftable, but not "ready".
        self.assertTrue(roster.is_draftable)
        self.assertFalse(roster.is_ranked_complete)

    async def test_unknown_workspace_does_not_guess_a_tenancy(self) -> None:
        registration = _registration(1, {"tank": 2500}, member_id=9)
        resolve = mock.AsyncMock()
        with mock.patch.object(roster_engine.ranks, "resolve", resolve):
            roster = await _resolve(_Session([(9, 77)]), registration, workspace_id=None)
        resolve.assert_not_awaited()
        self.assertEqual(roster.rank_on("tank"), 2500)

    async def test_member_from_another_workspace_cannot_blank_the_own_layer(self) -> None:
        """The member lookup is workspace-filtered, so a cross-tenant anchor
        resolves to nothing -- and must fall back, not erase."""
        registration = _registration(1, {"tank": 2500}, member_id=9)
        resolve = mock.AsyncMock(return_value={})
        with mock.patch.object(roster_engine.ranks, "resolve", resolve):
            roster = await _resolve(_Session([]), registration, workspace_id=1)
        self.assertEqual(roster.rank_on("tank"), 2500)

    async def test_every_declared_role_ranked_is_ready(self) -> None:
        """What the ``ready``/``incomplete`` verdict now reads, in one property."""
        registration = _registration(1, {"tank": 2500, "dps": None}, member_id=9)
        resolve = mock.AsyncMock(
            return_value={
                (9, "tank"): ResolvedRank(2500, "registration"),
                (9, "dps"): ResolvedRank(3200, "workspace"),
            }
        )
        with mock.patch.object(roster_engine.ranks, "resolve", resolve):
            roster = await _resolve(_Session([(9, 77)]), registration, workspace_id=1)
        self.assertTrue(roster.is_ranked_complete)
        self.assertEqual(roster.role_ranks, {"tank": 2500, "dps": 3200})

    async def test_optional_mode_drops_a_row_the_registrant_did_not_declare(self) -> None:
        """The other half of the predicate: under ``optional`` an inactive row is
        not a role at all, even carrying a number. Reporting it would advertise a
        rating the balancer and the draft both refuse to pick on."""
        registration = _registration(1, {"tank": 2500, "dps": 4000}, member_id=9, inactive=frozenset({"dps"}))
        resolve = mock.AsyncMock(return_value={(9, "tank"): ResolvedRank(2500, "registration")})
        with mock.patch.object(roster_engine.ranks, "resolve", resolve):
            roster = await _resolve(_Session([(9, 77)]), registration, workspace_id=1)
        self.assertEqual([entry.role.slot_code for entry in roster.roles], ["tank"])
        self.assertEqual(roster.playable_roles, frozenset({HeroClass.tank}))
        self.assertEqual(roster.role_ranks, {"tank": 2500})
        self.assertIsNone(roster.rank_on("dps"))
        # Judged over the declared roles only -- the undeclared one cannot make
        # the registration look incomplete.
        self.assertTrue(roster.is_ranked_complete)
        # The inactive row's own number is never even offered as a layer.
        self.assertEqual(resolve.await_args.kwargs["registration_ranks"], {(9, "tank"): 2500})


class TestFlexModesAtTheEngineLevel(IsolatedAsyncioTestCase):
    """Under ``all_roles``/``forced`` role stops being a constraint."""

    async def _resolve_all_roles(self, mode: str, registration: SimpleNamespace, resolved: dict) -> Any:
        resolve = mock.AsyncMock(return_value=resolved)
        with mock.patch.object(roster_engine.ranks, "resolve", resolve):
            return await _resolve(_Session([(9, 77)]), registration, workspace_id=1, form=_flex_form(mode))

    async def test_every_role_is_playable_and_an_unrated_one_inherits_the_best(self) -> None:
        for mode in ("all_roles", "forced"):
            with self.subTest(mode=mode):
                registration = _registration(1, {"tank": 2500, "dps": None}, member_id=9, inactive=frozenset({"dps"}))
                roster = await self._resolve_all_roles(
                    mode,
                    registration,
                    {
                        (9, "tank"): ResolvedRank(2500, "registration"),
                        (9, "dps"): ResolvedRank(None, "none"),
                        (9, "support"): ResolvedRank(None, "none"),
                    },
                )
                # The inactive row is NOT dropped, and the role with no row at all
                # is synthesized: all three come out playable.
                self.assertEqual(
                    roster.playable_roles,
                    frozenset({HeroClass.tank, HeroClass.damage, HeroClass.support}),
                )
                self.assertTrue(roster.is_ranked_complete)
                self.assertEqual(roster.role_ranks, {"tank": 2500, "dps": 2500, "support": 2500})

    async def test_a_role_with_its_own_rating_keeps_it(self) -> None:
        """The "one number printed three times" bug: the max only fills the roles
        no layer rated, it never overwrites a real per-role rating."""
        registration = _registration(1, {"tank": 2500, "dps": 4000}, member_id=9)
        roster = await self._resolve_all_roles(
            "all_roles",
            registration,
            {
                (9, "tank"): ResolvedRank(2500, "registration"),
                (9, "dps"): ResolvedRank(4000, "registration"),
                (9, "support"): ResolvedRank(None, "none"),
            },
        )
        self.assertEqual(roster.role_ranks, {"tank": 2500, "dps": 4000, "support": 4000})

    async def test_a_disabled_flex_field_cannot_force_roles_it_never_showed(self) -> None:
        """``enabled: false`` bans flex outright, so the mode is ignored: no
        backfill, no inheritance, and the inactive row stays out."""
        registration = _registration(1, {"tank": 2500, "dps": None}, member_id=9, inactive=frozenset({"dps"}))
        resolve = mock.AsyncMock(return_value={(9, "tank"): ResolvedRank(2500, "registration")})
        with mock.patch.object(roster_engine.ranks, "resolve", resolve):
            roster = await _resolve(
                _Session([(9, 77)]),
                registration,
                workspace_id=1,
                form=_flex_form("forced", enabled=False),
            )
        self.assertEqual([entry.role.slot_code for entry in roster.roles], ["tank"])
        self.assertEqual(roster.role_ranks, {"tank": 2500})
