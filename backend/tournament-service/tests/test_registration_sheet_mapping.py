"""Unit tests for the Google Sheets → registration mapping engine v2.

Covers the pure catalog/validation/coercion module (``mapping_catalog``) plus the
engine refactor in ``admin.py`` (custom-field parsing, per-row error collection,
language-agnostic suggestions). Pure unit tests — no database — mirroring the
existing registration test bootstrap.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

catalog = importlib.import_module("src.domain.registration.mapping_catalog")
schemas = importlib.import_module("src.schemas.registration")
sheet_parsing = importlib.import_module("src.domain.registration.sheet_parsing")
sheet_sync = importlib.import_module("src.services.registration.sheet_sync")

CustomFieldDefinition = schemas.CustomFieldDefinition
FieldValidationConfig = schemas.FieldValidationConfig

# The canonical built-in target set as it existed before the catalog refactor.
LEGACY_BUILTIN_TARGETS = {
    "source_record_key",
    "display_name",
    "battle_tag",
    "submitted_at",
    "smurf_tags",
    "discord_nick",
    "twitch_nick",
    "boosty_nick",
    "stream_pov",
    "notes",
    "source_roles.primary",
    "source_roles.additional",
    "is_flex",
    "admin_notes",
    "roles.tank.rank_value",
    "roles.tank.division_input",
    "roles.tank.is_active",
    "roles.tank.priority",
    "roles.damage.rank_value",
    "roles.damage.division_input",
    "roles.damage.subrole",
    "roles.damage.is_active",
    "roles.damage.priority",
    "roles.support.rank_value",
    "roles.support.division_input",
    "roles.support.subrole",
    "roles.support.is_active",
    "roles.support.priority",
}


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def test_builtin_specs_match_legacy_target_set():
    keys = {spec.key for spec in catalog.build_target_specs([])}
    assert keys == LEGACY_BUILTIN_TARGETS


def test_catalog_default_targets_alias_matches_admin():
    # The admin module should expose the same target set (post-refactor import).
    assert set(catalog.DEFAULT_MAPPING_TARGETS) == LEGACY_BUILTIN_TARGETS
    assert set(catalog.DEFAULT_MAPPING_TARGETS) == LEGACY_BUILTIN_TARGETS


def test_custom_field_specs_added_with_type_parsers():
    custom = [
        CustomFieldDefinition(key="age", label="Age", type="number"),
        CustomFieldDefinition(key="region", label="Region", type="select", options=["EU", "NA"]),
        CustomFieldDefinition(key="agree", label="Agree", type="checkbox"),
        CustomFieldDefinition(key="bio", label="Bio", type="text"),
    ]
    specs = catalog.target_spec_map(custom)
    assert specs["custom_fields.age"].default_parser == catalog.PARSER_INTEGER
    assert specs["custom_fields.region"].default_parser == catalog.PARSER_STRING
    assert specs["custom_fields.agree"].default_parser == catalog.PARSER_BOOLEAN
    assert specs["custom_fields.bio"].default_parser == catalog.PARSER_STRING
    assert specs["custom_fields.age"].group == "custom_fields"


def test_parser_catalog_covers_all_accepted_parsers():
    referenced = {p for spec in catalog.BUILTIN_TARGET_SPECS for p in spec.accepted_parsers}
    assert referenced <= catalog.VALID_PARSERS


def test_mapping_catalog_includes_all_value_mapping_categories():
    built = sheet_sync.build_mapping_catalog([])
    assert {category["category"] for category in built["value_categories"]} == {
        "booleans",
        "roles",
        "subroles",
        "role_subroles",
        "divisions",
    }


def test_mapping_catalog_merges_saved_value_maps():
    built = sheet_sync.build_mapping_catalog([], value_mapping={"roles": {"healer": "support"}})
    categories = {category["category"]: category["entries"] for category in built["value_categories"]}
    assert categories["roles"]["healer"] == "support"
    assert "tank" not in categories["roles"]


# ---------------------------------------------------------------------------
# Custom-field coercion
# ---------------------------------------------------------------------------


def test_coerce_number_ok_and_blank_and_bad():
    field_def = CustomFieldDefinition(key="age", label="Age", type="number")
    assert catalog.coerce_custom_field_value(field_def, "42").value == 42
    assert catalog.coerce_custom_field_value(field_def, "  ").value is None
    bad = catalog.coerce_custom_field_value(field_def, "abc")
    assert bad.value is None
    assert bad.error is not None


def test_coerce_checkbox_uses_boolean_defaults_and_value_map():
    field_def = CustomFieldDefinition(key="agree", label="Agree", type="checkbox")
    assert catalog.coerce_custom_field_value(field_def, "да").value is True
    assert catalog.coerce_custom_field_value(field_def, "no").value is False
    # Custom boolean mapping wins.
    result = catalog.coerce_custom_field_value(field_def, "oui", value_mapping={"booleans": {"oui": True}})
    assert result.value is True
    overridden = catalog.coerce_custom_field_value(field_def, "yes", value_mapping={"booleans": {"yes": False}})
    assert overridden.value is False


def test_coerce_select_warns_outside_options():
    field_def = CustomFieldDefinition(key="region", label="Region", type="select", options=["EU", "NA"])
    ok = catalog.coerce_custom_field_value(field_def, "EU")
    assert ok.value == "EU" and ok.warning is None
    outside = catalog.coerce_custom_field_value(field_def, "ASIA")
    assert outside.value == "ASIA" and outside.warning is not None


def test_coerce_text_regex_warning():
    field_def = CustomFieldDefinition(
        key="code",
        label="Code",
        type="text",
        validation=FieldValidationConfig(regex=r"\d{3}", error_message="need 3 digits"),
    )
    assert catalog.coerce_custom_field_value(field_def, "123").warning is None
    bad = catalog.coerce_custom_field_value(field_def, "ab")
    assert bad.value == "ab" and bad.warning == "need 3 digits"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _specs():
    return catalog.target_spec_map([])


def _codes(issues):
    return {issue.code for issue in issues}


def test_validate_valid_config_has_no_issues():
    config = {"targets": {"battle_tag": {"mode": "columns", "columns": ["A"], "parser": "battle_tag"}}}
    issues = catalog.validate_mapping_config(config, target_specs=_specs(), header_keys=["A", "B"])
    assert issues == []


def test_validate_unknown_target():
    config = {"targets": {"nope": {"mode": "columns", "columns": ["A"]}}}
    issues = catalog.validate_mapping_config(config, target_specs=_specs(), header_keys=["A"])
    assert "unknown_target" in _codes(issues)


def test_validate_unknown_column():
    config = {"targets": {"battle_tag": {"mode": "columns", "columns": ["Z"], "parser": "battle_tag"}}}
    issues = catalog.validate_mapping_config(config, target_specs=_specs(), header_keys=["A"])
    assert "unknown_column" in _codes(issues)


def test_validate_too_many_columns_on_single():
    config = {"targets": {"battle_tag": {"mode": "columns", "columns": ["A", "B"], "parser": "battle_tag"}}}
    issues = catalog.validate_mapping_config(config, target_specs=_specs(), header_keys=["A", "B"])
    assert "too_many_columns" in _codes(issues)


def test_validate_multi_column_allowed_on_smurf_tags():
    config = {
        "targets": {
            "battle_tag": {"mode": "columns", "columns": ["A"], "parser": "battle_tag"},
            "smurf_tags": {"mode": "columns", "columns": ["B", "C"], "parser": "battle_tag_list"},
        }
    }
    issues = catalog.validate_mapping_config(config, target_specs=_specs(), header_keys=["A", "B", "C"])
    assert issues == []


def test_validate_invalid_parser_for_target():
    config = {"targets": {"battle_tag": {"mode": "columns", "columns": ["A"], "parser": "datetime"}}}
    issues = catalog.validate_mapping_config(config, target_specs=_specs(), header_keys=["A"])
    assert "invalid_parser_for_target" in _codes(issues)


def test_validate_missing_constant_value():
    config = {
        "targets": {
            "battle_tag": {"mode": "columns", "columns": ["A"], "parser": "battle_tag"},
            "stream_pov": {"mode": "constant", "parser": "boolean"},
        }
    }
    issues = catalog.validate_mapping_config(config, target_specs=_specs(), header_keys=["A"])
    assert "missing_constant_value" in _codes(issues)


def test_validate_missing_identity_target():
    config = {"targets": {"display_name": {"mode": "columns", "columns": ["A"], "parser": "string"}}}
    issues = catalog.validate_mapping_config(config, target_specs=_specs(), header_keys=["A"])
    assert "missing_identity_target" in _codes(issues)


def test_validate_skips_column_checks_without_headers():
    config = {"targets": {"battle_tag": {"mode": "columns", "columns": ["Z"], "parser": "battle_tag"}}}
    issues = catalog.validate_mapping_config(config, target_specs=_specs(), header_keys=None)
    assert "unknown_column" not in _codes(issues)


# ---------------------------------------------------------------------------
# Row disposition
# ---------------------------------------------------------------------------


def test_classify_row_disposition():
    known_keys = {"abc#1"}
    known_tags = {"def#2"}
    assert (
        catalog.classify_row_disposition(None, None, known_source_keys=known_keys, known_battle_tag_keys=known_tags)
        == "skip"
    )
    assert (
        catalog.classify_row_disposition("abc#1", None, known_source_keys=known_keys, known_battle_tag_keys=known_tags)
        == "update"
    )
    assert (
        catalog.classify_row_disposition(
            "new#9", "def#2", known_source_keys=known_keys, known_battle_tag_keys=known_tags
        )
        == "update"
    )
    assert (
        catalog.classify_row_disposition(
            "new#9", "zzz#3", known_source_keys=known_keys, known_battle_tag_keys=known_tags
        )
        == "create"
    )


# ---------------------------------------------------------------------------
# Engine: suggestions are language-agnostic
# ---------------------------------------------------------------------------


def test_suggest_mapping_matches_english_and_russian_headers():
    russian = ["Отметка времени", "Ваш Battle Tag", "Укажите вашу роль", "Смурф аккаунты"]
    english = ["Timestamp", "Your Battle Tag", "Your role", "Smurf accounts"]
    for headers in (russian, english):
        mapping = sheet_parsing.suggest_mapping_from_headers(headers)
        targets = mapping["targets"]
        assert targets["battle_tag"]["mode"] == "columns"
        assert targets["submitted_at"]["mode"] == "columns"
        assert targets["source_roles.primary"]["mode"] == "columns"
        assert targets["smurf_tags"]["mode"] == "columns"


def test_suggest_disabled_targets_present_as_hints():
    mapping = sheet_parsing.suggest_mapping_from_headers(["Random column"])
    # Unmatched targets remain present but disabled (hints, not mappings).
    assert mapping["targets"]["battle_tag"]["mode"] == "disabled"


def test_suggest_mapping_matches_custom_field_label_case_insensitively():
    custom = [CustomFieldDefinition(key="favorite_map", label="Favorite Map", type="text")]
    mapping = sheet_parsing.suggest_mapping_from_headers(["FAVORITE MAP"], custom_fields=custom)
    assert mapping["targets"]["custom_fields.favorite_map"]["mode"] == "columns"


# ---------------------------------------------------------------------------
# Engine: parse_sheet_row writes custom fields & collects errors
# ---------------------------------------------------------------------------


def _grid():
    # Minimal grid stub: division_to_rank isn't exercised by these rows.
    return SimpleNamespace(resolve_rank_from_division=lambda n: None)


def test_division_value_mapping_returns_configured_rank():
    rank = sheet_parsing.parse_target_value(
        parser="division_to_rank",
        values=["Gold 2"],
        value_mapping={"divisions": {"gold 2": 2450}},
        grid=_grid(),
    )
    assert rank == 2450


def test_parse_sheet_row_writes_custom_fields():
    headers = ["BattleTag", "Age", "Region"]
    row = ["Player#1", "25", "EU"]
    mapping = {
        "targets": {
            "battle_tag": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag"},
            "source_record_key": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag"},
            "custom_fields.age": {"mode": "columns", "columns": ["Age"], "parser": "integer"},
            "custom_fields.region": {"mode": "columns", "columns": ["Region"], "parser": "string"},
        }
    }
    custom = [
        CustomFieldDefinition(key="age", label="Age", type="number"),
        CustomFieldDefinition(key="region", label="Region", type="select", options=["EU", "NA"]),
    ]
    result = sheet_parsing.parse_sheet_row_detailed(
        headers=headers,
        row=row,
        mapping_config=mapping,
        value_mapping=None,
        grid=_grid(),
        custom_fields=custom,
    )
    assert result.fields is not None
    assert result.fields["custom_fields"] == {"age": 25, "region": "EU"}


def test_parse_sheet_row_omits_unmapped_custom_fields():
    headers = ["BattleTag", "Age"]
    row = ["Player#1", "25"]
    mapping = {
        "targets": {
            "battle_tag": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag"},
            "custom_fields.age": {"mode": "disabled", "parser": "integer"},
        }
    }
    custom = [CustomFieldDefinition(key="age", label="Age", type="number")]
    result = sheet_parsing.parse_sheet_row_detailed(
        headers=headers,
        row=row,
        mapping_config=mapping,
        value_mapping=None,
        grid=_grid(),
        custom_fields=custom,
    )
    assert result.fields is not None
    assert "custom_fields" not in result.fields or result.fields["custom_fields"] == {}


def test_parse_sheet_row_collects_custom_field_error():
    headers = ["BattleTag", "Age"]
    row = ["Player#1", "not-a-number"]
    mapping = {
        "targets": {
            "battle_tag": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag"},
            "custom_fields.age": {"mode": "columns", "columns": ["Age"], "parser": "integer"},
        }
    }
    custom = [CustomFieldDefinition(key="age", label="Age", type="number")]
    result = sheet_parsing.parse_sheet_row_detailed(
        headers=headers,
        row=row,
        mapping_config=mapping,
        value_mapping=None,
        grid=_grid(),
        custom_fields=custom,
    )
    assert result.fields is not None
    assert any(e["target"] == "custom_fields.age" for e in result.errors)


def test_parse_sheet_row_skip_without_identity_returns_none_fields():
    headers = ["Name"]
    row = ["nobody"]
    mapping = {"targets": {"display_name": {"mode": "columns", "columns": ["Name"], "parser": "string"}}}
    result = sheet_parsing.parse_sheet_row_detailed(
        headers=headers,
        row=row,
        mapping_config=mapping,
        value_mapping=None,
        grid=_grid(),
        custom_fields=[],
    )
    assert result.fields is None


# ---------------------------------------------------------------------------
# New parsers: role_subrole_token and sr_value
# ---------------------------------------------------------------------------


def test_role_subrole_token_custom_hitscan():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["Хитскан ДПС"],
        value_mapping={"role_subroles": {"хитскан дпс": {"role": "damage", "subrole": "hitscan"}}},
        grid=_grid(),
    )
    assert result == {"role": "damage", "subrole": "hitscan"}


def test_role_subrole_token_custom_flex():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["Флекс"],
        value_mapping={"role_subroles": {"флекс": {"role": "flex", "subrole": None}}},
        grid=_grid(),
    )
    assert result == {"role": "flex", "subrole": None}


def test_role_subrole_token_custom_map():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["heal"],
        value_mapping={"role_subroles": {"heal": {"role": "support", "subrole": "main_heal"}}},
        grid=_grid(),
    )
    assert result == {"role": "support", "subrole": "main_heal"}


def test_role_subrole_token_explicit_role_no_subrole():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["tank"],
        value_mapping={"role_subroles": {"tank": {"role": "tank", "subrole": None}}},
        grid=_grid(),
    )
    assert result == {"role": "tank", "subrole": None}


def test_role_subrole_token_no_mapping_returns_none():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["tank"],
        value_mapping={},
        grid=_grid(),
    )
    assert result is None


def test_role_subrole_token_unknown_returns_none():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["unknown_value_xyz"],
        value_mapping={},
        grid=_grid(),
    )
    assert result is None


_SUBROLE_CATALOG = {
    "tank": [],
    "damage": [{"slug": "hitscan", "label": "Hitscan"}],
    "support": [{"slug": "main_heal", "label": "Main Heal"}],
}


def test_map_subrole_token_accepts_catalog_slug_without_value_map():
    assert sheet_parsing.map_subrole_token("hitscan", {}, _SUBROLE_CATALOG) == "hitscan"


def test_map_subrole_token_rejects_unknown_when_catalog():
    assert sheet_parsing.map_subrole_token("burst", {}, _SUBROLE_CATALOG) is None


def test_map_subrole_token_mapped_value_must_be_in_catalog():
    assert sheet_parsing.map_subrole_token("хит", {"subroles": {"хит": "hitscan"}}, _SUBROLE_CATALOG) == "hitscan"
    assert sheet_parsing.map_subrole_token("хит", {"subroles": {"хит": "burst"}}, _SUBROLE_CATALOG) is None


def test_role_subrole_rejects_unknown_subrole_when_catalog():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["heal"],
        value_mapping={"role_subroles": {"heal": {"role": "support", "subrole": "not_a_real"}}},
        grid=_grid(),
        subrole_catalog=_SUBROLE_CATALOG,
    )
    assert result is None


def test_role_subrole_accepts_catalog_subrole():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["heal"],
        value_mapping={"role_subroles": {"heal": {"role": "support", "subrole": "main_heal"}}},
        grid=_grid(),
        subrole_catalog=_SUBROLE_CATALOG,
    )
    assert result == {"role": "support", "subrole": "main_heal"}


def test_validate_value_mapping_unknown_subrole():
    issues = catalog.validate_value_mapping_subroles({"subroles": {"foo": "burst"}}, _SUBROLE_CATALOG)
    assert any(issue.code == "unknown_subrole" for issue in issues)


def test_mapping_catalog_includes_subrole_catalog():
    built = sheet_sync.build_mapping_catalog([], subrole_catalog=_SUBROLE_CATALOG)
    assert built["subrole_catalog"] == _SUBROLE_CATALOG


def test_catalog_slugs_none_skips_enforcement():
    from shared.domain.player_sub_roles import catalog_slugs

    assert catalog_slugs(None) is None
    assert catalog_slugs(_SUBROLE_CATALOG, "damage") == {"hitscan"}
    assert catalog_slugs(_SUBROLE_CATALOG) == {"hitscan", "main_heal"}


def test_sr_value_numeric_string():
    result = sheet_parsing.parse_target_value(
        parser="sr_value",
        values=["2500"],
        value_mapping={},
        grid=_grid(),
    )
    assert result == 2500


def test_sr_value_text_label_from_divisions_map():
    result = sheet_parsing.parse_target_value(
        parser="sr_value",
        values=["Gold 3"],
        value_mapping={"divisions": {"Gold 3": 2800}},
        grid=_grid(),
    )
    assert result == 2800


def test_sr_value_empty_returns_none():
    result = sheet_parsing.parse_target_value(
        parser="sr_value",
        values=[],
        value_mapping={},
        grid=_grid(),
    )
    assert result is None


# ---------------------------------------------------------------------------
# build_registration_role_payloads: priority order and flex detection
# ---------------------------------------------------------------------------


def _make_parsed(primary, additional=None, is_flex=False, roles=None):
    return {
        "source_roles": {"primary": primary, "additional": additional or []},
        "is_flex": is_flex,
        "roles": roles or {},
    }


def test_priority_follows_declaration_order():
    parsed = _make_parsed(
        primary="damage",
        additional=["support"],
        roles={
            "damage": {"rank_value": 2500, "subrole": None, "is_active": True, "priority": None},
            "support": {"rank_value": 2300, "subrole": None, "is_active": True, "priority": None},
        },
    )
    payloads = sheet_parsing.build_registration_role_payloads(parsed)
    by_role = {p["role"]: p for p in payloads}
    assert by_role["damage"]["priority"] == 0
    assert by_role["support"]["priority"] == 1


def test_flex_token_in_primary_sets_is_full_flex():
    parsed = _make_parsed(
        primary={"role": "flex", "subrole": None},
        roles={
            "tank": {"rank_value": 2000, "subrole": None, "is_active": True, "priority": None},
            "damage": {"rank_value": 2200, "subrole": None, "is_active": True, "priority": None},
            "support": {"rank_value": 2100, "subrole": None, "is_active": True, "priority": None},
        },
    )
    payloads = sheet_parsing.build_registration_role_payloads(parsed)
    assert all(p["is_primary"] for p in payloads)


def test_subrole_from_token_propagates_to_payload():
    parsed = _make_parsed(
        primary={"role": "damage", "subrole": "hitscan"},
        roles={"damage": {"rank_value": 2500, "subrole": None, "is_active": True, "priority": None}},
    )
    payloads = sheet_parsing.build_registration_role_payloads(parsed)
    damage_payload = next(p for p in payloads if p["role"] == "damage")
    assert damage_payload["subrole"] == "hitscan"


def test_explicit_subrole_wins_over_token_subrole():
    parsed = _make_parsed(
        primary={"role": "damage", "subrole": "hitscan"},
        roles={"damage": {"rank_value": 2500, "subrole": "projectile", "is_active": True, "priority": None}},
    )
    payloads = sheet_parsing.build_registration_role_payloads(parsed)
    damage_payload = next(p for p in payloads if p["role"] == "damage")
    assert damage_payload["subrole"] == "projectile"


def test_subrole_from_additional_token_propagates_to_payload():
    parsed = _make_parsed(
        primary={"role": "damage", "subrole": "hitscan"},
        additional=[{"role": "support", "subrole": "main_heal"}],
        roles={
            "damage": {"rank_value": 2500, "subrole": None, "is_active": True, "priority": None},
            "support": {"rank_value": 2300, "subrole": None, "is_active": True, "priority": None},
        },
    )
    payloads = sheet_parsing.build_registration_role_payloads(parsed)
    by_role = {p["role"]: p for p in payloads}
    assert by_role["damage"]["subrole"] == "hitscan"
    assert by_role["support"]["subrole"] == "main_heal"


def test_role_subrole_token_accepted_for_primary_and_additional():
    primary_spec = catalog.target_spec_map({})["source_roles.primary"]
    additional_spec = catalog.target_spec_map({})["source_roles.additional"]
    assert catalog.PARSER_ROLE_SUBROLE_TOKEN in primary_spec.accepted_parsers
    assert catalog.PARSER_ROLE_SUBROLE_TOKEN in additional_spec.accepted_parsers


def test_sr_value_accepted_for_all_rank_value_targets():
    specs = catalog.target_spec_map({})
    for role_code in ("tank", "damage", "support"):
        spec = specs[f"roles.{role_code}.rank_value"]
        assert catalog.PARSER_SR_VALUE in spec.accepted_parsers


# ---------------------------------------------------------------------------
# is_list flag: role_token and role_subrole_token list mode
# ---------------------------------------------------------------------------


_ROLE_MAP = {"roles": {"damage": "damage", "support": "support", "tank": "tank"}}


def test_role_token_is_list_multiple_values():
    result = sheet_parsing.parse_target_value(
        parser="role_token",
        values=["damage", "support"],
        value_mapping=_ROLE_MAP,
        grid=_grid(),
        is_list=True,
    )
    assert result == ["damage", "support"]


def test_role_token_is_list_splits_comma_separated():
    result = sheet_parsing.parse_target_value(
        parser="role_token",
        values=["tank,damage"],
        value_mapping=_ROLE_MAP,
        grid=_grid(),
        is_list=True,
    )
    assert result == ["tank", "damage"]


def test_role_token_is_list_skips_empty_values():
    result = sheet_parsing.parse_target_value(
        parser="role_token",
        values=["", "support", ""],
        value_mapping=_ROLE_MAP,
        grid=_grid(),
        is_list=True,
    )
    assert result == ["support"]


_ROLE_SUBROLE_MAP = {
    "role_subroles": {
        "хитскан дпс": {"role": "damage", "subrole": "hitscan"},
        "мейн хил": {"role": "support", "subrole": "main_heal"},
        "лайт хил (мерси, кирико)": {"role": "support", "subrole": "light_heal"},
        "проджектайл дд (генджи, фара, ханзо, торбьерн, джанкрет, эхо, мей, рипер, сомбра, симметра, трейсер)": {
            "role": "damage",
            "subrole": "projectile",
        },
        "хитскан дд (маккри, вдова, солдат76, эш)": {"role": "damage", "subrole": "hitscan"},
        "support": {"role": "support", "subrole": None},
        "damage": {"role": "damage", "subrole": None},
    }
}


def test_role_subrole_token_is_list_multiple_columns():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["Хитскан ДПС", "Мейн хил"],
        value_mapping=_ROLE_SUBROLE_MAP,
        grid=_grid(),
        is_list=True,
    )
    assert result == [{"role": "damage", "subrole": "hitscan"}, {"role": "support", "subrole": "main_heal"}]


def test_role_subrole_token_verbose_google_forms_label():
    # Google Forms option label with hero list in parentheses — each cell is one
    # complete token matched exactly against the configured value_mapping.
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["Проджектайл ДД (Генджи, Фара, Ханзо, Торбьерн, Джанкрет, Эхо, Мей, Рипер, Сомбра, Симметра, Трейсер)"],
        value_mapping=_ROLE_SUBROLE_MAP,
        grid=_grid(),
        is_list=True,
    )
    assert result == [{"role": "damage", "subrole": "projectile"}]


def test_role_subrole_token_verbose_hitscan_label():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["Хитскан ДД (Маккри, Вдова, Солдат76, Эш)"],
        value_mapping=_ROLE_SUBROLE_MAP,
        grid=_grid(),
        is_list=True,
    )
    assert result == [{"role": "damage", "subrole": "hitscan"}]


def test_role_subrole_token_verbose_light_heal_label():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["Лайт хил (Мерси, Кирико)"],
        value_mapping=_ROLE_SUBROLE_MAP,
        grid=_grid(),
        is_list=True,
    )
    assert result == [{"role": "support", "subrole": "light_heal"}]


def test_role_subrole_token_is_list_first_column_empty():
    # Simulates 3 mapped columns where column 1 is empty — get_selector_values already
    # filters empty cells, so parse_target_value receives only the non-empty values.
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["support"],
        value_mapping=_ROLE_SUBROLE_MAP,
        grid=_grid(),
        is_list=True,
    )
    assert result == [{"role": "support", "subrole": None}]


def test_role_subrole_token_is_list_deduplicates_by_role():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["damage", "damage"],
        value_mapping=_ROLE_SUBROLE_MAP,
        grid=_grid(),
        is_list=True,
    )
    assert result == [{"role": "damage", "subrole": None}]


def test_role_subrole_token_no_is_list_unchanged():
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["Хитскан ДПС"],
        value_mapping=_ROLE_SUBROLE_MAP,
        grid=_grid(),
    )
    assert result == {"role": "damage", "subrole": "hitscan"}


def test_role_subrole_token_multi_role_mapping_expands():
    # A single cell value that maps to a list — e.g. "Флекс, Танк или Сап"
    # expands into two role entries without splitting on commas.
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["Флекс, Танк или Сап"],
        value_mapping={
            "role_subroles": {
                "флекс, танк или сап": [
                    {"role": "tank", "subrole": None},
                    {"role": "support", "subrole": None},
                ]
            }
        },
        grid=_grid(),
        is_list=True,
    )
    assert result == [{"role": "tank", "subrole": None}, {"role": "support", "subrole": None}]


def test_role_subrole_token_multi_role_deduplicates_across_columns():
    # Multi-role from one cell + explicit tank from another column — tank deduped.
    result = sheet_parsing.parse_target_value(
        parser="role_subrole_token",
        values=["Флекс, Танк или Сап", "Танк"],
        value_mapping={
            "role_subroles": {
                "флекс, танк или сап": [
                    {"role": "tank", "subrole": None},
                    {"role": "support", "subrole": None},
                ],
                "танк": {"role": "tank", "subrole": None},
            }
        },
        grid=_grid(),
        is_list=True,
    )
    assert result == [{"role": "tank", "subrole": None}, {"role": "support", "subrole": None}]


def test_additional_roles_spec_has_default_is_list():
    spec = catalog.target_spec_map({})["source_roles.additional"]
    assert spec.default_is_list is True


def test_role_token_list_with_explicit_mapping():
    result = sheet_parsing.parse_target_value(
        parser="role_token_list",
        values=["damage", "support"],
        value_mapping=_ROLE_MAP,
        grid=_grid(),
    )
    assert result == ["damage", "support"]
