"""Golden test for the pure converters inside the ``regform01_form_schema`` revision.

The migration must not import ``shared`` (migrations run against a database whose
models may predate the code), so its converter is defined inline and this test
loads the revision module **by path**. The last two tests close the loop the
migration itself cannot: they feed the converter's output through the real
``FormSchema`` validator, which is the only proof that the rows the migration
writes are readable by the application afterwards.
"""

from __future__ import annotations

import importlib.util
import pathlib

from shared.domain.forms.schema import FormSchema

_PATH = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions" / "regform01_form_schema.py"
spec = importlib.util.spec_from_file_location("regform01", _PATH)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

LEGACY_DEFAULT_BUILTINS = {
    "battle_tag": {"enabled": True, "required": True, "validation": {"regex": "([^#]{2,12}#[0-9]{4,})"}},
    "smurf_tags": {"enabled": True, "required": False},
    "discord_nick": {"enabled": True, "required": False, "require_verified": True},
    "twitch_nick": {"enabled": True, "required": False},
    "boosty_nick": {"enabled": False, "required": False},
    "primary_role": {"enabled": True, "required": True, "subroles": {"tank": ["main_tank"]}},
    "additional_roles": {"enabled": True, "required": True},
    "flex_role": {"enabled": True, "mode": "all_roles"},
    "top_heroes": {"enabled": True, "required": False, "max_heroes": 3},
    "stream_pov": {"enabled": True, "required": False},
    "notes": {"enabled": True, "required": False},
}
LEGACY_CUSTOM = [
    {
        "key": "vk",
        "label": "VK",
        "type": "url",
        "required": False,
        "placeholder": None,
        "options": None,
        "validation": None,
        "show_in_draft": True,
    },
    {"key": "age", "label": "Age", "type": "number", "required": True},
]

#: Every legacy builtin toggled on, with sub-roles on both role fields (they are
#: unioned into one ``roles.params.subroles``) and a *broken* regex on ``notes``:
#: ``FormSchema`` refuses a pattern that will not compile, so the converter has to
#: drop it rather than carry it into version #1.
LEGACY_EVERY_TOGGLE = {
    "battle_tag": {
        "enabled": True,
        "required": True,
        "require_verified": True,
        "validation": {"regex": "([^#]{2,12}#[0-9]{4,})", "error_message": "BattleTag must match Player#1234."},
    },
    "smurf_tags": {"enabled": True, "required": True, "validation": {"regex": "([^#]{2,12}#[0-9]{4,})"}},
    "discord_nick": {"enabled": True, "required": True, "require_verified": True},
    "twitch_nick": {"enabled": True, "required": True, "require_verified": True},
    "boosty_nick": {"enabled": True, "required": True},
    "primary_role": {"enabled": True, "required": True, "subroles": {"tank": ["main_tank"], "damage": ["hitscan"]}},
    "additional_roles": {"enabled": True, "required": True, "subroles": {"damage": ["projectile"]}},
    "flex_role": {"enabled": True, "mode": "forced"},
    "top_heroes": {"enabled": True, "required": True, "max_heroes": 7},
    "stream_pov": {"enabled": True, "required": False},
    "notes": {"enabled": True, "required": False, "validation": {"regex": "(((", "error_message": "broken"}},
}
LEGACY_EVERY_CUSTOM = [
    {"key": "vk", "label": "VK", "type": "url", "required": True, "show_in_draft": True},
    {"key": "age", "label": "Age", "type": "number", "required": True},
    {"key": "region", "label": "Region", "type": "select", "options": ["EU", "NA"], "required": False},
    {"key": "agrees", "label": "Agrees", "type": "checkbox", "required": True},
    {"key": "about", "label": "About", "type": "text", "placeholder": "A few words", "required": False},
]


def test_default_form_converts_to_three_sections_in_todays_order():
    schema = mod.legacy_to_schema(LEGACY_DEFAULT_BUILTINS, LEGACY_CUSTOM)
    assert [s["key"] for s in schema["sections"]] == ["accounts", "roles", "details"]
    assert [f["key"] for f in schema["sections"][0]["fields"]] == [
        "battle_tag",
        "smurf_tags",
        "identity_discord",
        "identity_twitch",
    ]
    roles = schema["sections"][1]["fields"][0]
    assert roles["params"] == {
        "primary_required": True,
        "additional_required": True,
        "flex_allowed": True,
        "flex_mode": "all_roles",
        "subroles": {"tank": ["main_tank"]},
        "top_heroes": {"enabled": True, "required": False, "max": 3},
    }
    assert [f["key"] for f in schema["sections"][2]["fields"]] == ["stream_pov", "public_notes", "vk", "age"]
    discord = schema["sections"][0]["fields"][2]
    assert discord["kind"] == "builtin" and discord["params"] == {"require_verified": True}
    assert discord["visibility"] == "public"
    assert schema["sections"][2]["fields"][2] == {
        "key": "vk",
        "kind": "url",
        "label": "VK",
        "required": False,
        "visibility": "public",
        "show_in_draft": True,
    }


def test_disabled_builtins_and_absent_keys_are_omitted_and_empty_config_yields_the_default():
    # An absent ``boosty_nick`` is ENABLED: the pre-migration wizard read every
    # account field as ``?.enabled !== false``, so a form saved with an empty
    # config still showed the Boosty input, and the conversion must keep it.
    assert [f["key"] for f in mod.legacy_to_schema({}, [])["sections"][0]["fields"]] == [
        "battle_tag",
        "smurf_tags",
        "identity_discord",
        "identity_twitch",
        "identity_boosty",
    ]
    only_tag = mod.legacy_to_schema(
        {k: {"enabled": False} for k in LEGACY_DEFAULT_BUILTINS if k != "battle_tag"}
        | {"battle_tag": {"enabled": True}},
        [],
    )
    assert [f["key"] for s in only_tag["sections"] for f in s["fields"]] == ["battle_tag"]


def test_a_form_with_every_field_off_still_has_one_section():
    """``FormSchema.sections`` has ``min_length=1``: an all-off form must still
    produce a readable (empty) schema rather than an unloadable version row."""
    nothing = mod.legacy_to_schema({k: {"enabled": False} for k in LEGACY_DEFAULT_BUILTINS}, [])
    assert nothing["sections"] == [{"key": "accounts", "fields": []}]
    assert FormSchema.model_validate(nothing).fields() == []


def test_nicks_and_sheet_targets_are_remapped():
    assert mod.legacy_nicks({"discord_nick": " Ferz ", "twitch_nick": None, "boosty_nick": "B"}) == [
        ("discord", "Ferz", "ferz"),
        ("boosty", "B", "b"),
    ]
    # Real shape of ``registration_google_sheet_feed.mapping_config_json``:
    # ``{"targets": {<target key>: {"mode", "columns"|"value", "parser"}}}``.
    mapping = {
        "targets": {
            "battle_tag": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag"},
            "discord_nick": {"mode": "columns", "columns": ["Discord"], "parser": "string"},
            "twitch_nick": {"mode": "columns", "columns": ["Twitch"], "parser": "string"},
            "boosty_nick": {"mode": "disabled", "parser": "string"},
            "notes": {"mode": "columns", "columns": ["Notes"], "parser": "join_lines"},
            "admin_notes": {"mode": "columns", "columns": ["Admin"], "parser": "join_lines"},
            "custom_fields.age": {"mode": "columns", "columns": ["Age"], "parser": "integer"},
        }
    }
    remapped = mod.remap_sheet_targets(mapping)
    assert list(remapped["targets"]) == [
        "battle_tag",
        "identity_discord",
        "identity_twitch",
        "identity_boosty",
        "public_notes",
        "admin_notes",
        "custom_fields.age",
    ]
    assert remapped["targets"]["identity_discord"] == {"mode": "columns", "columns": ["Discord"], "parser": "string"}
    # ``admin_notes`` is an organizer column, not a form field: it must survive untouched.
    assert remapped["targets"]["admin_notes"] == mapping["targets"]["admin_notes"]
    assert mod.remap_sheet_targets(None) is None
    assert mod.unmap_sheet_targets(remapped) == mapping


def test_converted_default_form_is_a_schema_the_application_can_read():
    schema = FormSchema.model_validate(mod.legacy_to_schema(LEGACY_DEFAULT_BUILTINS, LEGACY_CUSTOM))
    assert [f.key for f in schema.fields()] == [
        "battle_tag",
        "smurf_tags",
        "identity_discord",
        "identity_twitch",
        "roles",
        "stream_pov",
        "public_notes",
        "vk",
        "age",
    ]
    assert schema.builtin("roles").params["flex_mode"] == "all_roles"
    assert schema.public_keys() == frozenset(f.key for f in schema.fields())


def test_converted_every_toggle_form_validates_and_drops_an_uncompilable_regex():
    raw = mod.legacy_to_schema(LEGACY_EVERY_TOGGLE, LEGACY_EVERY_CUSTOM)
    schema = FormSchema.model_validate(raw)
    assert [f.key for f in schema.fields()] == [
        "battle_tag",
        "smurf_tags",
        "identity_discord",
        "identity_twitch",
        "identity_boosty",
        "roles",
        "stream_pov",
        "public_notes",
        "vk",
        "age",
        "region",
        "agrees",
        "about",
    ]
    assert schema.builtin("roles").params["subroles"] == {"tank": ["main_tank"], "damage": ["hitscan", "projectile"]}
    assert schema.builtin("roles").params["top_heroes"] == {"enabled": True, "required": True, "max": 7}
    notes = schema.field("public_notes")
    assert notes.validation is not None and notes.validation.regex is None
    assert notes.validation.error_message == "broken"
    assert schema.field("region").options == ["EU", "NA"]


def test_a_regex_too_long_to_compile_safely_is_dropped():
    long_pattern = "a" * 257
    raw = mod.legacy_to_schema({"battle_tag": {"enabled": True, "validation": {"regex": long_pattern}}}, [])
    FormSchema.model_validate(raw)
    assert "validation" not in raw["sections"][0]["fields"][0]
