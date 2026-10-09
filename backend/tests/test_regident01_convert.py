"""Golden test for the pure converters inside the ``regident01`` revision.

Loaded by path, like ``test_regform01_convert.py``: the migration may not import
``shared``, so the only proof its rewritten documents stay readable is feeding
them through the real ``FormSchema`` validator from here.
"""

from __future__ import annotations

import importlib.util
import pathlib

from shared.domain.forms.schema import FormSchema

_PATH = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions" / "regident01_identity_positions.py"
spec = importlib.util.spec_from_file_location("regident01", _PATH)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _schema(*fields: dict) -> dict:
    return {"schema_version": 1, "sections": [{"key": "accounts", "fields": list(fields)}]}


def test_battle_tag_and_smurfs_become_one_identity_field():
    raw = _schema(
        {
            "key": "battle_tag",
            "kind": "builtin",
            "label": "BattleTag",
            "required": True,
            "editable": True,
            "visibility": "public",
            "validation": {"regex": "([^#]{2,12}#[0-9]{4,})"},
            "params": {"require_verified": True},
        },
        {"key": "smurf_tags", "kind": "builtin", "required": False, "visibility": "public"},
        # Boosty cannot be verified any more: the dead flag goes, the field stays.
        {"key": "identity_boosty", "kind": "builtin", "params": {"require_verified": True}},
        {
            "key": "note",
            "kind": "text",
            "label": "Note",
            "visible_when": {"field": "smurf_tags", "op": "truthy"},
        },
    )
    converted = mod.convert_schema(raw)
    schema = FormSchema.model_validate(converted)

    assert [f.key for f in schema.fields()] == ["identity_battlenet", "identity_boosty", "note"]
    battlenet = schema.builtin("identity_battlenet")
    # ``max_count`` 5 because the form ASKED for smurfs; everything else carried.
    assert battlenet.params == {"require_verified": True, "max_count": 5}
    assert (battlenet.label, battlenet.required, battlenet.editable) == ("BattleTag", True, True)
    assert battlenet.validation.regex == "([^#]{2,12}#[0-9]{4,})"
    assert schema.builtin("identity_boosty").params == {}
    assert schema.field("note").visible_when.field == "identity_battlenet"

    # Without a smurf question one handle is all the form ever asked for.
    single = mod.convert_schema(_schema({"key": "battle_tag", "kind": "builtin", "required": True}))
    assert FormSchema.model_validate(single).builtin("identity_battlenet").params == {
        "require_verified": False,
        "max_count": 1,
    }

    # Down again: the list field splits back into the two legacy questions.
    restored = mod.restore_schema(converted)
    assert [f["key"] for f in restored["sections"][0]["fields"]] == [
        "battle_tag",
        "smurf_tags",
        "identity_boosty",
        "note",
    ]
    assert restored["sections"][0]["fields"][3]["visible_when"]["field"] == "battle_tag"


def test_sheet_targets_merge_and_keep_the_dedup_key_on_its_column():
    mapping = {
        "targets": {
            "battle_tag": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag"},
            "smurf_tags": {"mode": "columns", "columns": ["Smurf1", "Smurf2"], "parser": "battle_tag_list"},
            "admin_notes": {"mode": "columns", "columns": ["Admin"], "parser": "join_lines"},
        }
    }
    converted = mod.convert_mapping(mapping)
    assert converted["targets"]["identity_battlenet"] == {
        "mode": "columns",
        "columns": ["BattleTag", "Smurf1", "Smurf2"],
        "parser": "battle_tag_list",
    }
    assert "smurf_tags" not in converted["targets"]
    assert converted["targets"]["admin_notes"] == mapping["targets"]["admin_notes"]
    # No explicit dedup target: the implicit "key off the battle_tag value" rule
    # dies with the target, so the same column is pinned to it instead.
    assert converted["targets"]["source_record_key"] == {
        "mode": "columns",
        "columns": ["BattleTag"],
        "parser": "battle_tag",
    }
    assert mod.convert_mapping(None) is None

    restored = mod.restore_mapping(converted)
    assert restored["targets"]["battle_tag"] == mapping["targets"]["battle_tag"]
    assert restored["targets"]["smurf_tags"] == {
        "mode": "columns",
        "columns": ["Smurf1", "Smurf2"],
        "parser": "battle_tag_list",
    }


def test_handles_are_normalized_deduplicated_and_capped():
    assert mod.battlenet_handles(" Ferz # 2155 ", ["FERZ#2155", "", None, "Smurf #1", "Smurf#2"]) == [
        ("Ferz#2155", "ferz#2155"),
        ("Smurf#1", "smurf#1"),
        ("Smurf#2", "smurf#2"),
    ]
    assert mod.battlenet_handles("Main#1", [f"S{n}#1111" for n in range(20)])[-1] == ("S8#1111", "s8#1111")
    assert len(mod.battlenet_handles("Main#1", [f"S{n}#1111" for n in range(20)])) == 10
    assert mod.battlenet_handles("   ", None) == []
