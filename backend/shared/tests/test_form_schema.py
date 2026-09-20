"""Registration form schema: invariants, builtin catalog and default form."""

import pytest
from pydantic import ValidationError

from shared.domain.forms import FormField, FormSchema, FormSection, default_schema
from shared.domain.forms.builtins import (
    IDENTITY_PROVIDERS,
    RolesParams,
    builtin_spec,
    identity_key,
    identity_provider,
)


def _schema(*fields: FormField, section_key: str = "main") -> FormSchema:
    return FormSchema(sections=[FormSection(key=section_key, fields=list(fields))])


def test_duplicate_field_keys_are_rejected():
    with pytest.raises(ValidationError, match="duplicate field key"):
        _schema(FormField(key="vk", kind="text", label="VK"), FormField(key="vk", kind="url", label="VK2"))


def test_custom_key_may_not_shadow_a_builtin_or_identity_prefix():
    with pytest.raises(ValidationError, match="reserved"):
        _schema(FormField(key="battle_tag", kind="text", label="x"))
    with pytest.raises(ValidationError, match="reserved"):
        _schema(FormField(key="identity_telegram", kind="text", label="x"))


def test_builtin_visibility_is_fixed_by_the_catalog():
    with pytest.raises(ValidationError, match="visibility"):
        _schema(FormField(key="battle_tag", kind="builtin", visibility="organizers"))
    with pytest.raises(ValidationError, match="visibility"):
        _schema(FormField(key="organizer_notes", kind="builtin", visibility="public"))


def test_visible_when_must_point_at_an_earlier_field():
    later = FormField(key="twitch_only", kind="text", label="x", visible_when={"field": "stream_pov", "op": "truthy"})
    with pytest.raises(ValidationError, match="earlier"):
        _schema(later, FormField(key="stream_pov", kind="builtin"))
    ok = _schema(FormField(key="stream_pov", kind="builtin"), later)
    assert ok.field("twitch_only").visible_when.field == "stream_pov"


def test_show_in_draft_requires_public_visibility_and_custom_kind():
    with pytest.raises(ValidationError, match="show_in_draft"):
        _schema(FormField(key="phone", kind="text", label="Phone", visibility="organizers", show_in_draft=True))
    with pytest.raises(ValidationError, match="show_in_draft"):
        _schema(FormField(key="public_notes", kind="builtin", show_in_draft=True))


def test_select_needs_unique_non_empty_options_and_other_kinds_none():
    with pytest.raises(ValidationError, match="options"):
        _schema(FormField(key="age", kind="select", label="Age", options=[]))
    with pytest.raises(ValidationError, match="options"):
        _schema(FormField(key="age", kind="select", label="Age", options=["a", "a"]))
    with pytest.raises(ValidationError, match="options"):
        _schema(FormField(key="age", kind="number", label="Age", options=["a"]))


def test_roles_params_validate_against_the_catalog_model():
    with pytest.raises(ValidationError, match="flex_mode"):
        _schema(FormField(key="roles", kind="builtin", params={"flex_mode": "sometimes"}))


def test_public_keys_and_canonical_json_are_order_independent_for_dedupe():
    a = _schema(
        FormField(key="battle_tag", kind="builtin"),
        FormField(key="phone", kind="text", label="P", visibility="organizers"),
    )
    b = FormSchema.model_validate(a.model_dump())
    assert a.public_keys() == frozenset({"battle_tag"})
    assert a.canonical_json() == b.canonical_json()


def test_default_schema_matches_todays_default_form():
    keys = [f.key for f in default_schema().fields()]
    assert keys == ["battle_tag", "smurf_tags", "identity_discord", "identity_twitch", "roles", "public_notes"]
    assert [s.key for s in default_schema().sections] == ["accounts", "roles", "details"]


def test_identity_keys_round_trip_for_every_non_battlenet_provider():
    assert "battlenet" not in IDENTITY_PROVIDERS
    for provider in IDENTITY_PROVIDERS:
        assert identity_provider(identity_key(provider)) == provider
        assert builtin_spec(identity_key(provider)).fixed_visibility is None
    assert identity_provider("identity_nope") is None and builtin_spec("identity_nope") is None


def test_roles_params_defaults_reproduce_todays_optional_mode():
    p = RolesParams()
    assert (p.primary_required, p.additional_required, p.flex_mode, p.top_heroes.enabled, p.top_heroes.max) == (
        True,
        False,
        "optional",
        False,
        5,
    )


def test_section_keys_must_be_valid_and_unique():
    with pytest.raises(ValidationError, match="invalid section key"):
        _schema(section_key="Main")
    with pytest.raises(ValidationError, match="duplicate section key"):
        FormSchema(sections=[FormSection(key="main"), FormSection(key="main")])


def test_field_keys_must_match_the_key_pattern():
    with pytest.raises(ValidationError, match="invalid field key"):
        _schema(FormField(key="Phone", kind="text", label="P"))


def test_builtin_key_must_exist_and_builtins_take_no_options_or_params():
    with pytest.raises(ValidationError, match="unknown builtin"):
        _schema(FormField(key="nope", kind="builtin"))
    with pytest.raises(ValidationError, match="options"):
        _schema(FormField(key="battle_tag", kind="builtin", options=["a"]))
    with pytest.raises(ValidationError, match="takes no params"):
        _schema(FormField(key="public_notes", kind="builtin", params={"x": 1}))


def test_custom_fields_need_a_label_and_take_no_params():
    with pytest.raises(ValidationError, match="needs a label"):
        _schema(FormField(key="phone", kind="text"))
    with pytest.raises(ValidationError, match="custom fields take no params"):
        _schema(FormField(key="phone", kind="text", label="P", params={"x": 1}))


def test_visible_when_may_not_reference_itself():
    with pytest.raises(ValidationError, match="earlier"):
        _schema(FormField(key="phone", kind="text", label="P", visible_when={"field": "phone", "op": "truthy"}))
