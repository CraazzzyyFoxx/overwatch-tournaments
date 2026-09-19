"""Every-role tournaments (``flex_role.mode`` = ``all_roles`` / ``forced``).

Role does not matter in these tournaments, so every role has to be PLAYABLE --
and in the balancer, eligibility for a role IS carrying a rating for it
(``Player.can_play`` is ``role in ratings``, mirrored in Rust's ``context.rs``),
not an ``is_flex`` flag. A player ranked only on DPS could otherwise never be
placed as tank, so roles the registration never ranked inherit the player's
strongest number.

What the maximum must NOT do is overwrite a rank the registrant actually
stated: the draft shows the per-role number to the captain choosing a role, and
flattening all three turned that display into one value printed three times.

There used to be two implementations of this rule in Python
(``rules.map_registration`` for the draft, the admin list's own mapper for the
balancer) kept honest by a parity test. There is one now --
``shared.services.roster.RosterEngine`` -- so these tests pin its BEHAVIOUR
rather than an agreement between copies.

Design: docs/superpowers/specs/2026-08-04-forced-flex-max-rank-design.md
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from shared.core.enums import HERO_TYPE_CLASSES, HeroClass  # noqa: E402
from shared.division_grid import DEFAULT_GRID  # noqa: E402
from shared.domain.roster import PlayerRoster, flex_role_mode  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    BalancerRegistration,
    BalancerRegistrationRole,
)
from shared.services.roster import roster_engine  # noqa: E402

ALL_ROLE_VALUES = {role.slot_code for role in HERO_TYPE_CLASSES}


def _form(built_in: dict[str, Any] | None) -> Any:
    """The one thing the engine reads a registration form for: the flex mode."""
    return SimpleNamespace(built_in_fields_json=built_in)


def _role(
    role: str,
    *,
    priority: int = 0,
    is_primary: bool = False,
    is_active: bool = True,
    rank_value: int | None = None,
    subrole: str | None = None,
) -> BalancerRegistrationRole:
    return BalancerRegistrationRole(
        role=role,
        priority=priority,
        is_primary=is_primary,
        is_active=is_active,
        rank_value=rank_value,
        subrole=subrole,
    )


def _resolve(roles: list[BalancerRegistrationRole], *, mode: str | None = None) -> PlayerRoster:
    """Resolve one registration through the engine, with no database behind it.

    ``workspace_id=None`` means there is no canon and no Overwatch snapshot to
    inherit through, so the registration's own numbers are the only layer --
    which is exactly what these fixtures are about. ``form``/``grid`` are passed
    so the engine never reaches for a session.
    """
    registration = BalancerRegistration(id=1, tournament_id=1, battle_tag="Reg#1")
    registration.roles = roles
    rosters = asyncio.run(
        roster_engine.resolve(
            None,  # type: ignore[arg-type]
            [registration],
            workspace_id=None,
            tournament_id=1,
            form=_form(None if mode is None else {"flex_role": {"mode": mode}}),
            grid=DEFAULT_GRID,
        )
    )
    return rosters[1]


class TestFlexRoleMode:
    """THE reader of ``flex_role.mode``, now shared by the write path and the draft."""

    def test_forced(self) -> None:
        assert flex_role_mode(_form({"flex_role": {"mode": "forced"}})) == "forced"

    def test_all_roles(self) -> None:
        assert flex_role_mode(_form({"flex_role": {"mode": "all_roles"}})) == "all_roles"

    def test_optional_is_explicit(self) -> None:
        assert flex_role_mode(_form({"flex_role": {"mode": "optional"}})) == "optional"

    def test_absent_config_is_optional(self) -> None:
        assert flex_role_mode(_form({})) == "optional"

    def test_missing_form_fails_closed(self) -> None:
        assert flex_role_mode(None) == "optional"

    def test_unreadable_config_is_optional(self) -> None:
        assert flex_role_mode(_form({"flex_role": "yes"})) == "optional"
        assert flex_role_mode(_form(None)) == "optional"

    def test_a_disabled_field_outranks_the_mode_left_in_the_json(self) -> None:
        # A form cannot force every role playable through a field it does not
        # show. ``enabled: false`` therefore wins over a stale ``mode``.
        assert flex_role_mode(_form({"flex_role": {"enabled": False, "mode": "forced"}})) == "optional"
        assert flex_role_mode(_form({"flex_role": {"enabled": False, "mode": "all_roles"}})) == "optional"

    def test_an_unknown_mode_is_optional(self) -> None:
        assert flex_role_mode(_form({"flex_role": {"mode": "whatever"}})) == "optional"


class TestEveryRoleModeMakesEveryRolePlayable:
    def test_a_ranked_role_keeps_its_own_rank(self) -> None:
        """The draft shows this number per role, so it may not be overwritten."""
        resolved = _resolve(
            [
                _role("damage", priority=0, is_primary=True, rank_value=3900),
                _role("support", priority=1, is_primary=True, rank_value=2400),
            ],
            mode="all_roles",
        )

        # Tank was never ranked, so it takes the maximum: eligibility is the
        # presence of a rating, and that is the only value available for it.
        assert resolved.role_ranks == {"damage": 3900, "support": 2400, "tank": 3900}
        assert resolved.playable_roles == frozenset(HERO_TYPE_CLASSES)

    def test_the_best_rank_is_the_max_not_the_lead_role_s(self) -> None:
        """The bug this closes: the lead role's rank won even when lower."""
        resolved = _resolve(
            [
                _role("support", priority=0, is_primary=True, rank_value=2400),
                _role("damage", priority=1, is_primary=True, rank_value=3900),
            ],
            mode="all_roles",
        )

        assert resolved.primary is not None and resolved.primary.role is HeroClass.support
        assert resolved.best_rank == 3900

    def test_a_single_ranked_role_covers_the_other_two(self) -> None:
        """The target case: ranked on DPS only, still placeable as tank."""
        resolved = _resolve([_role("damage", is_primary=True, rank_value=3900)], mode="forced")

        assert resolved.role_ranks == dict.fromkeys(ALL_ROLE_VALUES, 3900)
        assert resolved.best_rank == 3900

    def test_inactive_roles_still_contribute_and_are_playable(self) -> None:
        """Sheet rows without a parsed rank arrive with is_active=False."""
        resolved = _resolve([_role("tank", is_primary=True, is_active=False, rank_value=3100)], mode="all_roles")

        assert resolved.role_ranks == dict.fromkeys(ALL_ROLE_VALUES, 3100)

    def test_no_ranks_at_all_leaves_nobody_playable(self) -> None:
        # There is no number to spread, so every role stays unplayable and the
        # player is not draftable at all -- the pool reports them instead of the
        # draft minting a rank-0 body.
        resolved = _resolve([_role("damage", is_primary=True)], mode="forced")

        assert resolved.role_ranks == {}
        assert resolved.best_rank is None
        assert resolved.is_draftable is False
        assert resolved.primary is None

    def test_all_three_roles_are_covered_even_from_one_entry(self) -> None:
        resolved = _resolve([_role("damage", is_primary=True, rank_value=3000)], mode="forced")

        lead = resolved.primary
        assert lead is not None
        assert {lead.role, *resolved.secondary_roles} == set(HERO_TYPE_CLASSES)

    def test_sub_role_comes_from_the_first_role_by_priority(self) -> None:
        resolved = _resolve(
            [
                _role("support", priority=0, is_primary=True, rank_value=3000, subrole="main_heal"),
                _role("damage", priority=1, is_primary=True, rank_value=3000, subrole="hitscan"),
            ],
            mode="forced",
        )

        assert resolved.sub_role == "main_heal"

    def test_full_flex_still_comes_from_the_registration(self) -> None:
        # ``is_full_flex`` is the registration's own fact (more than one role,
        # every one primary), not something the mode stamps on.
        every_role_primary = _resolve(
            [
                _role("damage", priority=0, is_primary=True, rank_value=3000),
                _role("tank", priority=1, is_primary=True, rank_value=3000),
            ],
            mode="all_roles",
        )
        one_priority_role = _resolve(
            [
                _role("damage", priority=0, is_primary=True, rank_value=3000),
                _role("tank", priority=1, rank_value=3000),
            ],
            mode="all_roles",
        )

        assert every_role_primary.is_full_flex is True
        assert one_priority_role.is_full_flex is False


class TestAllRolesModeKeepsThePriority:
    """``all_roles`` differs from ``forced`` in exactly one respect.

    Both make every role playable and carrying a rating, because balancer
    eligibility demands one per role. Only ``forced`` also forces every role
    primary (on the WRITE path). Under ``all_roles`` the registrant's single
    priority role survives, which is what keeps a real balance-versus-comfort
    trade-off alive: a forced tournament has zero discomfort everywhere and the
    solver's second objective collapses to sub-role collisions.
    """

    def test_the_priority_role_becomes_primary(self) -> None:
        resolved = _resolve(
            [
                _role("tank", priority=0, is_primary=True, rank_value=3300),
                _role("damage", priority=1, rank_value=2800),
                _role("support", priority=2, rank_value=3000),
            ],
            mode="all_roles",
        )

        assert resolved.primary is not None and resolved.primary.role is HeroClass.tank
        assert set(resolved.secondary_roles) == {HeroClass.damage, HeroClass.support}

    def test_every_role_is_rated_without_losing_the_stated_ranks(self) -> None:
        resolved = _resolve(
            [
                _role("tank", priority=0, is_primary=True, rank_value=2800),
                _role("damage", priority=1, rank_value=3900),
            ],
            mode="all_roles",
        )

        # Support is unrated and takes the maximum; tank keeps the 2800 the
        # registrant stated, which is what the draft shows on the tank row.
        assert resolved.role_ranks == {"tank": 2800, "damage": 3900, "support": 3900}
        assert resolved.best_rank == 3900


class TestOptionalModeIsUnchanged:
    def test_per_role_ranks_are_preserved(self) -> None:
        resolved = _resolve(
            [
                _role("damage", priority=0, is_primary=True, rank_value=3900),
                _role("support", priority=1, rank_value=2400),
            ]
        )

        assert resolved.role_ranks == {"damage": 3900, "support": 2400}

    def test_the_lead_role_is_the_priority_one(self) -> None:
        resolved = _resolve(
            [
                _role("support", priority=0, is_primary=True, rank_value=2400),
                _role("damage", priority=1, rank_value=3900),
            ]
        )

        assert resolved.primary is not None and resolved.primary.role is HeroClass.support
        assert resolved.rank_on(HeroClass.support) == 2400

    def test_an_unranked_role_is_declared_but_not_playable(self) -> None:
        # No spreading here: the role stays in ``roles`` (so the pool can report
        # the registration as incomplete) and out of ``playable_roles``.
        resolved = _resolve(
            [
                _role("damage", priority=0, is_primary=True, rank_value=3900),
                _role("support", priority=1),
            ]
        )

        assert {entry.role for entry in resolved.roles} == {HeroClass.damage, HeroClass.support}
        assert resolved.playable_roles == frozenset({HeroClass.damage})
        assert resolved.is_ranked_complete is False

    def test_inactive_roles_are_dropped(self) -> None:
        resolved = _resolve(
            [
                _role("damage", priority=0, is_primary=True, rank_value=3900),
                _role("tank", priority=1, is_active=False, rank_value=3100),
            ]
        )

        assert resolved.role_ranks == {"damage": 3900}
        assert resolved.secondary_roles == ()


class TestDiscomfortDivergesFromTheBalancer:
    """Witness for a pre-existing mirror that ``all_roles`` makes visible.

    The draft and the balancer both encode "how much does this role hurt", in
    separate code. For a registrant with one priority role and two playable
    others, measured:

    | role     | balancer | draft |
    |----------|----------|-------|
    | priority |        0 |     0 |
    | other    |      100 |  1000 |
    | other    |      200 |  1000 |

    The draft penalises a non-priority role 5-10x harder because
    ``preference_order`` carries only the lead role (``services/draft/selection.py``),
    while the balancer builds a full ordering from ``priority``
    (``player_loader``). It also hands the two non-priority roles DIFFERENT
    penalties, from row order the registrant never expressed.

    ``forced`` hid this: every role is primary there, so discomfort is nil on
    both sides. This test does not assert the desired behaviour -- it pins the
    current divergence so closing it becomes a deliberate, visible change. See
    docs/superpowers/specs/2026-08-04-code-mirrors-registry.md, class D.
    """

    def test_draft_penalises_non_priority_roles_uniformly_and_harder(self) -> None:
        from src.domain.draft import fit as sug

        player = sug.FitPlayer(
            player_id=1,
            rank_value=3300,
            playable_roles=frozenset(HERO_TYPE_CLASSES),
            preference_order=(HeroClass.tank,),
            is_flex=False,
            rank_by_role=dict.fromkeys(HERO_TYPE_CLASSES, 3300),
        )

        assert sug.role_discomfort(player, HeroClass.tank) == 0
        assert sug.role_discomfort(player, HeroClass.damage) == 1000
        assert sug.role_discomfort(player, HeroClass.support) == 1000

    def test_balancer_penalises_them_by_position_instead(self) -> None:
        from src.domain.balancer.entities import Player

        mask = {"Tank": 1, "Damage": 2, "Support": 2}
        player = Player(
            "x",
            {"Tank": 3300, "Damage": 3300, "Support": 3300},
            ["Tank", "Damage", "Support"],
            "u",
            mask,
            is_flex=False,
        )

        assert player.get_discomfort("Tank") == 0
        assert player.get_discomfort("Damage") == 100
        assert player.get_discomfort("Support") == 200
