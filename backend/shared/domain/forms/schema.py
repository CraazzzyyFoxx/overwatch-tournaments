"""Registration form schema: sections of ordered fields. Pure model, no I/O.

One schema replaces ``built_in_fields_json`` (a dict of hard-coded keys) and
``custom_fields_json`` (a list of loosely typed definitions). Builtins keep
their own storage (columns, ``registration_role``, ``registration_identity``);
the schema only decides presence, order, rules and visibility.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from shared.core.social import InvalidHandlePattern, compile_handle_pattern
from shared.domain.forms.builtins import IDENTITY_KEY_PREFIX, builtin_spec, is_builtin_key

__all__ = (
    "KEY_PATTERN",
    "OPTION_KINDS",
    "Condition",
    "ConditionOp",
    "FieldKind",
    "FieldValidation",
    "FormField",
    "FormSchema",
    "FormSection",
    "Visibility",
    "default_schema",
    "schema_from_form",
)

FieldKind = Literal["builtin", "text", "textarea", "number", "select", "multi_select", "checkbox", "url", "date"]
Visibility = Literal["public", "organizers"]
ConditionOp = Literal["eq", "neq", "in", "truthy"]
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
OPTION_KINDS = frozenset({"select", "multi_select"})


class FieldValidation(BaseModel):
    regex: str | None = None
    error_message: str | None = None


class Condition(BaseModel):
    field: str
    op: ConditionOp
    value: Any = None


class FormField(BaseModel):
    key: str
    kind: FieldKind
    label: str | None = None
    help: str | None = None
    placeholder: str | None = None
    required: bool = False
    visibility: Visibility = "public"
    options: list[str] | None = None
    validation: FieldValidation | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    show_in_draft: bool = False
    visible_when: Condition | None = None

    @property
    def is_builtin(self) -> bool:
        return self.kind == "builtin"


class FormSection(BaseModel):
    key: str
    title: str | None = None
    description: str | None = None
    fields: list[FormField] = Field(default_factory=list)


class FormSchema(BaseModel):
    schema_version: Literal[1] = 1
    sections: list[FormSection] = Field(min_length=1)

    @model_validator(mode="after")
    def _invariants(self) -> FormSchema:
        seen_sections: set[str] = set()
        seen_fields: dict[str, int] = {}
        order = 0
        for si, section in enumerate(self.sections):
            if not KEY_PATTERN.fullmatch(section.key):
                raise ValueError(f"sections[{si}].key: invalid section key {section.key!r}")
            if section.key in seen_sections:
                raise ValueError(f"sections[{si}].key: duplicate section key {section.key!r}")
            seen_sections.add(section.key)
            for fi, field in enumerate(section.fields):
                path = f"sections[{si}].fields[{fi}]"
                if not KEY_PATTERN.fullmatch(field.key):
                    raise ValueError(f"{path}.key: invalid field key {field.key!r}")
                if field.key in seen_fields:
                    raise ValueError(f"{path}.key: duplicate field key {field.key!r}")
                if field.is_builtin:
                    spec = builtin_spec(field.key)
                    if spec is None:
                        raise ValueError(f"{path}.key: unknown builtin {field.key!r}")
                    if spec.params_model is not None:
                        try:
                            spec.params_model.model_validate(field.params)
                        except ValidationError as exc:
                            first = exc.errors()[0]
                            loc = ".".join(str(part) for part in first["loc"])
                            raise ValueError(f"{path}.params.{loc}: {first['msg']}") from exc
                    elif field.params:
                        raise ValueError(f"{path}.params: {field.key!r} takes no params")
                    if spec.fixed_visibility is not None and field.visibility != spec.fixed_visibility:
                        raise ValueError(f"{path}.visibility: {field.key!r} is always {spec.fixed_visibility}")
                    if field.options is not None:
                        raise ValueError(f"{path}.options: builtins take no options")
                    if field.show_in_draft:
                        raise ValueError(f"{path}.show_in_draft: only custom fields may opt into the draft")
                else:
                    if is_builtin_key(field.key) or field.key.startswith(IDENTITY_KEY_PREFIX):
                        raise ValueError(f"{path}.key: {field.key!r} is reserved for a builtin")
                    if not (field.label or "").strip():
                        raise ValueError(f"{path}.label: custom field needs a label")
                    if field.params:
                        raise ValueError(f"{path}.params: custom fields take no params")
                    if field.kind in OPTION_KINDS:
                        if not field.options or len(set(field.options)) != len(field.options):
                            raise ValueError(f"{path}.options: non-empty unique options required")
                    elif field.options is not None:
                        raise ValueError(f"{path}.options: only select/multi_select take options")
                if field.show_in_draft and field.visibility != "public":
                    raise ValueError(f"{path}.show_in_draft: requires public visibility")
                if field.visible_when is not None:
                    target = field.visible_when.field
                    if target == field.key or target not in seen_fields:
                        raise ValueError(f"{path}.visible_when: must reference an earlier field")
                regex = field.validation.regex if field.validation else None
                if regex:
                    # Compiled here, at save time, so a pattern that cannot run --
                    # or is long enough to be a ReDoS -- never reaches a submission.
                    try:
                        compile_handle_pattern(regex)
                    except InvalidHandlePattern as exc:
                        raise ValueError(f"{path}.validation.regex: {exc}") from exc
                seen_fields[field.key] = order
                order += 1
        return self

    def fields(self) -> list[FormField]:
        return [f for s in self.sections for f in s.fields]

    def field(self, key: str) -> FormField | None:
        return next((f for f in self.fields() if f.key == key), None)

    def builtin(self, key: str) -> FormField | None:
        f = self.field(key)
        return f if f is not None and f.is_builtin else None

    def public_keys(self) -> frozenset[str]:
        return frozenset(f.key for f in self.fields() if f.visibility == "public")

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def default_schema() -> FormSchema:
    def b(key: str, **kw: Any) -> FormField:
        return FormField(key=key, kind="builtin", **kw)

    return FormSchema(
        sections=[
            FormSection(
                key="accounts",
                fields=[b("battle_tag", required=True), b("smurf_tags"), b("identity_discord"), b("identity_twitch")],
            ),
            FormSection(key="roles", fields=[b("roles")]),
            FormSection(key="details", fields=[b("public_notes")]),
        ]
    )


def schema_from_form(form: Any) -> FormSchema | None:
    """The current schema of a ``BalancerRegistrationForm`` (or any object with
    ``current_version.schema_json``); ``None`` when there is no form/version."""
    version = getattr(form, "current_version", None) if form is not None else None
    raw = getattr(version, "schema_json", None)
    return FormSchema.model_validate(raw) if raw else None
