"""Unit tests for registration role/sub-role validation and normalization.

Covers the sub-role fixes: catalog-driven validation (P4/P5), unified write-path
normalization (P3), and the shared sub-role catalog keying (P6).

The rules themselves now live in ``services/registration/roles_rules.py`` and
RETURN field errors instead of raising, so every assertion here is the list of
error codes the submission produces — ``[]`` meaning accepted.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

roles_rules = importlib.import_module("src.services.registration.roles_rules")
reg_service = importlib.import_module("src.services.registration.service")

from shared.core import enums  # noqa: E402
from shared.domain.forms.schema import FormField  # noqa: E402
from shared.domain.player_sub_roles import (  # noqa: E402
    build_subrole_catalog,
    canonical_to_registration_role,
)
from shared.hero_catalog import HeroCatalogEntry  # noqa: E402


def _field(**params: Any) -> FormField:
    """The schema's ``roles`` field carrying the organizer's configuration."""
    return FormField(key="roles", kind="builtin", params=params)


def _codes(
    field: FormField,
    roles: list[dict],
    *,
    subrole_catalog: dict | None = None,
    hero_catalog: dict | None = None,
) -> list[str]:
    errors = roles_rules.validate_roles(
        field,
        roles,
        subrole_catalog=subrole_catalog,
        hero_catalog=hero_catalog,
    )
    assert {error.field for error in errors} <= {"roles"}
    return [error.code for error in errors]


HERO_CATALOG = {
    "ana": HeroCatalogEntry(id=1, slug="ana", hero_class=enums.HeroClass.support),
    "kiriko": HeroCatalogEntry(id=2, slug="kiriko", hero_class=enums.HeroClass.support),
    "ashe": HeroCatalogEntry(id=3, slug="ashe", hero_class=enums.HeroClass.damage),
    "genji": HeroCatalogEntry(id=4, slug="genji", hero_class=enums.HeroClass.damage),
    "reinhardt": HeroCatalogEntry(id=5, slug="reinhardt", hero_class=enums.HeroClass.tank),
    "dva": HeroCatalogEntry(id=6, slug="dva", hero_class=enums.HeroClass.tank),
}

TOP_HEROES_ON = {"enabled": True}


def _role_input(**spec) -> SimpleNamespace:
    """One submitted role row for the write path. ``build_registration_roles``
    reads these by attribute, so a namespace is the whole contract."""
    return SimpleNamespace(**{"role": None, "subrole": None, "is_primary": False, "top_heroes": None, **spec})


CATALOG = {
    "tank": [{"slug": "main_tank", "label": "Main Tank"}],
    "damage": [
        {"slug": "hitscan", "label": "Hitscan"},
        {"slug": "projectile", "label": "Projectile"},
    ],
    "support": [{"slug": "main_heal", "label": "Main Heal"}],
}


class ValidateRolesTests(TestCase):
    def test_invalid_role_code_rejected(self) -> None:
        assert _codes(_field(), [{"role": "flex", "is_primary": True}]) == ["roles.unknown_role"]

    def test_subrole_not_in_config_rejected(self) -> None:
        field = _field(subroles={"damage": ["hitscan"]})
        roles = [{"role": "damage", "subrole": "projectile", "is_primary": True}]
        assert _codes(field, roles) == ["roles.subrole_not_allowed"]

    def test_subrole_in_config_accepted(self) -> None:
        field = _field(subroles={"damage": ["hitscan"]})
        assert _codes(field, [{"role": "damage", "subrole": "hitscan", "is_primary": True}]) == []

    def test_subrole_falls_back_to_catalog(self) -> None:
        field = _field()
        # In catalog -> ok
        assert (
            _codes(
                field,
                [{"role": "damage", "subrole": "hitscan", "is_primary": True}],
                subrole_catalog=CATALOG,
            )
            == []
        )
        # Not in catalog -> rejected
        assert _codes(
            field,
            [{"role": "damage", "subrole": "burst", "is_primary": True}],
            subrole_catalog=CATALOG,
        ) == ["roles.subrole_not_allowed"]

    def test_lenient_when_no_config_or_catalog(self) -> None:
        # Nothing configured anywhere -> accept any normalized sub-role.
        assert _codes(_field(), [{"role": "damage", "subrole": "whatever", "is_primary": True}]) == []

    def test_tank_subrole_via_catalog(self) -> None:
        assert (
            _codes(
                _field(),
                [{"role": "tank", "subrole": "main_tank", "is_primary": True}],
                subrole_catalog=CATALOG,
            )
            == []
        )

    def test_subrole_is_normalized_before_check(self) -> None:
        field = _field(subroles={"support": ["main_heal"]})
        # "Main Heal" normalizes to main_heal and passes.
        assert _codes(field, [{"role": "support", "subrole": "Main Heal", "is_primary": True}]) == []

    def test_non_primary_roles_are_checked_against_the_same_config(self) -> None:
        # The pre-schema config split ``subroles`` across primary_role and
        # additional_roles; ``RolesParams.subroles`` is one map per role code,
        # so what survives is that a secondary row is validated too.
        field = _field(primary_required=False, subroles={"damage": ["projectile"]})
        assert _codes(field, [{"role": "damage", "subrole": "projectile", "is_primary": False}]) == []
        assert _codes(field, [{"role": "damage", "subrole": "hitscan", "is_primary": False}]) == [
            "roles.subrole_not_allowed"
        ]


class BuildRegistrationRolesTests(TestCase):
    def test_normalizes_subrole(self) -> None:
        entries = reg_service.build_registration_roles(
            [_role_input(role="damage", subrole="Main Damage", is_primary=True)]
        )
        assert len(entries) == 1
        assert entries[0].role == "damage"
        assert entries[0].subrole == "main_damage"

    def test_filters_invalid_role(self) -> None:
        entries = reg_service.build_registration_roles(
            [
                _role_input(role="flex", is_primary=True),
                _role_input(role="damage", is_primary=True),
            ]
        )
        assert [entry.role for entry in entries] == ["damage"]

    def test_dedup_and_priority(self) -> None:
        entries = reg_service.build_registration_roles(
            [
                _role_input(role="damage", is_primary=True),
                _role_input(role="damage", is_primary=False),
                _role_input(role="support", is_primary=False),
            ]
        )
        assert [entry.role for entry in entries] == ["damage", "support"]
        assert [entry.priority for entry in entries] == [0, 1]

    def test_handles_none(self) -> None:
        assert reg_service.build_registration_roles(None) == []


class TopHeroValidationTests(TestCase):
    def _codes(self, top_heroes: dict | None, roles: list[dict]) -> list[str]:
        params = {} if top_heroes is None else {"top_heroes": top_heroes}
        return _codes(_field(**params), roles, hero_catalog=HERO_CATALOG)

    def test_disabled_field_skips_hero_validation(self) -> None:
        # No top_heroes config -> heroes are ignored even when class would mismatch.
        assert self._codes(None, [{"role": "damage", "is_primary": True, "top_heroes": ["ana"]}]) == []

    def test_hero_class_must_match_non_flex_role(self) -> None:
        roles = [{"role": "damage", "is_primary": True, "top_heroes": ["ana"]}]
        assert self._codes(TOP_HEROES_ON, roles) == ["roles.hero_wrong_class"]

    def test_matching_class_accepted(self) -> None:
        roles = [{"role": "damage", "is_primary": True, "top_heroes": ["ashe", "genji"]}]
        assert self._codes(TOP_HEROES_ON, roles) == []

    def test_unknown_hero_rejected(self) -> None:
        roles = [{"role": "damage", "is_primary": True, "top_heroes": ["nobody"]}]
        assert self._codes(TOP_HEROES_ON, roles) == ["invalid_option"]

    def test_duplicate_heroes_rejected(self) -> None:
        roles = [{"role": "damage", "is_primary": True, "top_heroes": ["ashe", "ashe"]}]
        assert self._codes(TOP_HEROES_ON, roles) == ["invalid_option"]

    def test_exceeding_configured_max_rejected(self) -> None:
        roles = [{"role": "damage", "is_primary": True, "top_heroes": ["ashe", "genji"]}]
        assert self._codes({"enabled": True, "max": 1}, roles) == ["roles.too_many_heroes"]

    def test_default_max_is_five(self) -> None:
        many = ["ashe", "genji", "ashe", "genji", "ashe", "genji"]  # 6 items
        roles = [{"role": "damage", "is_primary": True, "top_heroes": many}]
        # Collect-every-error: the old validator stopped at the count.
        assert self._codes(TOP_HEROES_ON, roles) == ["roles.too_many_heroes", "invalid_option"]

    def test_flex_accepts_any_class(self) -> None:
        # All-primary submission (flex) attaches any-class heroes -> class check skipped.
        assert (
            self._codes(
                TOP_HEROES_ON,
                [
                    {"role": "damage", "is_primary": True, "top_heroes": ["ana", "reinhardt"]},
                    {"role": "tank", "is_primary": True},
                    {"role": "support", "is_primary": True},
                ],
            )
            == []
        )

    def test_required_without_heroes_rejected(self) -> None:
        required = {"enabled": True, "required": True}
        assert self._codes(required, [{"role": "damage", "is_primary": True}]) == ["required"]

    def test_required_with_heroes_accepted(self) -> None:
        required = {"enabled": True, "required": True}
        roles = [{"role": "damage", "is_primary": True, "top_heroes": ["ashe"]}]
        assert self._codes(required, roles) == []


class FlexGuardTests(TestCase):
    FULL_FLEX = [
        {"role": "tank", "is_primary": True},
        {"role": "damage", "is_primary": True},
        {"role": "support", "is_primary": True},
    ]

    def test_flex_disabled_rejects_all_primary(self) -> None:
        assert _codes(_field(flex_allowed=False), self.FULL_FLEX) == ["roles.flex_unavailable"]

    def test_flex_disabled_allows_non_flex(self) -> None:
        roles = [{"role": "damage", "is_primary": True}, {"role": "tank", "is_primary": False}]
        assert _codes(_field(flex_allowed=False), roles) == []

    def test_flex_enabled_by_default(self) -> None:
        assert _codes(_field(), self.FULL_FLEX) == []


class AdditionalRolesRequiredTests(TestCase):
    """``additional_required``: the submission must cover more than the
    priority role. The guard used to read ``not is_flex and not any(not
    is_primary)`` over an ``is_flex`` missing its ``len > 1`` term, i.e.
    ``¬P ∧ P`` -- the organizer's toggle never rejected anything.
    """

    FIELD = _field(additional_required=True)

    def test_single_primary_role_is_rejected(self) -> None:
        assert _codes(self.FIELD, [{"role": "tank", "is_primary": True}]) == ["roles.additional_required"]

    def test_secondary_role_satisfies_it(self) -> None:
        roles = [{"role": "tank", "is_primary": True}, {"role": "damage", "is_primary": False}]
        assert _codes(self.FIELD, roles) == []

    def test_full_flex_satisfies_it(self) -> None:
        assert _codes(self.FIELD, FlexGuardTests.FULL_FLEX) == []


class AllRolesModeGuardTests(TestCase):
    """``all_roles``: exactly one priority role, or flex. Nothing in between.

    The write-path normalizer backfills the role SET but cannot invent which role
    the registrant meant, so a payload with no priority — or two — is rejected
    rather than guessed at.
    """

    # ``primary_required=False`` mirrors the old fixture, which configured
    # ``flex_role.mode`` alone and left ``primary_role`` unset.
    FIELD = _field(flex_mode="all_roles", primary_required=False)

    def test_accepts_exactly_one_priority(self) -> None:
        roles = [
            {"role": "tank", "is_primary": True},
            {"role": "damage", "is_primary": False},
            {"role": "support", "is_primary": False},
        ]
        assert _codes(self.FIELD, roles) == []

    def test_accepts_flex(self) -> None:
        assert _codes(self.FIELD, FlexGuardTests.FULL_FLEX) == []

    def test_rejects_no_priority(self) -> None:
        roles = [
            {"role": "tank", "is_primary": False},
            {"role": "damage", "is_primary": False},
            {"role": "support", "is_primary": False},
        ]
        assert _codes(self.FIELD, roles) == ["roles.one_priority_or_flex"]

    def test_rejects_two_priorities(self) -> None:
        roles = [
            {"role": "tank", "is_primary": True},
            {"role": "damage", "is_primary": True},
            {"role": "support", "is_primary": False},
        ]
        assert _codes(self.FIELD, roles) == ["roles.one_priority_or_flex"]

    def test_optional_mode_still_allows_two_primaries(self) -> None:
        """The guard is scoped to the mode; nothing else changes behaviour."""
        roles = [{"role": "tank", "is_primary": True}, {"role": "damage", "is_primary": True}]
        assert _codes(_field(), roles) == []


class BuildRegistrationRoleHeroesTests(TestCase):
    def test_attaches_ordered_hero_entries(self) -> None:
        entries = reg_service.build_registration_roles(
            [_role_input(role="damage", is_primary=True, top_heroes=["ashe", "genji"])],
            hero_catalog=HERO_CATALOG,
        )
        heroes = entries[0].hero_entries
        assert [(h.hero_id, h.priority) for h in heroes] == [(3, 1), (4, 2)]

    def test_caps_dedups_and_drops_unknown(self) -> None:
        entries = reg_service.build_registration_roles(
            [_role_input(role="damage", is_primary=True, top_heroes=["ashe", "genji", "ashe", "nobody"])],
            hero_catalog=HERO_CATALOG,
            max_heroes=2,
        )
        assert [h.hero_id for h in entries[0].hero_entries] == [3, 4]

    def test_no_catalog_means_no_hero_entries(self) -> None:
        entries = reg_service.build_registration_roles(
            [_role_input(role="damage", is_primary=True, top_heroes=["ashe"])]
        )
        assert list(entries[0].hero_entries) == []


class SharedCatalogMappingTests(TestCase):
    def test_canonical_to_registration_role(self) -> None:
        assert canonical_to_registration_role("damage") == "damage"
        assert canonical_to_registration_role("support") == "support"
        assert canonical_to_registration_role("tank") == "tank"
        assert canonical_to_registration_role("nonsense") is None

    def test_build_catalog_keys_by_registration_role_code(self) -> None:
        rows = [
            SimpleNamespace(role="damage", slug="hitscan", label="Hitscan"),
            SimpleNamespace(role="support", slug="main_heal", label="Main Heal"),
            SimpleNamespace(role="tank", slug="main_tank", label="Main Tank"),
        ]
        catalog = build_subrole_catalog(rows)
        assert catalog["damage"] == [{"slug": "hitscan", "label": "Hitscan"}]
        assert catalog["support"] == [{"slug": "main_heal", "label": "Main Heal"}]
        assert catalog["tank"] == [{"slug": "main_tank", "label": "Main Tank"}]

    def test_build_catalog_always_returns_all_codes(self) -> None:
        catalog = build_subrole_catalog([])
        assert set(catalog.keys()) == {"tank", "damage", "support"}
        assert all(value == [] for value in catalog.values())
