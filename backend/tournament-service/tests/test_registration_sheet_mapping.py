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
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

catalog = importlib.import_module("src.services.registration.mapping_catalog")
schemas = importlib.import_module("src.schemas.registration")
admin = importlib.import_module("src.services.registration.admin")

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
    "roles.dps.rank_value",
    "roles.dps.division_input",
    "roles.dps.subrole",
    "roles.dps.is_active",
    "roles.dps.priority",
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
    assert set(admin.DEFAULT_MAPPING_TARGETS) == LEGACY_BUILTIN_TARGETS


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
    built = admin.build_mapping_catalog([])
    assert {category["category"] for category in built["value_categories"]} == {
        "booleans",
        "roles",
        "subroles",
        "divisions",
    }


def test_mapping_catalog_merges_saved_value_maps_with_defaults():
    built = admin.build_mapping_catalog([], value_mapping={"roles": {"healer": "support"}})
    categories = {category["category"]: category["entries"] for category in built["value_categories"]}
    assert categories["roles"]["healer"] == "support"
    assert categories["roles"]["tank"] == "tank"


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
    result = catalog.coerce_custom_field_value(
        field_def, "oui", value_mapping={"booleans": {"oui": True}}
    )
    assert result.value is True
    overridden = catalog.coerce_custom_field_value(
        field_def, "yes", value_mapping={"booleans": {"yes": False}}
    )
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
    assert catalog.classify_row_disposition(None, None, known_source_keys=known_keys, known_battle_tag_keys=known_tags) == "skip"
    assert catalog.classify_row_disposition("abc#1", None, known_source_keys=known_keys, known_battle_tag_keys=known_tags) == "update"
    assert catalog.classify_row_disposition("new#9", "def#2", known_source_keys=known_keys, known_battle_tag_keys=known_tags) == "update"
    assert catalog.classify_row_disposition("new#9", "zzz#3", known_source_keys=known_keys, known_battle_tag_keys=known_tags) == "create"


# ---------------------------------------------------------------------------
# Engine: suggestions are language-agnostic
# ---------------------------------------------------------------------------


def test_suggest_mapping_matches_english_and_russian_headers():
    russian = ["Отметка времени", "Ваш Battle Tag", "Укажите вашу роль", "Смурф аккаунты"]
    english = ["Timestamp", "Your Battle Tag", "Your role", "Smurf accounts"]
    for headers in (russian, english):
        mapping = admin.suggest_mapping_from_headers(headers)
        targets = mapping["targets"]
        assert targets["battle_tag"]["mode"] == "columns"
        assert targets["submitted_at"]["mode"] == "columns"
        assert targets["source_roles.primary"]["mode"] == "columns"
        assert targets["smurf_tags"]["mode"] == "columns"


def test_suggest_disabled_targets_present_as_hints():
    mapping = admin.suggest_mapping_from_headers(["Random column"])
    # Unmatched targets remain present but disabled (hints, not mappings).
    assert mapping["targets"]["battle_tag"]["mode"] == "disabled"


def test_suggest_mapping_matches_custom_field_label_case_insensitively():
    custom = [CustomFieldDefinition(key="favorite_map", label="Favorite Map", type="text")]
    mapping = admin.suggest_mapping_from_headers(["FAVORITE MAP"], custom_fields=custom)
    assert mapping["targets"]["custom_fields.favorite_map"]["mode"] == "columns"


# ---------------------------------------------------------------------------
# Engine: parse_sheet_row writes custom fields & collects errors
# ---------------------------------------------------------------------------


def _grid():
    # Minimal grid stub: division_to_rank isn't exercised by these rows.
    return SimpleNamespace(resolve_rank_from_division=lambda n: None)


def test_division_value_mapping_returns_configured_rank():
    rank = admin.parse_target_value(
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
    result = admin.parse_sheet_row_detailed(
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
    result = admin.parse_sheet_row_detailed(
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
    result = admin.parse_sheet_row_detailed(
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
    result = admin.parse_sheet_row_detailed(
        headers=headers,
        row=row,
        mapping_config=mapping,
        value_mapping=None,
        grid=_grid(),
        custom_fields=[],
    )
    assert result.fields is None
