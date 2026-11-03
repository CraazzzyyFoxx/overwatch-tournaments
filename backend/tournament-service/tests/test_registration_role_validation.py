"""Unit tests for registration role/sub-role validation and normalization.

Covers the sub-role fixes: catalog-driven validation (P4/P5), unified write-path
normalization (P3), and the shared sub-role catalog keying (P6).

The rules themselves now live in ``services/registration/roles_rules.py`` and
RETURN field errors instead of raising, so every assertion here is the list of
error codes the submission produces — ``[]`` meaning accepted.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


roles_rules = importlib.import_module("src.services.registration.roles_rules")
reg_common = importlib.import_module("src.services.registration._common")

from shared.core.errors import BaseAPIException  # noqa: E402
from shared.domain.forms.schema import FormField  # noqa: E402
from shared.domain.player_sub_roles import (  # noqa: E402
    build_subrole_catalog,
    canonical_to_registration_role,
)
from shared.domain.roles import DimensionNode, Ontology, RoleNode  # noqa: E402
from shared.hero_catalog import HeroCatalogEntry  # noqa: E402
from shared.testing.roles import rated_catalog  # noqa: E402


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
        role_codes=ROLE_CODES,
    )
    assert {error.field for error in errors} <= {"roles"}
    return [error.code for error in errors]


HERO_CATALOG = {
    slug: HeroCatalogEntry(id=entity_id, slug=slug)
    for entity_id, slug in enumerate(("ana", "kiriko", "ashe", "genji", "reinhardt", "dva"), start=1)
}

TOP_HEROES_ON = {"enabled": True}

ROLE_CODES = ("tank", "damage", "support")
CATALOG_ROLES = rated_catalog(sub_roles={"damage": ("hitscan",)})


def test_builder_resolves_form_suffix_to_parent_qualified_leaf() -> None:
    entries = reg_common.build_registration_roles(
        [{"role": "damage", "subrole": "Hitscan", "is_primary": True}],
        catalog_roles=CATALOG_ROLES,
        role_codes=ROLE_CODES,
    )
    assert [(entry.role, entry.subrole, entry.catalog_role.id) for entry in entries] == [
        ("damage", "damage_hitscan", 4),
    ]


def test_builder_drops_unknown_subrole_without_losing_top_role() -> None:
    entries = reg_common.build_registration_roles(
        [{"role": "support", "subrole": "hitscan"}],
        catalog_roles=CATALOG_ROLES,
        role_codes=ROLE_CODES,
    )
    assert [(entry.role, entry.subrole) for entry in entries] == [("support", None)]


class RoleRefInputTests(TestCase):
    def test_parentless_leaf_and_forged_parent_resolve_to_the_real_parent(self) -> None:
        for parent in (None, "support"):
            row = reg_common._role_row(
                CATALOG_ROLES, {"dimension": "player_role", "role": "damage_hitscan", "parent": parent}, None
            )
            assert row.catalog_role is CATALOG_ROLES["damage_hitscan"]
            assert row.role_ref.model_dump() == {
                "dimension": "player_role",
                "role": "damage_hitscan",
                "parent": "damage",
            }

    def test_role_ref_requires_the_rated_dimension_and_scoped_leaf(self) -> None:
        for ref, detail in (
            ({"dimension": "lane", "role": "damage"}, "role_dimension_mismatch"),
            ({"dimension": "player_role", "role": "support_other_workspace"}, "unknown_role"),
        ):
            with self.assertRaises(BaseAPIException) as caught:
                reg_common._role_row(CATALOG_ROLES, ref, None)
            assert caught.exception.status_code == 422
            assert detail in caught.exception.detail


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
        entries = reg_common.build_registration_roles(
            [_role_input(role="damage", subrole="Hitscan", is_primary=True)],
            catalog_roles=CATALOG_ROLES,
            role_codes=ROLE_CODES,
        )
        assert len(entries) == 1
        assert entries[0].role == "damage"
        assert entries[0].subrole == "damage_hitscan"

    def test_filters_invalid_role(self) -> None:
        entries = reg_common.build_registration_roles(
            [
                _role_input(role="flex", is_primary=True),
                _role_input(role="damage", is_primary=True),
            ],
            catalog_roles=CATALOG_ROLES,
            role_codes=ROLE_CODES,
        )
        assert [entry.role for entry in entries] == ["damage"]

    def test_dedup_and_priority(self) -> None:
        entries = reg_common.build_registration_roles(
            [
                _role_input(role="damage", is_primary=True),
                _role_input(role="damage", is_primary=False),
                _role_input(role="support", is_primary=False),
            ],
            catalog_roles=CATALOG_ROLES,
            role_codes=ROLE_CODES,
        )
        assert [entry.role for entry in entries] == ["damage", "support"]
        assert [entry.priority for entry in entries] == [0, 1]

    def test_handles_none(self) -> None:
        assert reg_common.build_registration_roles(None, catalog_roles=CATALOG_ROLES, role_codes=ROLE_CODES) == []


class TopHeroValidationTests(TestCase):
    def _codes(self, top_heroes: dict | None, roles: list[dict]) -> list[str]:
        params = {} if top_heroes is None else {"top_heroes": top_heroes}
        return _codes(_field(**params), roles, hero_catalog=HERO_CATALOG)

    def test_disabled_field_skips_hero_validation(self) -> None:
        # No top_heroes config -> characters are ignored, even unknown ones.
        assert self._codes(None, [{"role": "damage", "is_primary": True, "top_heroes": ["nobody"]}]) == []

    def test_no_role_is_inferred_from_a_characters_class(self) -> None:
        # A support-class character is a legal pick for a declared damage role: the
        # catalog entry carries no class at all, so nothing can compare it with the role.
        roles = [{"role": "damage", "is_primary": True, "top_heroes": ["ana", "ashe", "reinhardt"]}]
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

    def test_flex_submission_accepts_picks_on_every_role(self) -> None:
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


class MaxRolesTests(TestCase):
    TWO = [{"role": "tank", "is_primary": True}, {"role": "damage", "is_primary": False}]

    def test_two_roles_over_a_cap_of_one(self) -> None:
        assert _codes(_field(max_roles=1), self.TWO) == ["roles.too_many_roles"]

    def test_one_role_within_a_cap_of_one(self) -> None:
        assert _codes(_field(max_roles=1), self.TWO[:1]) == []

    def test_no_cap_by_default(self) -> None:
        assert _codes(_field(), self.TWO) == []


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
        entries = reg_common.build_registration_roles(
            [_role_input(role="damage", is_primary=True, top_heroes=["ashe", "genji"])],
            hero_catalog=HERO_CATALOG,
            catalog_roles=CATALOG_ROLES,
            role_codes=ROLE_CODES,
        )
        heroes = entries[0].hero_entries
        assert [(h.entity_id, h.priority) for h in heroes] == [(3, 1), (4, 2)]

    def test_caps_dedups_and_drops_unknown(self) -> None:
        entries = reg_common.build_registration_roles(
            [_role_input(role="damage", is_primary=True, top_heroes=["ashe", "genji", "ashe", "nobody"])],
            hero_catalog=HERO_CATALOG,
            max_heroes=2,
            catalog_roles=CATALOG_ROLES,
            role_codes=ROLE_CODES,
        )
        assert [h.entity_id for h in entries[0].hero_entries] == [3, 4]

    def test_no_catalog_means_no_hero_entries(self) -> None:
        entries = reg_common.build_registration_roles(
            [_role_input(role="damage", is_primary=True, top_heroes=["ashe"])],
            catalog_roles=CATALOG_ROLES,
            role_codes=ROLE_CODES,
        )
        assert list(entries[0].hero_entries) == []


class ReplaceRegistrationRoleCharactersTests(TestCase):
    """The typed (admin) role rows carry ``top_characters``; the persisted answer rows keep ``top_heroes``."""

    def _replace(self, roles: list[dict], *, hero_catalog=HERO_CATALOG):
        registration = SimpleNamespace(roles=[])
        reg_common.replace_registration_roles(
            registration, roles, catalog_roles=CATALOG_ROLES, hero_catalog=hero_catalog, max_heroes=2
        )
        return registration.roles

    def test_top_characters_are_validated_against_the_catalog_and_persisted(self) -> None:
        roles = self._replace(
            [{"role": "damage", "is_primary": True, "top_characters": ["ashe", "nobody", "genji", "dva"]}]
        )
        assert [(h.entity_id, h.priority) for h in roles[0].hero_entries] == [(3, 1), (4, 2)]

    def test_the_answer_spelling_is_not_a_second_input_on_the_typed_row(self) -> None:
        roles = self._replace([{"role": "damage", "is_primary": True, "top_heroes": ["ashe"]}])
        assert list(roles[0].hero_entries) == []

    def test_no_catalog_means_nothing_is_persisted(self) -> None:
        roles = self._replace([{"role": "damage", "is_primary": True, "top_characters": ["ashe"]}], hero_catalog=None)
        assert list(roles[0].hero_entries) == []


class SharedCatalogMappingTests(TestCase):
    def test_canonical_to_registration_role(self) -> None:
        assert canonical_to_registration_role("damage") == "damage"
        assert canonical_to_registration_role("support") == "support"
        assert canonical_to_registration_role("tank") == "tank"
        assert canonical_to_registration_role("nonsense") is None

    def test_build_catalog_keys_by_registration_role_code(self) -> None:
        ontology = Ontology(
            "overwatch",
            [DimensionNode(1, "player_role", "Role", "single", True)],
            [
                RoleNode(10, 1, "player_role", "tank", "Tank", sort_order=0),
                RoleNode(11, 1, "player_role", "damage", "Damage", sort_order=1),
                RoleNode(12, 1, "player_role", "support", "Support", sort_order=2),
                RoleNode(20, 1, "player_role", "hitscan", "Hitscan", parent_id=11, workspace_id=7),
                RoleNode(21, 1, "player_role", "main_heal", "Main Heal", parent_id=12, workspace_id=7),
                RoleNode(22, 1, "player_role", "main_tank", "Main Tank", parent_id=10, workspace_id=7),
                RoleNode(23, 1, "player_role", "other_ws", "Other", parent_id=10, workspace_id=8),
            ],
        )
        catalog = build_subrole_catalog(ontology, 7)
        assert catalog["damage"] == [{"slug": "hitscan", "label": "Hitscan"}]
        assert catalog["support"] == [{"slug": "main_heal", "label": "Main Heal"}]
        assert catalog["tank"] == [{"slug": "main_tank", "label": "Main Tank"}]

    def test_build_catalog_always_returns_all_codes(self) -> None:
        ontology = Ontology(
            "overwatch",
            [DimensionNode(1, "player_role", "Role", "single", True)],
            [
                RoleNode(10 + i, 1, "player_role", code, code, sort_order=i)
                for i, code in enumerate(("tank", "damage", "support"))
            ],
        )
        catalog = build_subrole_catalog(ontology, 7)
        assert set(catalog.keys()) == {"tank", "damage", "support"}
        assert all(value == [] for value in catalog.values())
