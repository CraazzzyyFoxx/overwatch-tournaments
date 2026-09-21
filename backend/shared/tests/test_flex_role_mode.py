"""``flex_role_mode``: the one reader of the ``roles`` builtin's flex params.

Twenty-seven call sites -- the balancer input, the draft pool, feasibility,
autopick, the write-path normalizer -- route through this function, and every
one of them fails SILENTLY when it answers wrong: an ``all_roles`` tournament
simply stops backfilling roles, and nobody sees an error. When the form's
``built_in_fields_json`` column was dropped, the old ``getattr(form, ...,
None)`` default made this return ``"optional"`` for every tournament in the
system with nothing in the suite to notice. Hence these tests.
"""

from types import SimpleNamespace

from shared.domain.forms import FormField, FormSchema, FormSection, default_schema
from shared.domain.roster import flex_role_mode


def _form(**roles_params) -> SimpleNamespace:
    schema = FormSchema(
        sections=[FormSection(key="roles", fields=[FormField(key="roles", kind="builtin", params=roles_params)])]
    )
    return SimpleNamespace(current_version=SimpleNamespace(schema_json=schema.model_dump(mode="json")))


def test_forced_resolves_to_forced():
    assert flex_role_mode(_form(flex_mode="forced")) == "forced"


def test_all_roles_resolves_to_all_roles():
    assert flex_role_mode(_form(flex_mode="all_roles")) == "all_roles"


def test_the_default_form_is_optional():
    """``default_schema()`` asks the ``roles`` builtin with no params at all, so the
    catalog defaults decide -- and the catalog default must stay ``optional``."""
    form = SimpleNamespace(current_version=SimpleNamespace(schema_json=default_schema().model_dump(mode="json")))
    assert flex_role_mode(form) == "optional"


def test_a_banned_flex_field_beats_a_mode_left_behind():
    """A form cannot force every role playable through a field it does not show."""
    assert flex_role_mode(_form(flex_allowed=False, flex_mode="forced")) == "optional"


def test_a_form_without_a_roles_question_is_optional():
    schema = FormSchema(sections=[FormSection(key="details", fields=[FormField(key="public_notes", kind="builtin")])])
    form = SimpleNamespace(current_version=SimpleNamespace(schema_json=schema.model_dump(mode="json")))
    assert flex_role_mode(form) == "optional"


def test_no_form_and_an_unconfigured_form_are_optional():
    assert flex_role_mode(None) == "optional"
    assert flex_role_mode(SimpleNamespace(current_version=None)) == "optional"
