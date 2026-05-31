"""Unit tests for registration role/sub-role validation and normalization.

Covers the sub-role fixes: catalog-driven validation (P4/P5), unified write-path
normalization (P3), and the shared dps<->damage catalog mapping (P6).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

import pytest
from fastapi import HTTPException

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

validation = importlib.import_module("src.services.registration.validation")
reg_service = importlib.import_module("src.services.registration.service")
schemas = importlib.import_module("src.schemas.registration")

from shared.core import enums  # noqa: E402
from shared.domain.player_sub_roles import (  # noqa: E402
    build_subrole_catalog,
    canonical_to_registration_role,
)
from shared.hero_catalog import HeroCatalogEntry  # noqa: E402


def _form(built_in_fields: dict) -> SimpleNamespace:
    return SimpleNamespace(built_in_fields_json=built_in_fields, custom_fields_json=[])


HERO_CATALOG = {
    "ana": HeroCatalogEntry(id=1, slug="ana", hero_class=enums.HeroClass.support),
    "kiriko": HeroCatalogEntry(id=2, slug="kiriko", hero_class=enums.HeroClass.support),
    "ashe": HeroCatalogEntry(id=3, slug="ashe", hero_class=enums.HeroClass.damage),
    "genji": HeroCatalogEntry(id=4, slug="genji", hero_class=enums.HeroClass.damage),
    "reinhardt": HeroCatalogEntry(id=5, slug="reinhardt", hero_class=enums.HeroClass.tank),
    "dva": HeroCatalogEntry(id=6, slug="dva", hero_class=enums.HeroClass.tank),
}

TOP_HEROES_ON = {"top_heroes": {"enabled": True}}


def _payload(roles: list[dict]) -> schemas.RegistrationCreate:
    return schemas.RegistrationCreate(
        roles=[schemas.RoleWithSubrole(**role) for role in roles]
    )


CATALOG = {
    "tank": [{"slug": "main_tank", "label": "Main Tank"}],
    "dps": [
        {"slug": "hitscan", "label": "Hitscan"},
        {"slug": "projectile", "label": "Projectile"},
    ],
    "support": [{"slug": "main_heal", "label": "Main Heal"}],
}


class ValidateRolesTests(TestCase):
    def test_invalid_role_code_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc:
            validation.validate_registration_input(
                _form({}),
                _payload([{"role": "flex", "is_primary": True}]),
            )
        assert exc.value.status_code == 422

    def test_subrole_not_in_config_rejected(self) -> None:
        form = _form(
            {"primary_role": {"enabled": True, "subroles": {"dps": ["hitscan"]}}}
        )
        with pytest.raises(HTTPException) as exc:
            validation.validate_registration_input(
                form,
                _payload([{"role": "dps", "subrole": "projectile", "is_primary": True}]),
            )
        assert exc.value.status_code == 422

    def test_subrole_in_config_accepted(self) -> None:
        form = _form(
            {"primary_role": {"enabled": True, "subroles": {"dps": ["hitscan"]}}}
        )
        validation.validate_registration_input(
            form,
            _payload([{"role": "dps", "subrole": "hitscan", "is_primary": True}]),
        )

    def test_subrole_falls_back_to_catalog(self) -> None:
        form = _form({"primary_role": {"enabled": True}})
        # In catalog -> ok
        validation.validate_registration_input(
            form,
            _payload([{"role": "dps", "subrole": "hitscan", "is_primary": True}]),
            subrole_catalog=CATALOG,
        )
        # Not in catalog -> rejected
        with pytest.raises(HTTPException) as exc:
            validation.validate_registration_input(
                form,
                _payload([{"role": "dps", "subrole": "burst", "is_primary": True}]),
                subrole_catalog=CATALOG,
            )
        assert exc.value.status_code == 422

    def test_lenient_when_no_config_or_catalog(self) -> None:
        # Nothing configured anywhere -> accept any normalized sub-role.
        validation.validate_registration_input(
            _form({}),
            _payload([{"role": "dps", "subrole": "whatever", "is_primary": True}]),
        )

    def test_tank_subrole_via_catalog(self) -> None:
        validation.validate_registration_input(
            _form({"primary_role": {"enabled": True}}),
            _payload([{"role": "tank", "subrole": "main_tank", "is_primary": True}]),
            subrole_catalog=CATALOG,
        )

    def test_subrole_is_normalized_before_check(self) -> None:
        form = _form(
            {"primary_role": {"enabled": True, "subroles": {"support": ["main_heal"]}}}
        )
        # "Main Heal" normalizes to main_heal and passes.
        validation.validate_registration_input(
            form,
            _payload([{"role": "support", "subrole": "Main Heal", "is_primary": True}]),
        )

    def test_additional_roles_use_additional_config(self) -> None:
        form = _form(
            {
                "primary_role": {"enabled": True, "subroles": {"dps": ["hitscan"]}},
                "additional_roles": {"enabled": True, "subroles": {"dps": ["projectile"]}},
            }
        )
        # Secondary dps allows projectile (additional config), not hitscan.
        validation.validate_registration_input(
            form,
            _payload([{"role": "dps", "subrole": "projectile", "is_primary": False}]),
        )
        with pytest.raises(HTTPException):
            validation.validate_registration_input(
                form,
                _payload([{"role": "dps", "subrole": "hitscan", "is_primary": False}]),
            )


class BuildRegistrationRolesTests(TestCase):
    def test_normalizes_subrole(self) -> None:
        entries = reg_service.build_registration_roles(
            [schemas.RoleWithSubrole(role="dps", subrole="Main DPS", is_primary=True)]
        )
        assert len(entries) == 1
        assert entries[0].role == "dps"
        assert entries[0].subrole == "main_dps"

    def test_filters_invalid_role(self) -> None:
        entries = reg_service.build_registration_roles(
            [
                schemas.RoleWithSubrole(role="flex", is_primary=True),
                schemas.RoleWithSubrole(role="dps", is_primary=True),
            ]
        )
        assert [entry.role for entry in entries] == ["dps"]

    def test_dedup_and_priority(self) -> None:
        entries = reg_service.build_registration_roles(
            [
                schemas.RoleWithSubrole(role="dps", is_primary=True),
                schemas.RoleWithSubrole(role="dps", is_primary=False),
                schemas.RoleWithSubrole(role="support", is_primary=False),
            ]
        )
        assert [entry.role for entry in entries] == ["dps", "support"]
        assert [entry.priority for entry in entries] == [0, 1]

    def test_handles_none(self) -> None:
        assert reg_service.build_registration_roles(None) == []


class TopHeroValidationTests(TestCase):
    def _validate(self, built_in_fields: dict, roles: list[dict]) -> None:
        validation.validate_registration_input(
            _form(built_in_fields),
            _payload(roles),
            hero_catalog=HERO_CATALOG,
        )

    def test_disabled_field_skips_hero_validation(self) -> None:
        # No top_heroes config -> heroes are ignored even when class would mismatch.
        self._validate({}, [{"role": "dps", "is_primary": True, "top_heroes": ["ana"]}])

    def test_hero_class_must_match_non_flex_role(self) -> None:
        with pytest.raises(HTTPException) as exc:
            self._validate(TOP_HEROES_ON, [{"role": "dps", "is_primary": True, "top_heroes": ["ana"]}])
        assert exc.value.status_code == 422

    def test_matching_class_accepted(self) -> None:
        self._validate(TOP_HEROES_ON, [{"role": "dps", "is_primary": True, "top_heroes": ["ashe", "genji"]}])

    def test_unknown_hero_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc:
            self._validate(TOP_HEROES_ON, [{"role": "dps", "is_primary": True, "top_heroes": ["nobody"]}])
        assert exc.value.status_code == 422

    def test_duplicate_heroes_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc:
            self._validate(TOP_HEROES_ON, [{"role": "dps", "is_primary": True, "top_heroes": ["ashe", "ashe"]}])
        assert exc.value.status_code == 422

    def test_exceeding_configured_max_rejected(self) -> None:
        form = {"top_heroes": {"enabled": True, "max_heroes": 1}}
        with pytest.raises(HTTPException) as exc:
            self._validate(form, [{"role": "dps", "is_primary": True, "top_heroes": ["ashe", "genji"]}])
        assert exc.value.status_code == 422

    def test_default_max_is_five(self) -> None:
        many = ["ashe", "genji", "ashe", "genji", "ashe", "genji"]  # 6 items
        with pytest.raises(HTTPException) as exc:
            self._validate(TOP_HEROES_ON, [{"role": "dps", "is_primary": True, "top_heroes": many}])
        assert exc.value.status_code == 422

    def test_flex_accepts_any_class(self) -> None:
        # All-primary submission (flex) attaches any-class heroes -> class check skipped.
        self._validate(
            TOP_HEROES_ON,
            [
                {"role": "dps", "is_primary": True, "top_heroes": ["ana", "reinhardt"]},
                {"role": "tank", "is_primary": True},
                {"role": "support", "is_primary": True},
            ],
        )

    def test_required_without_heroes_rejected(self) -> None:
        form = {"top_heroes": {"enabled": True, "required": True}}
        with pytest.raises(HTTPException) as exc:
            self._validate(form, [{"role": "dps", "is_primary": True}])
        assert exc.value.status_code == 422

    def test_required_with_heroes_accepted(self) -> None:
        form = {"top_heroes": {"enabled": True, "required": True}}
        self._validate(form, [{"role": "dps", "is_primary": True, "top_heroes": ["ashe"]}])


class FlexGuardTests(TestCase):
    def test_flex_disabled_rejects_all_primary(self) -> None:
        form = _form({"flex_role": {"enabled": False}})
        with pytest.raises(HTTPException) as exc:
            validation.validate_registration_input(
                form,
                _payload(
                    [
                        {"role": "tank", "is_primary": True},
                        {"role": "dps", "is_primary": True},
                        {"role": "support", "is_primary": True},
                    ]
                ),
            )
        assert exc.value.status_code == 422

    def test_flex_disabled_allows_non_flex(self) -> None:
        form = _form({"flex_role": {"enabled": False}})
        validation.validate_registration_input(
            form,
            _payload([{"role": "dps", "is_primary": True}, {"role": "tank", "is_primary": False}]),
        )

    def test_flex_enabled_by_default(self) -> None:
        validation.validate_registration_input(
            _form({}),
            _payload(
                [
                    {"role": "tank", "is_primary": True},
                    {"role": "dps", "is_primary": True},
                    {"role": "support", "is_primary": True},
                ]
            ),
        )


class BuildRegistrationRoleHeroesTests(TestCase):
    def test_attaches_ordered_hero_entries(self) -> None:
        entries = reg_service.build_registration_roles(
            [schemas.RoleWithSubrole(role="dps", is_primary=True, top_heroes=["ashe", "genji"])],
            hero_catalog=HERO_CATALOG,
        )
        heroes = entries[0].hero_entries
        assert [(h.hero_id, h.priority) for h in heroes] == [(3, 1), (4, 2)]

    def test_caps_dedups_and_drops_unknown(self) -> None:
        entries = reg_service.build_registration_roles(
            [
                schemas.RoleWithSubrole(
                    role="dps", is_primary=True, top_heroes=["ashe", "genji", "ashe", "nobody"]
                )
            ],
            hero_catalog=HERO_CATALOG,
            max_heroes=2,
        )
        assert [h.hero_id for h in entries[0].hero_entries] == [3, 4]

    def test_no_catalog_means_no_hero_entries(self) -> None:
        entries = reg_service.build_registration_roles(
            [schemas.RoleWithSubrole(role="dps", is_primary=True, top_heroes=["ashe"])]
        )
        assert list(entries[0].hero_entries) == []


class SharedCatalogMappingTests(TestCase):
    def test_canonical_to_registration_role(self) -> None:
        assert canonical_to_registration_role("damage") == "dps"
        assert canonical_to_registration_role("dps") == "dps"
        assert canonical_to_registration_role("support") == "support"
        assert canonical_to_registration_role("tank") == "tank"
        assert canonical_to_registration_role("nonsense") is None

    def test_build_catalog_maps_damage_to_dps(self) -> None:
        rows = [
            SimpleNamespace(role="damage", slug="hitscan", label="Hitscan"),
            SimpleNamespace(role="support", slug="main_heal", label="Main Heal"),
            SimpleNamespace(role="tank", slug="main_tank", label="Main Tank"),
        ]
        catalog = build_subrole_catalog(rows)
        assert catalog["dps"] == [{"slug": "hitscan", "label": "Hitscan"}]
        assert catalog["support"] == [{"slug": "main_heal", "label": "Main Heal"}]
        assert catalog["tank"] == [{"slug": "main_tank", "label": "Main Tank"}]

    def test_build_catalog_always_returns_all_codes(self) -> None:
        catalog = build_subrole_catalog([])
        assert set(catalog.keys()) == {"tank", "dps", "support"}
        assert all(value == [] for value in catalog.values())
