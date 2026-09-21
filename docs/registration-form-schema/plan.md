# Registration Form Schema — Implementation Plan
**Status:** implemented (2026-09-21)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the registration form's two hard-coded field systems with one versioned, sectioned `FormSchema` (shared domain), typed answers, per-field visibility, conditional visibility, workspace templates, an identity table instead of per-provider columns, and one server-side validator with structured errors — end to end, backend to browser.

**Architecture:** `backend/shared/domain/forms/` owns the schema model, the builtin catalog and pure normalisation. tournament-service owns versions, templates, the answer pipeline (normalise → role/verified plugins → writer) and the read projection with public-key stripping. The frontend renders every form surface (public wizard, team/invite wizards, admin editor, builder preview) from the schema through one `SchemaForm` with a renderer registry; server errors map to fields by `code`.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 async, Alembic (hand-written revisions), pytest via `uv`; Next.js 16 / React, TanStack Query, next-intl, `@dnd-kit`, vitest + bun:test.

**Spec:** [`docs/registration-form-schema/design.md`](./design.md) — read it first; every task argues from it.

## Global Constraints

- Code-intelligence routing from `.claude/CLAUDE.md` applies: graft/CodeGraph first, `grep/glob/read` as fallback.
- Backend tests run **per package**: `cd backend && uv run pytest shared/tests`, `uv run pytest tournament-service/tests`, `uv run pytest balancer-service/tests`, `uv run pytest tests` (the cross-service suite in `backend/tests`). Lint: `cd backend && uv run bash scripts/lint.sh`.
- Frontend: `cd frontend && bun run typecheck && bun run lint && bun run lint:zones && bun run test:split && bun run test:vitest && bun run test:bun`. Never `next build` for testing (AGENTS.md).
- New tables ⇒ regenerate `docs/database_erd.md`: `cd backend && uv run python scripts/export_erd.py`. Changed Pydantic wire models ⇒ `cd backend && bash scripts/export_openapi_schemas.sh`. CI fails when either is stale.
- Migrations are hand-written, revision ids are short slugs (`regform01`), `down_revision` is the current head from `cd backend && uv run alembic heads`. Migrations do **not** import `shared`.
- Structured errors: `ApiHTTPException(status, [ApiExc(msg=..., code=..., field=...)])`. Never raise a bare-string 422 from the new code.
- Clean cutover: no compatibility shims, no re-exports of deleted types, no dual-write of `built_in_fields_json`/`custom_fields_json`. Every caller is migrated in the task that changes its contract.
- Builtin keys exist in exactly two places: `backend/shared/domain/forms/builtins.py` (authoritative) and `frontend/src/lib/forms/builtin-keys.ts` (UI list; the server rejects anything else).
- Conventional commits: `feat(registration): …`, `refactor(registration): …`, `test(registration): …`, `feat(frontend): …`.

---

## File map

**Create**

| Path | Responsibility |
|---|---|
| `backend/shared/domain/forms/__init__.py` | public re-exports |
| `backend/shared/domain/forms/schema.py` | `FormSchema`, `FormSection`, `FormField`, `FieldValidation`, `Condition`, invariants, `canonical_json`, `default_schema`, `schema_from_form` |
| `backend/shared/domain/forms/builtins.py` | builtin catalog, params models, `DEFAULT_PATTERNS`, identity key helpers |
| `backend/shared/domain/forms/validate.py` | `ErrorCode`, `FieldError`, `NormalizedAnswers`, `evaluate_condition`, `visible_fields`, `normalize_answers`, `raise_field_errors` |
| `backend/shared/tests/test_form_schema.py` | invariants, normalise matrix, conditions, canonical json |
| `backend/migrations/versions/regform01_form_schema.py` | tables, columns, inline legacy converter, backfill, drops |
| `backend/tests/test_regform01_convert.py` | golden test of the migration's converter |
| `backend/tournament-service/src/services/registration/form_service.py` | `RegistrationFormService`: get, schema, upsert with versions, stale count |
| `backend/tournament-service/src/services/registration/roles_rules.py` | role composition / sub-role / hero rules → `FieldError`s (moved from `validation.py`) |
| `backend/tournament-service/src/services/registration/answers.py` | `RegistrationAnswerService`: validate (normalise + plugins), `apply` writer, `answers_of` projection |
| `backend/tournament-service/src/services/registration/templates.py` | `RegistrationFormTemplateService` |
| `backend/tournament-service/src/schemas/registration_form.py` | `RegistrationFormRead/Upsert`, template read/upsert |
| `backend/shared/repository/registration.py` (modify) | `RegistrationFormVersionRepository`, `RegistrationFormTemplateRepository`, identity helpers |
| `frontend/src/types/forms.types.ts` | `FormSchema`, `FormSection`, `FormField`, `Condition`, params types |
| `frontend/src/lib/forms/builtin-keys.ts` | `BUILTIN_FIELD_KEYS`, `IDENTITY_PROVIDERS`, `identityKey`, `identityProvider`, `isBuiltinKey` |
| `frontend/src/lib/forms/visible-when.ts` | `evaluateCondition`, `visibleFields` |
| `frontend/src/lib/forms/validate.ts` | `validateAnswer(field, value, t)` generic rules |
| `frontend/src/lib/forms/form-errors.ts` | `fieldErrorsFrom(error)` |
| `frontend/src/lib/forms/keys.ts` | `makeUniqueFieldKey` (moved from `formConfig.ts`) |
| `frontend/src/components/forms/{types.ts,SchemaForm.tsx,GenericField.tsx,AnswerValue.tsx}` | schema-driven renderer |
| `frontend/src/components/registration/fields/*.tsx` + `registrationRenderers.ts` | builtin renderers |
| `frontend/src/components/registration/RegistrationSchemaForm.tsx` | replaces `UnifiedRegistrationForm.tsx` |
| `frontend/src/components/balancer/form/_components/{SectionList,FieldEditor,RolesParamsEditor,AddFieldMenu,TemplateMenu}.tsx` | builder pieces |
| `frontend/src/services/registration-form-templates.service.ts` | template API |
| `frontend/src/app/admin/settings/registration-forms/page.tsx` | workspace templates screen |

**Delete** (final cleanup task): `backend/tournament-service/src/services/registration/validation.py`; `frontend/src/components/registration/{UnifiedRegistrationForm.tsx,AccountStep.tsx,DetailsStep.tsx,CustomField.tsx,customFieldValue.tsx,validation.ts,validation.test.ts,DetailsStep.behavior.test.tsx}`; `frontend/src/components/balancer/form/_components/{BuiltInFieldsCard.tsx,BuiltInFieldsCard.behavior.test.tsx,CustomFieldsCard.tsx,SubrolesTab.tsx,formConfig.ts}`.

---

## Phase A — shared domain (no database)

### Task 1: `FormSchema` model and invariants

**Files:**
- Create: `backend/shared/domain/forms/__init__.py`, `backend/shared/domain/forms/schema.py`
- Test: `backend/shared/tests/test_form_schema.py`

**Interfaces:**
- Produces: `FormSchema`, `FormSection`, `FormField`, `FieldValidation`, `Condition`, `FieldKind`, `Visibility`, `ConditionOp`, `KEY_PATTERN`, `FormSchema.fields()`, `.field(key)`, `.builtin(key)`, `.public_keys()`, `.canonical_json()`, `default_schema()`, `schema_from_form(form)`. Depends on Task 2's catalog for invariant 3/4 — write Task 1 and Task 2 together in one commit; the tests below exercise both.

- [ ] **Step 1: Write the failing tests** (`backend/shared/tests/test_form_schema.py`)

```python
import pytest
from pydantic import ValidationError

from shared.domain.forms import FormField, FormSchema, FormSection, default_schema


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
    a = _schema(FormField(key="battle_tag", kind="builtin"), FormField(key="phone", kind="text", label="P", visibility="organizers"))
    b = FormSchema.model_validate(a.model_dump())
    assert a.public_keys() == frozenset({"battle_tag"})
    assert a.canonical_json() == b.canonical_json()


def test_default_schema_matches_todays_default_form():
    keys = [f.key for f in default_schema().fields()]
    assert keys == ["battle_tag", "smurf_tags", "identity_discord", "identity_twitch", "roles", "public_notes"]
    assert [s.key for s in default_schema().sections] == ["accounts", "roles", "details"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest shared/tests/test_form_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: shared.domain.forms`

- [ ] **Step 3: Implement `schema.py`**

```python
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

from pydantic import BaseModel, Field, model_validator

from shared.domain.forms.builtins import IDENTITY_KEY_PREFIX, builtin_spec, is_builtin_key

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
                            raise ValueError(f"{path}.params.{'.'.join(str(p) for p in first['loc'])}: {first['msg']}") from exc
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
    b = lambda key, **kw: FormField(key=key, kind="builtin", **kw)  # noqa: E731
    return FormSchema(
        sections=[
            FormSection(key="accounts", fields=[b("battle_tag", required=True), b("smurf_tags"), b("identity_discord"), b("identity_twitch")]),
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
```

`__init__.py` re-exports every public name from the three modules.

- [ ] **Step 4: Run tests** — `cd backend && uv run pytest shared/tests/test_form_schema.py -q` → PASS after Task 2 lands (same commit).

### Task 2: Builtin catalog

**Files:**
- Create: `backend/shared/domain/forms/builtins.py`
- Test: `backend/shared/tests/test_form_schema.py` (tests from Task 1 cover it; add the two below)

**Interfaces:**
- Produces: `BUILTIN_KEYS`, `IDENTITY_KEY_PREFIX`, `IDENTITY_PROVIDERS`, `identity_key(provider)`, `identity_provider(key)`, `is_builtin_key(key)`, `BuiltinSpec`, `builtin_spec(key)`, `RolesParams`, `TopHeroesParams`, `IdentityParams`, `BattleTagParams`, `DEFAULT_PATTERNS`, `default_pattern(field)`.

- [ ] **Step 1: Add tests**

```python
from shared.domain.forms.builtins import IDENTITY_PROVIDERS, RolesParams, builtin_spec, identity_key, identity_provider

def test_identity_keys_round_trip_for_every_non_battlenet_provider():
    assert "battlenet" not in IDENTITY_PROVIDERS
    for provider in IDENTITY_PROVIDERS:
        assert identity_provider(identity_key(provider)) == provider
        assert builtin_spec(identity_key(provider)).fixed_visibility is None
    assert identity_provider("identity_nope") is None and builtin_spec("identity_nope") is None

def test_roles_params_defaults_reproduce_todays_optional_mode():
    p = RolesParams()
    assert (p.primary_required, p.additional_required, p.flex_mode, p.top_heroes.enabled, p.top_heroes.max) == (True, False, "optional", False, 5)
```

- [ ] **Step 2: Implement**

```python
from __future__ import annotations
from typing import Literal, NamedTuple
from pydantic import BaseModel, ConfigDict, Field
from shared.core.social import SocialProvider

IDENTITY_KEY_PREFIX = "identity_"
IDENTITY_PROVIDERS: tuple[str, ...] = (SocialProvider.DISCORD, SocialProvider.TWITCH, SocialProvider.BOOSTY, SocialProvider.VK, SocialProvider.YOUTUBE)

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class BattleTagParams(_Strict):
    require_verified: bool = False

class IdentityParams(_Strict):
    require_verified: bool = False

class TopHeroesParams(_Strict):
    enabled: bool = False
    required: bool = False
    max: int = Field(default=5, ge=1, le=20)

class RolesParams(_Strict):
    primary_required: bool = True
    additional_required: bool = False
    flex_allowed: bool = True        # legacy flex_role.enabled; False ⇒ an all-primary (full-flex) submission is refused
    flex_mode: Literal["optional", "all_roles", "forced"] = "optional"
    subroles: dict[str, list[str]] = Field(default_factory=dict)   # role code -> allowed sub-role slugs; {} = every catalog slug
    top_heroes: TopHeroesParams = Field(default_factory=TopHeroesParams)

class BuiltinSpec(NamedTuple):
    key: str
    fixed_visibility: Literal["public", "organizers"] | None
    params_model: type[BaseModel] | None

_STATIC: dict[str, BuiltinSpec] = {
    "battle_tag": BuiltinSpec("battle_tag", "public", BattleTagParams),
    "smurf_tags": BuiltinSpec("smurf_tags", None, None),
    "roles": BuiltinSpec("roles", "public", RolesParams),
    "stream_pov": BuiltinSpec("stream_pov", "public", None),
    "public_notes": BuiltinSpec("public_notes", "public", None),
    "organizer_notes": BuiltinSpec("organizer_notes", "organizers", None),
}
BUILTIN_KEYS: tuple[str, ...] = tuple(_STATIC) + tuple(IDENTITY_KEY_PREFIX + p for p in IDENTITY_PROVIDERS)

def identity_key(provider: str) -> str: return IDENTITY_KEY_PREFIX + provider
def identity_provider(key: str) -> str | None:
    if not key.startswith(IDENTITY_KEY_PREFIX): return None
    provider = key[len(IDENTITY_KEY_PREFIX):]
    return provider if provider in IDENTITY_PROVIDERS else None
def is_builtin_key(key: str) -> bool: return key in BUILTIN_KEYS
def builtin_spec(key: str) -> BuiltinSpec | None:
    if key in _STATIC: return _STATIC[key]
    return BuiltinSpec(key, None, IdentityParams) if identity_provider(key) else None

#: Server-side defaults; today these live only in frontend formConfig.ts:30-35.
DEFAULT_PATTERNS: dict[str, str] = {
    "battle_tag": r"([^#]{2,12}#[0-9]{4,})",
    "smurf_tags": r"([^#]{2,12}#[0-9]{4,})",
    identity_key(SocialProvider.DISCORD): r"^[a-z0-9_.]{2,32}$",
    identity_key(SocialProvider.TWITCH): r"^[a-zA-Z0-9_]{4,25}$",
    identity_key(SocialProvider.BOOSTY): r"^[^#]{2,50}$",
    "url": r"^https?://.+$",
}
def default_pattern(key: str, kind: str) -> str | None:
    return DEFAULT_PATTERNS.get(key) or DEFAULT_PATTERNS.get(kind)
```

- [ ] **Step 3: Run** `cd backend && uv run pytest shared/tests/test_form_schema.py -q` → PASS.
- [ ] **Step 4: Commit** — `git add backend/shared/domain/forms backend/shared/tests/test_form_schema.py && git commit -m "feat(forms): FormSchema model, builtin catalog and invariants"`

### Task 3: Answer normalisation and structured errors

**Files:**
- Create: `backend/shared/domain/forms/validate.py`
- Modify: `backend/shared/core/errors.py:12-14` (`ApiExc.field`)
- Test: `backend/shared/tests/test_form_schema.py`, `backend/shared/tests/test_rpc_error_details.py` (existing — add one assertion that `field` survives `model_dump`)

**Interfaces:**
- Produces:
  ```python
  class ErrorCode(StrEnum): REQUIRED="required"; INVALID_FORMAT="invalid_format"; INVALID_TYPE="invalid_type"; INVALID_OPTION="invalid_option"; TOO_MANY="too_many"; NOT_VERIFIED="not_verified"; UNKNOWN_FIELD="unknown_field"; FORM_VERSION_STALE="form_version_stale"; SCHEMA_INVALID="schema_invalid"
  @dataclass(frozen=True, slots=True) class FieldError: field: str; code: str; msg: str; params: Mapping[str, Any] = MappingProxyType({})
  @dataclass(frozen=True, slots=True) class NormalizedAnswers: values: dict[str, Any]; errors: list[FieldError]
  def evaluate_condition(cond: Condition, answers: Mapping[str, Any]) -> bool
  def visible_fields(schema: FormSchema, answers: Mapping[str, Any]) -> list[FormField]
  def normalize_answers(schema: FormSchema, answers: Mapping[str, Any], *, partial: bool = False, enforce_required: bool = True) -> NormalizedAnswers
  def raise_field_errors(errors: Sequence[FieldError], status_code: int = 422) -> NoReturn
  ```
- `ApiExc` becomes `class ApiExc(BaseModel): msg: str; code: str; field: str | None = None`.

- [ ] **Step 1: Tests** (append to `test_form_schema.py`)

```python
from shared.domain.forms import FormField, FormSchema, FormSection, evaluate_condition, normalize_answers


def _s(*fields): return FormSchema(sections=[FormSection(key="s", fields=list(fields))])
def _codes(result): return {(e.field, e.code) for e in result.errors}

def test_number_checkbox_multi_select_and_date_are_coerced_to_typed_values():
    schema = _s(FormField(key="age", kind="number", label="A"), FormField(key="ok", kind="checkbox", label="O"),
                FormField(key="days", kind="multi_select", label="D", options=["sat", "sun"]), FormField(key="born", kind="date", label="B"))
    r = normalize_answers(schema, {"age": "17", "ok": "true", "days": ["sun"], "born": "2001-02-03"})
    assert r.errors == [] and r.values == {"age": 17, "ok": True, "days": ["sun"], "born": "2001-02-03"}
    assert normalize_answers(schema, {"age": "1.5"}).values["age"] == 1.5
    bad = normalize_answers(schema, {"age": "x", "ok": "maybe", "days": ["mon"], "born": "03.02.2001"})
    assert _codes(bad) == {("age", "invalid_type"), ("ok", "invalid_type"), ("days", "invalid_option"), ("born", "invalid_type")}

def test_required_checkbox_must_be_true_and_required_reports_every_missing_field():
    schema = _s(FormField(key="rules", kind="checkbox", label="R", required=True), FormField(key="vk", kind="text", label="V", required=True))
    r = normalize_answers(schema, {"rules": False, "vk": "  "})
    assert _codes(r) == {("rules", "required"), ("vk", "required")}
    assert normalize_answers(schema, {"vk": "x"}, enforce_required=False).errors == []

def test_hidden_field_is_dropped_and_never_required():
    schema = _s(FormField(key="stream_pov", kind="builtin"),
                FormField(key="identity_twitch", kind="builtin", required=True, visible_when={"field": "stream_pov", "op": "truthy"}))
    r = normalize_answers(schema, {"stream_pov": False, "identity_twitch": "abcd"})
    assert r.errors == [] and "identity_twitch" not in r.values
    r2 = normalize_answers(schema, {"stream_pov": True})
    assert _codes(r2) == {("identity_twitch", "required")}

def test_default_patterns_apply_server_side_and_explicit_regex_wins():
    schema = _s(FormField(key="identity_discord", kind="builtin"), FormField(key="site", kind="url", label="S"),
                FormField(key="battle_tag", kind="builtin", validation={"regex": "^X#[0-9]{4}$", "error_message": "X only"}))
    r = normalize_answers(schema, {"identity_discord": "Bad Name!", "site": "ftp://x", "battle_tag": "Y#1234"})
    assert _codes(r) == {("identity_discord", "invalid_format"), ("site", "invalid_format"), ("battle_tag", "invalid_format")}
    assert next(e for e in r.errors if e.field == "battle_tag").msg == "X only"

def test_unknown_key_and_partial_semantics():
    schema = _s(FormField(key="vk", kind="text", label="V", required=True), FormField(key="tg", kind="text", label="T"))
    assert _codes(normalize_answers(schema, {"nope": 1})) == {("nope", "unknown_field"), ("vk", "required")}
    assert normalize_answers(schema, {"tg": "x"}, partial=True).errors == []

def test_evaluate_condition_ops():
    from shared.domain.forms import Condition
    assert evaluate_condition(Condition(field="a", op="eq", value="x"), {"a": "x"})
    assert evaluate_condition(Condition(field="a", op="neq", value="x"), {"a": "y"})
    assert evaluate_condition(Condition(field="a", op="in", value=["x", "y"]), {"a": "y"})
    assert evaluate_condition(Condition(field="a", op="in", value=["x"]), {"a": ["x", "z"]})
    assert evaluate_condition(Condition(field="a", op="truthy"), {"a": "true"})
    assert not evaluate_condition(Condition(field="a", op="truthy"), {"a": "false"})
    assert not evaluate_condition(Condition(field="a", op="truthy"), {})
```

- [ ] **Step 2: Run** → FAIL (`validate` module missing).

- [ ] **Step 3: Implement `validate.py`**

Rules per kind (all strings are `.strip()`ped first; `""`/`None`/`[]` count as empty):

| kind / key | accept | store | error |
|---|---|---|---|
| `text`, `textarea`, `url`, `public_notes`, `organizer_notes` | `str` | `str` | pattern → `invalid_format` |
| `number` | `int`, `float`, `str` matching `^-?\d+(?:[.,]\d+)?$` | `int` when integral else `float` | `invalid_type` |
| `checkbox`, `stream_pov` | `bool`, `"true"/"false"` | `bool` | `invalid_type`; required and `False` → `required` |
| `select` | `str ∈ options` | `str` | `invalid_option` |
| `multi_select` | `list[str] ⊆ options`, unique | `list[str]` in option order | `invalid_option`; `invalid_type` if not a list |
| `date` | `date.fromisoformat` | `"YYYY-MM-DD"` | `invalid_type` |
| `battle_tag` | `str` | trimmed original | pattern checked on `value.split("#")[0].casefold() + "#" + tail` → `invalid_format` |
| `smurf_tags` | `list[str]` | trimmed, de-duplicated | each tag as `battle_tag` |
| `identity_*` | `str` | `normalize_social_handle(provider, value)` | pattern → `invalid_format` |
| `roles` | `list[dict]` each with `role: str`, optional `subrole: str|None`, `is_primary: bool`, `top_heroes: list[str]|None` | as given (rules in Task 9) | `invalid_type` |

Algorithm: `visible = visible_fields(schema, answers)`; `unknown = answers.keys() - {f.key for f in schema.fields()}` → `unknown_field` each; for each visible field: `if partial and key not in answers: continue`; coerce; `if empty: if required and enforce_required: error(required) ; continue`; pattern (explicit regex, else `default_pattern(key, kind)`); collect. Hidden fields are skipped entirely (not in `values`). `evaluate_condition`: `truthy` treats `"false"`, `0`, `""`, `None`, `[]` as false; `in` is `answer in value` for scalars and `bool(set(answer) & set(value))` for lists. `raise_field_errors` builds `ApiHTTPException(status_code, [ApiExc(msg=e.msg, code=e.code, field=e.field) for e in errors])`.

- [ ] **Step 4: Change `ApiExc`** — add `field: str | None = None`; in `backend/shared/tests/test_rpc_error_details.py` add `assert ApiExc(msg="m", code="c", field="f").model_dump(mode="json") == {"msg": "m", "code": "c", "field": "f"}`.
- [ ] **Step 5: Run** `cd backend && uv run pytest shared/tests -q` → PASS. `uv run bash scripts/lint.sh` → clean.
- [ ] **Step 6: Commit** — `git commit -am "feat(forms): normalize_answers with structured field errors; ApiExc.field"`

---

## Phase B — database

### Task 4: ORM models and load options

**Files:**
- Modify: `backend/shared/models/registration/registration.py` (`BalancerRegistrationForm:29-115`, `BalancerRegistration:168-278`, `__all__`), `backend/shared/domain/roster.py` (`PlayerRoster:102-243`), `backend/shared/services/roster.py` (`registration_load_options`, `RosterEngine._build:306-390`, `full_export:431-527`), `backend/shared/repository/registration.py`
- Regenerate: `docs/database_erd.md`

**Interfaces:**
- Produces models `BalancerRegistrationFormVersion(form_id, number, schema_json, created_by)`, `BalancerRegistrationFormTemplate(workspace_id, name, schema_json, created_by)`, `BalancerRegistrationIdentity(registration_id, provider, handle, handle_normalized)`; `BalancerRegistrationForm.current_version_id/current_version`; `BalancerRegistration.public_notes`, `.organizer_notes`, `.form_version_id/form_version`, `.identities`; removed: `notes`, `discord_nick`, `twitch_nick`, `boosty_nick`, `built_in_fields_json`, `custom_fields_json`.
- `PlayerRoster.identities: Mapping[str, str]` (provider → handle), `.public_notes: str | None`; removed `discord_nick/twitch_nick/boosty_nick/notes`.
- Repositories: `RegistrationFormVersionRepository.get(session, id)`, `.latest_number(session, form_id) -> int`; `RegistrationFormTemplateRepository.list_for_workspace(session, workspace_id)`, `.get_for_workspace(session, workspace_id, template_id)`.

- [ ] **Step 1: Models**

```python
class BalancerRegistrationFormVersion(db.TimeStampIntegerMixin):
    """One immutable snapshot of a form's schema. Append-only: a save whose
    canonical JSON differs from the current version inserts number+1."""
    __tablename__ = "registration_form_version"
    __table_args__ = (UniqueConstraint("form_id", "number", name="uq_balancer_registration_form_version_number"), {"schema": "balancer"})
    form_id: Mapped[int] = mapped_column(ForeignKey("balancer.registration_form.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer(), nullable=False)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)

class BalancerRegistrationFormTemplate(db.TimeStampIntegerMixin):
    __tablename__ = "registration_form_template"
    __table_args__ = (Index("uq_balancer_registration_form_template_name", "workspace_id", text("lower(name)"), unique=True), {"schema": "balancer"})
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)

class BalancerRegistrationIdentity(db.TimeStampIntegerMixin):
    """A social handle the registrant typed for one provider (``identity_<provider>``)."""
    __tablename__ = "registration_identity"
    __table_args__ = (UniqueConstraint("registration_id", "provider", name="uq_balancer_registration_identity_provider"),
                      Index("ix_balancer_registration_identity_handle", "provider", "handle_normalized"), {"schema": "balancer"})
    registration_id: Mapped[int] = mapped_column(ForeignKey("balancer.registration.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    handle_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    registration: Mapped[BalancerRegistration] = relationship(back_populates="identities")
```

On `BalancerRegistrationForm`: delete `built_in_fields_json`, `custom_fields_json`; add `current_version_id: Mapped[int | None] = mapped_column(ForeignKey("balancer.registration_form_version.id", ondelete="SET NULL"), nullable=True)` and `current_version: Mapped[BalancerRegistrationFormVersion | None] = relationship(foreign_keys=[current_version_id], post_update=True)`. Nullable on purpose: `registration_form ↔ registration_form_version` is an FK cycle and PostgreSQL never defers NOT NULL, so the ORM could not insert a form with a NOT NULL pointer to a version that needs the form's id first. `RegistrationFormService.apply_schema` (Task 6) always creates the form and version #1 in one flush, and `schema_from_form` returns `None` for a form without a version ("not configured"). On `BalancerRegistration`: rename `notes → public_notes`, add `organizer_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)`, add `form_version_id` (`ForeignKey("balancer.registration_form_version.id", ondelete="SET NULL"), nullable=True, index=True`) + `form_version` relationship, add `identities: Mapped[list[BalancerRegistrationIdentity]] = relationship(back_populates="registration", cascade="all, delete-orphan")`, delete the three nick columns. Comment on `identities`/`form_version`: never lazy-loaded in async code (same rule as `roles`). Imports needed in the models file: `Index`, `text` from `sqlalchemy`; `ValidationError` from `pydantic` in `schema.py`.

- [ ] **Step 2: `registration_load_options()`** adds `selectinload(models.BalancerRegistration.identities)` and `selectinload(models.BalancerRegistration.form_version)`. `PlayerRoster` swaps the three nick fields for `identities: Mapping[str, str] = field(default_factory=dict)` and `notes → public_notes`; `RosterEngine._build` fills `identities={i.provider: i.handle for i in reg.identities}`; `full_export` private block emits `"identities": dict(roster.identities), "public_notes": roster.public_notes`. Fix `backend/balancer-service/tests/test_owt_player_export.py:271-292` accordingly.
- [ ] **Step 3: Repositories** — add the two classes with the methods above (follow `RegistrationFormRepository` style, `BaseRepository[...]`).
- [ ] **Step 4:** `cd backend && uv run python scripts/export_erd.py` (new tables land in the existing registration section; no new package). Import check: `uv run python -c "import shared.models"`.
- [ ] **Step 5: Commit** — `feat(registration): form version, template and identity models`

Expect tournament-service/balancer-service tests to break here; they are fixed in Tasks 6–10. Do not run them yet.

### Task 5: Migration `regform01_form_schema`

**Files:**
- Create: `backend/migrations/versions/regform01_form_schema.py`
- Test: `backend/tests/test_regform01_convert.py`

**Interfaces:**
- Produces pure functions in the migration module: `legacy_to_schema(built_in: dict, custom: list) -> dict` (a `FormSchema`-shaped dict), `legacy_nicks(row) -> list[tuple[str, str, str]]` (provider, handle, normalized), `remap_sheet_targets(mapping: dict | None) -> dict | None`.

- [ ] **Step 1: Golden test**

```python
import importlib.util, pathlib

_PATH = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions" / "regform01_form_schema.py"
spec = importlib.util.spec_from_file_location("regform01", _PATH); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

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
LEGACY_CUSTOM = [{"key": "vk", "label": "VK", "type": "url", "required": False, "placeholder": None, "options": None, "validation": None, "show_in_draft": True},
                 {"key": "age", "label": "Age", "type": "number", "required": True}]

def test_default_form_converts_to_three_sections_in_todays_order():
    schema = mod.legacy_to_schema(LEGACY_DEFAULT_BUILTINS, LEGACY_CUSTOM)
    assert [s["key"] for s in schema["sections"]] == ["accounts", "roles", "details"]
    assert [f["key"] for f in schema["sections"][0]["fields"]] == ["battle_tag", "smurf_tags", "identity_discord", "identity_twitch"]
    roles = schema["sections"][1]["fields"][0]
    assert roles["params"] == {"primary_required": True, "additional_required": True, "flex_allowed": True, "flex_mode": "all_roles",
                               "subroles": {"tank": ["main_tank"]}, "top_heroes": {"enabled": True, "required": False, "max": 3}}
    assert [f["key"] for f in schema["sections"][2]["fields"]] == ["stream_pov", "public_notes", "vk", "age"]
    discord = schema["sections"][0]["fields"][2]
    assert discord["kind"] == "builtin" and discord["params"] == {"require_verified": True} and discord["visibility"] == "public"
    assert schema["sections"][2]["fields"][2] == {"key": "vk", "kind": "url", "label": "VK", "required": False, "visibility": "public", "show_in_draft": True}

def test_disabled_builtins_and_absent_keys_are_omitted_and_empty_config_yields_the_default():
    assert [f["key"] for f in mod.legacy_to_schema({}, [])["sections"][0]["fields"]] == ["battle_tag", "smurf_tags", "identity_discord", "identity_twitch", "identity_boosty"]
    only_tag = mod.legacy_to_schema({k: {"enabled": False} for k in LEGACY_DEFAULT_BUILTINS if k != "battle_tag"} | {"battle_tag": {"enabled": True}}, [])
    assert [f["key"] for s in only_tag["sections"] for f in s["fields"]] == ["battle_tag"]

def test_nicks_and_sheet_targets_are_remapped():
    assert mod.legacy_nicks({"discord_nick": " Ferz ", "twitch_nick": None, "boosty_nick": "B"}) == [("discord", "Ferz", "ferz"), ("boosty", "B", "b")]
    assert mod.remap_sheet_targets({"targets": {"discord_nick": {"c": 1}, "notes": {"c": 2}, "battle_tag": {"c": 3}}}) == \
        {"targets": {"identity_discord": {"c": 1}, "public_notes": {"c": 2}, "battle_tag": {"c": 3}}}
```

Adjust the `remap_sheet_targets` fixture to the real shape of `mapping_config_json` (read `backend/tournament-service/src/domain/registration/mapping_catalog.py` and `sheet_parsing.py` first; the function must rename keys wherever target keys occur in that structure).

- [ ] **Step 2: Write the migration.** Header like `reghide01`; `down_revision` = output of `cd backend && uv run alembic heads`. Legacy default when a key is absent from `built_in_fields_json`: `battle_tag/smurf_tags/discord_nick/twitch_nick/boosty_nick/primary_role/additional_roles/flex_role/notes` enabled, `top_heroes/stream_pov` disabled (matches the wizard's `?.enabled !== false` reading in `UnifiedRegistrationForm.tsx:202` / `AccountStep.tsx:63-67` / `DetailsStep.tsx:61-62`; `top_heroes` and `stream_pov` are the two keys the wizard reads as `=== true`. NOT `formConfig.ts` `defaultEnabled`, which only seeds the builder UI and also disagrees on `smurf_tags`/`additional_roles`). Roles mapping: `primary_role.required → primary_required`, `additional_roles.required → additional_required`, `flex_role.enabled → flex_allowed`, `flex_role.mode (None → "optional") → flex_mode`, `primary_role.subroles ∪ additional_roles.subroles → subroles`, `top_heroes.{enabled, required, max_heroes (None → 5)} → top_heroes.{enabled, required, max}`; the `roles` field is emitted whenever `primary_role` or `additional_roles` is enabled, and the `roles` section is omitted otherwise. Custom `type` maps 1:1 to `kind`; `validation`, `placeholder`, `options`, `show_in_draft`, `required` carry over; every field gets `visibility: "public"`.

  `upgrade()` order: create three tables (`op.create_index("uq_balancer_registration_form_template_name", "registration_form_template", ["workspace_id", sa.text("lower(name)")], unique=True, schema="balancer")` for the template name) → add columns (`current_version_id` nullable, `form_version_id`, `organizer_notes`) → `op.alter_column("registration", "notes", new_column_name="public_notes", schema="balancer")` → data loop with `op.get_bind()`: for each `registration_form` row insert version 1 and update `current_version_id`; `UPDATE balancer.registration SET form_version_id = :v WHERE tournament_id = :t` (soft-deleted rows included — harmless and keeps reads uniform); for each registration with a non-empty nick insert identity rows; for each `registration_google_sheet_feed` rewrite `mapping_config_json` → drop the five legacy columns. The converter omits keys whose value is `None` and omits empty sections.

  `downgrade()`: re-add columns, reverse identity rows into nick columns, rename `public_notes → notes`, write `built_in_fields_json/custom_fields_json` from the current version with a `schema_to_legacy` inverse (custom kinds outside `text|number|select|checkbox|url` → `text`), drop the new columns and tables.

- [ ] **Step 3:** `cd backend && uv run pytest tests/test_regform01_convert.py -q` → PASS. Apply against the dev stack: `make migrate` (or `docker compose exec app-svc alembic upgrade head`), then `alembic downgrade -1` and `upgrade head` once to prove reversibility.
- [ ] **Step 4: Commit** — `feat(registration): regform01 — schema versions, templates, identities; drop legacy form JSON and nick columns`

---

## Phase C — tournament-service

### Task 6: Form service, versions, wire schemas

**Files:**
- Create: `backend/tournament-service/src/services/registration/form_service.py`, `backend/tournament-service/src/schemas/registration_form.py`
- Modify: `backend/tournament-service/src/schemas/registration.py` (delete `FieldValidationConfig`, `CustomFieldDefinition`, `BuiltInFieldConfig`, `RegistrationFormRead`, `RegistrationFormUpsert`, `RoleWithSubrole`, `RegistrationCreate`, `RegistrationUpdate`; add `RegistrationSubmit`, `RegistrationUpdate`), `backend/tournament-service/src/services/registration/service.py:1158-1235` (delete `upsert_registration_form`), `serializers.py:151-190`, `schemas/registration_build.py:149-201` (`_resolve_top_heroes_config`, `_form_to_read`), `_common.py:59-70`, `backend/shared/domain/roster.py:49-68` (`flex_role_mode`), `rpc/public_rpc.py:382-406` (`_reg_pub_form`), `rpc/registration_admin.py:266-296`
- Test: `backend/tournament-service/tests/test_registration_form_versions.py` (new)

**Interfaces:**
```python
# schemas/registration_form.py
class RegistrationFormRead(BaseModel):
    id: int; tournament_id: int; workspace_id: int; is_open: bool
    auto_approve: bool = False; require_open_profile: bool = False; open_profile_scope: str = "main"; show_ranks: bool = False
    hide_registrations: bool = False; max_participants: int | None = None; require_subscription: bool = False
    subscription_stage: SubscriptionEnforcementStage = ...; subscription_scope: Literal["player", "team"] = "player"
    subscription_requirement_json: dict[str, Any] = {}; max_substitutes: int = 0
    team_rank_min: int | None = None; team_rank_max: int | None = None; team_max_rank_spread: int | None = None
    team_unique_identity: bool = False; team_require_discord_guild: bool = False
    form_schema: FormSchema; version_id: int; version_number: int
    stale_registrations: int | None = None          # organizer reads only
    subrole_catalog: dict[str, list[SubroleOption]] = {}
class RegistrationFormUpsert(BaseModel):            # same toggles as before, plus:
    form_schema: FormSchema
class RegistrationFormTemplateRead(BaseModel): id: int; workspace_id: int; name: str; form_schema: FormSchema; updated_at: datetime
class RegistrationFormTemplateUpsert(BaseModel): name: str = Field(min_length=1, max_length=64); form_schema: FormSchema
# schemas/registration.py
class RegistrationSubmit(BaseModel): form_version_id: int; answers: dict[str, Any]
class RegistrationUpdate(BaseModel): form_version_id: int; answers: dict[str, Any]
# services/registration/form_service.py
class RegistrationFormService:
    async def get_form(self, session, tournament_id) -> models.BalancerRegistrationForm | None      # eager current_version
    def schema_of(self, form) -> FormSchema                                                          # schema_from_form or raise 500-ish RuntimeError
    async def upsert(self, session, tournament_id, body: RegistrationFormUpsert, *, workspace_id, actor_user_id) -> models.BalancerRegistrationForm
    async def stale_count(self, session, form) -> int
    async def apply_schema(self, session, form, schema: FormSchema, *, actor_user_id) -> models.BalancerRegistrationFormVersion  # dedupe by canonical_json; used by upsert and templates
form_service = RegistrationFormService()
```
`flex_role_mode(form)` now reads `schema_from_form(form)` → `RolesParams.model_validate(schema.builtin("roles").params).flex_mode` when the builtin exists, else `"optional"`. `_resolve_top_heroes_config(form)` → `RolesParams(...).top_heroes`. `form_custom_field_defs(form)` → `[f for f in schema.fields() if not f.is_builtin]`.

- [ ] **Step 1: Test**

```python
async def test_upsert_creates_a_version_only_when_the_schema_changes(session_factory):
    form = await form_service.upsert(s, t.id, RegistrationFormUpsert(form_schema=default_schema()), workspace_id=ws.id, actor_user_id=1)
    assert form.current_version.number == 1
    again = await form_service.upsert(s, t.id, RegistrationFormUpsert(form_schema=default_schema(), show_ranks=True), workspace_id=ws.id, actor_user_id=1)
    assert again.current_version_id == form.current_version_id and again.show_ranks is True
    changed = default_schema(); changed.sections[2].fields.append(FormField(key="vk", kind="url", label="VK"))
    v2 = await form_service.upsert(s, t.id, RegistrationFormUpsert(form_schema=changed), workspace_id=ws.id, actor_user_id=1)
    assert v2.current_version.number == 2
```
plus `test_stale_count_counts_live_registrations_on_older_versions` (two registrations, bump version, expect 2; a soft-deleted one is not counted). Use the integration fixtures already used by `backend/app-service/tests/test_tournament_readiness.py::seeded` as the pattern; the suite skips when Postgres is unreachable.

- [ ] **Step 2: Implement** `form_service.py` (move and rewrite `upsert_registration_form`: toggles copied field by field as today; `apply_schema` compares `canonical_json` against `current_version.schema_json` re-validated through `FormSchema`; on insert the version gets `number = latest_number + 1`; keep the existing realtime emission for form edits — find it in the old `upsert_registration_form` and call it from the new service). `serialize_registration_form`/`_form_to_read` build the new read (`form_schema=schema_of(form)`, `version_id`, `version_number`, `stale_registrations` only when the caller passes it). `_reg_pub_form` passes `stale_registrations=None`; admin `_reg_form_get` passes `await form_service.stale_count(...)`. `_reg_form_upsert` uses `form_service.upsert`. Pydantic `ValidationError` from `FormSchema` on upsert → `raise_field_errors([FieldError(field=".".join(str(p) for p in err["loc"]), code="schema_invalid", msg=err["msg"])])`.
- [ ] **Step 3: Update readers** listed in the Files line; delete `_coerce_built_in_field_config`/`_coerce_custom_field_definition` usages that die with `validation.py` in Task 9.
- [ ] **Step 4:** `cd backend && uv run pytest tournament-service/tests/test_registration_form_versions.py -q` → PASS. Commit — `feat(registration): versioned form schema service and read model`

### Task 7: Role rules as field errors

**Files:**
- Create: `backend/tournament-service/src/services/registration/roles_rules.py`
- Modify: `backend/tournament-service/tests/test_registration_role_validation.py`, `tests/test_forced_flex_roles.py` (fixtures → schema; assertions → codes)

**Interfaces:**
```python
def validate_roles(field: FormField, roles: list[dict[str, Any]], *, subrole_catalog: dict[str, list[Any]] | None, hero_catalog: HeroCatalog | None) -> list[FieldError]
def is_flex_submission(roles: list[dict[str, Any]]) -> bool     # moved verbatim from validation.py:116-123
```
Codes: `roles.primary_required`, `roles.additional_required`, `roles.flex_unavailable` (`params.flex_allowed is False` and the submission is full-flex — today's "flex disabled ⇒ reject all-primary" rule), `roles.one_priority_or_flex`, `roles.unknown_role`, `roles.subrole_not_allowed`, `roles.too_many_heroes`, `roles.hero_wrong_class`. `field` on every error is `"roles"`.

- [ ] **Step 1:** Rewrite `test_registration_role_validation.py`: the `_form(built_in_fields)` helper becomes `_field(**params) -> FormField(key="roles", kind="builtin", params=params)`; every `pytest.raises(HTTPException, match=...)` becomes `assert [e.code for e in validate_roles(...)] == [...]`. Keep every scenario; add none.
- [ ] **Step 2:** Move `_catalog_slugs`, `_allowed_subroles`, `_validate_roles`, `is_flex_submission`, `_resolve_max_heroes`, `_validate_role_heroes` and the composition rules from `validation.py:55-177,378-430` into `roles_rules.py`, returning errors instead of raising. Sub-roles allowed = `params.subroles.get(role)` when non-empty, else every catalog slug (same as `_allowed_subroles` today).
- [ ] **Step 3:** `uv run pytest tournament-service/tests/test_registration_role_validation.py tournament-service/tests/test_forced_flex_roles.py -q` → PASS. Commit — `refactor(registration): role rules return field errors`

### Task 8: Answer service — validate, apply, project

**Files:**
- Create: `backend/tournament-service/src/services/registration/answers.py`
- Modify: `service.py` (`create_registration:576-690` → thin, `update_registration:692-720`, `submit_public_registration:794-924`), `lifecycle.py` (`create_manual_registration:220-314`, `update_registration_profile:316-446`), `audit.py:40-56`, `schemas/admin/balancer.py:420-519` (`BalancerRegistrationRead/CreateRequest/UpdateRequest`), `rpc/registration_admin.py:713-810`, `rpc/public_rpc.py:409-530`, `schemas/registration.py:219-275` (`RegistrationRead`), `schemas/registration_build.py:225-346` (`_reg_to_read`), `serializers.py:67-148`
- Delete: `services/registration/validation.py`
- Test: `tests/test_registration_write_path_fields.py`, `tests/test_registration_verified_identity.py`, `tests/test_registration_audit.py`, `tests/test_reg_to_read_privacy.py`, new `tests/test_registration_answers.py`

**Interfaces:**
```python
class RegistrationAnswerService:
    async def validate(self, session, *, schema: FormSchema, answers: Mapping[str, Any], partial: bool, enforce_required: bool,
                       player_id: int | None, workspace_id: int, hero_catalog: HeroCatalog | None) -> dict[str, Any]
        # normalize_answers → roles_rules.validate_roles (when "roles" in values) → require_verified check for battle_tag/identity_* whose params say so
        # (SocialAccount(provider, username matches normalized handle) for player_id; missing player ⇒ not_verified) → raise_field_errors on any error → return values
    def apply(self, registration: models.BalancerRegistration, values: Mapping[str, Any], *, schema: FormSchema, hero_catalog: HeroCatalog | None) -> None
        # battle_tag → battle_tag + battle_tag_normalized; smurf_tags → smurf_tags_json; stream_pov; public_notes; organizer_notes
        # identity_* → upsert BalancerRegistrationIdentity(provider, handle, handle_normalized=normalize_social_handle(...)); provider present in schema but absent/empty in values ⇒ delete row
        # roles → build_registration_roles(...) (service.py:99-140) then merge: keep rank_value/is_active of existing rows with the same role; delete rows not in the new set
        # custom keys → registration.custom_fields_json = {**existing (if partial), **custom_values}; keys of custom fields answered empty are removed
    def answers_of(self, registration) -> dict[str, Any]
        # {"smurf_tags": list, "stream_pov": bool, "public_notes", "organizer_notes", identity_<p>: handle..., **(custom_fields_json or {})}; None values omitted
answer_service = RegistrationAnswerService()
```
`RegistrationRead`: remove `smurf_tags_json`, `discord_nick`, `twitch_nick`, `boosty_nick`, `stream_pov`, `notes`, `custom_fields_json`; add `answers: dict[str, Any]`, `form_version_id: int | None`, `form_version_stale: bool`. `_reg_to_read(..., public_keys: frozenset[str] | None = None)` → `answers = answers_of(reg)` filtered to `public_keys` when given; `battle_tag` and `roles` stay top-level. Admin `BalancerRegistrationRead` mirrors this but never filters. Admin `Create/UpdateRequest`: replace the nick/notes/custom fields with `answers: dict[str, Any] = {}`; keep `display_name`, `admin_notes`, `status`, `balancer_status`, `exclude_reason`, `roles: list[AdminRegistrationRoleInput] | None` (admin rank rows continue through `lifecycle`; when both `answers["roles"]` and `roles` are sent, `roles` wins — document it on the schema).

- [ ] **Step 1: Tests** — port `test_registration_write_path_fields.py` to `answers` (public create persists `battle_tag`, identity rows, typed custom values, `public_notes`; self-update merges custom answers; admin update replaces; omitting leaves alone), `test_registration_verified_identity.py` to `validate(...)` raising `ApiHTTPException` whose details carry `code == "not_verified"` and `field == "identity_discord"`, `test_reg_to_read_privacy.py`: `answers` carry `public_notes` for anonymous readers and **not** `organizer_notes` nor an `organizers`-visibility custom answer, while `public_keys=None` returns everything. New: `test_role_update_preserves_rank_value_on_surviving_roles`, `test_submit_with_stale_version_is_409_form_version_stale`, `test_public_submit_validates_against_current_version_and_stamps_it`.
- [ ] **Step 2: Implement `answers.py`** and rewire: `submit_public_registration` → load form + schema, `if body.form_version_id != form.current_version_id: raise_field_errors([FieldError("form_version_id", "form_version_stale", "The registration form changed; reload and try again.")], status_code=409)`; `values = await answer_service.validate(...)`; create row (`tournament_id`, `workspace_member` via existing `ensure_player_identity` using `values.get("battle_tag")`), `answer_service.apply(...)`, `registration.form_version_id = form.current_version_id`. `update_registration` (self) = same with `partial=True`. `lifecycle.create_manual_registration/update_registration_profile` = `enforce_required=False`, `partial=True`, `player_id=None`. Public RPC bodies → `RegistrationSubmit`/`RegistrationUpdate`. `audit.py` field map: `public_notes`, `organizer_notes`, identities diffed per provider as `identity_<p>`; drop the three nick keys; `_EMPTY_IS_NULL` keeps `smurf_tags_json`, `custom_fields_json`.
- [ ] **Step 3: Delete `validation.py`**; fix imports (`VERIFIED_FIELD_PROVIDERS`, `BATTLE_TAG_FIELDS` consumers — graft `trace_calls` on each symbol before deleting).
- [ ] **Step 4:** `cd backend && uv run pytest tournament-service/tests -q` → PASS (sheet-sync tests are fixed in Task 9 — if they fail here, proceed to Task 9 before committing both together). Commit — `feat(registration): flat answers pipeline — normalize, plugins, writer, public projection`

### Task 9: Sheet sync, identity readers, export, balancer/stream consumers

**Files:**
- Modify: `tournament-service/src/domain/registration/mapping_catalog.py:104-276`, `sheet_parsing.py:358-471`, `services/registration/sheet_sync.py:166-208,499-766`, `services/registration/export.py:37-51`, `backend/shared/services/team_eligibility.py:44-52`, `backend/shared/repository/stream.py:164-195`, `backend/balancer-service/src/services/draft/board.py:95-125`, `backend/balancer-service/src/schemas/draft.py` (`DraftPlayerRead.from_seat` reads `roster.public_notes`), `backend/balancer-service/src/services/draft/loaders.py` (identities already via `registration_load_options`)
- Test: `tournament-service/tests/test_registration_sheet_mapping.py`, `backend/tests/test_stream_repository.py:175-179`, `balancer-service/tests/test_draft_contracts.py` (`_FormSession` → version scalar), `shared/tests/test_registration_team_guards.py`

- [ ] **Step 1:** `mapping_catalog._build_builtin_specs`: targets become `battle_tag`, `smurf_tags`, `identity_<p>` for each `IDENTITY_PROVIDERS`, `roles`-related targets as today, `stream_pov`, `public_notes`, `organizer_notes`, `admin_notes` (admin field, not in schema). `parse_sheet_row_detailed` emits `answers: dict` + admin fields; `apply_sheet_fields_to_registration` / `sync_google_sheet_feed` call `answer_service.validate(..., partial=True, enforce_required=False, player_id=None)` and `apply`; a row whose answers fail normalisation records the field errors in the feed's per-row error list (existing `MappingFieldError` shape) instead of writing.
- [ ] **Step 2:** `team_eligibility._identity_keys`: `nick = next((i.handle_normalized for i in registration.identities if i.provider == SocialProvider.DISCORD), "")`. `stream.py::list_self_declared_channels`: `join(BalancerRegistrationIdentity, and_(identity.registration_id == registration.id, identity.provider == "twitch"))`, select `identity.handle`; update the SQL assertion in `backend/tests/test_stream_repository.py` to `"balancer.registration_identity"` + `"twitch"`. `export._registration_identity_handles`: `[(i.provider, i.handle) for i in registration.identities]`.
- [ ] **Step 3:** `board.visible_custom_fields`: `select(BalancerRegistrationFormVersion.schema_json).join(BalancerRegistrationForm, BalancerRegistrationForm.current_version_id == BalancerRegistrationFormVersion.id).where(BalancerRegistrationForm.tournament_id == tournament_id)`; iterate `sections[*].fields[*]` with `kind != "builtin" and show_in_draft and visibility == "public"`; `VisibleCustomField.type = field["kind"]`. `_FormSession`/`_BoardSession` test doubles return the schema dict.
- [ ] **Step 4:** `cd backend && uv run pytest tournament-service/tests balancer-service/tests shared/tests tests -q` → PASS. `uv run bash scripts/lint.sh`. Commit — `refactor(registration): identities table and schema versions across sheet sync, eligibility, stream, export, draft board`

### Task 10: Templates service, RPC, gateway routes, OpenAPI

**Files:**
- Create: `tournament-service/src/services/registration/templates.py`
- Modify: `rpc/registration_admin.py` (six ops), gateway routes for tournament-service admin registration (find the file in `gateway/internal/tournament/` that declares the `registration_form` routes; add `GET/POST /api/v1/admin/ws/{workspace_id}/registration-form-templates`, `PUT/DELETE .../{template_id}`, `POST /api/v1/admin/balancer/tournaments/{tournament_id}/registration-form/apply-template`, `POST /api/v1/admin/balancer/tournaments/{tournament_id}/registration-form/save-template` — the house prefixes every neighbouring route in that table uses), RBAC route documentation the repo keeps for every grant (see commit `8e85427c` for the file), `backend/tests/test_rpc_route_parity.py` fixtures if they enumerate ops
- Test: `tournament-service/tests/test_registration_form_templates.py`

**Interfaces:**
```python
class RegistrationFormTemplateService:
    async def list(self, session, *, workspace_id) -> list[models.BalancerRegistrationFormTemplate]
    async def create(self, session, *, workspace_id, body: RegistrationFormTemplateUpsert, actor_user_id) -> template   # 409 code "template_name_taken"
    async def update(self, session, *, workspace_id, template_id, body, actor_user_id) -> template
    async def delete(self, session, *, workspace_id, template_id) -> None
    async def apply(self, session, *, workspace_id, tournament_id, template_id, actor_user_id) -> models.BalancerRegistrationForm   # form_service.apply_schema
    async def save_from_form(self, session, *, workspace_id, tournament_id, name, actor_user_id) -> template
```
Ops: `regform_template_list|create|update|delete|apply|save_from_form`, permission `registration_form` `read` for list, `update` for the rest, via `ensure_workspace_permission` (templates) and `_tournament_ctx(..., resource="registration_form")` (apply/save).

- [ ] **Step 1:** Tests: create/list/update/delete round trip; duplicate name (case-insensitive) → 409 `template_name_taken`; `apply` bumps the tournament form version and leaves the template untouched afterwards; `save_from_form` snapshots the current schema.
- [ ] **Step 2:** Implement service + ops + routes. `cd backend && bash scripts/export_openapi_schemas.sh` and commit the manifest; `uv run pytest tests/test_rpc_route_parity.py tests/test_rpc_error_code_parity.py -q`.
- [ ] **Step 3:** Commit — `feat(registration): workspace form templates`

---

## Phase D — frontend

### Task 11: Types, services, error mapping, pure helpers

**Files:**
- Create: `frontend/src/types/forms.types.ts`, `frontend/src/lib/forms/{builtin-keys.ts,visible-when.ts,validate.ts,form-errors.ts,keys.ts}`, tests `frontend/src/lib/forms/{visible-when,validate,form-errors}.test.ts`
- Modify: `frontend/src/types/registration.types.ts` (delete `CustomFieldDefinition`, `FieldValidationConfig`, `BuiltInFieldConfig`; `RegistrationForm` → `form_schema`, `version_id`, `version_number`, `stale_registrations?`; `Registration` → `answers: Record<string, unknown>`, `form_version_id`, `form_version_stale`, drop the seven legacy fields; `RegistrationCreateInput/UpdateInput` → `RegistrationSubmitInput { form_version_id: number; answers: Record<string, unknown> }`), `frontend/src/types/balancer-admin.types.ts:332-395,476-574` (`AdminRegistrationForm(Upsert)` → `form_schema`; `AdminRegistration` → `answers`; `AdminRegistrationCreate/UpdateInput` → `answers`), `frontend/src/services/registration.service.ts`, `frontend/src/services/balancer-admin.service.ts`, `frontend/src/i18n/messages/{ru,en}.json` (namespace `forms`), `frontend/src/i18n/zone-namespaces.json` (`forms` in `web` and `admin`)

**Interfaces:**
```ts
// types/forms.types.ts
export type FieldKind = "builtin" | "text" | "textarea" | "number" | "select" | "multi_select" | "checkbox" | "url" | "date";
export type Visibility = "public" | "organizers";
export interface Condition { field: string; op: "eq" | "neq" | "in" | "truthy"; value?: unknown }
export interface FieldValidation { regex?: string | null; error_message?: string | null }
export interface FormField { key: string; kind: FieldKind; label?: string | null; help?: string | null; placeholder?: string | null; required: boolean; visibility: Visibility; options?: string[] | null; validation?: FieldValidation | null; params: Record<string, unknown>; show_in_draft: boolean; visible_when?: Condition | null }
export interface FormSection { key: string; title?: string | null; description?: string | null; fields: FormField[] }
export interface FormSchema { schema_version: 1; sections: FormSection[] }
export interface RolesParams { primary_required: boolean; additional_required: boolean; flex_allowed: boolean; flex_mode: "optional" | "all_roles" | "forced"; subroles: Record<string, string[]>; top_heroes: { enabled: boolean; required: boolean; max: number } }
export type Answers = Record<string, unknown>;
// lib/forms/builtin-keys.ts
export const IDENTITY_PROVIDERS = ["discord", "twitch", "boosty", "vk", "youtube"] as const;
export const BUILTIN_FIELD_KEYS = ["battle_tag", "smurf_tags", "roles", "stream_pov", "public_notes", "organizer_notes", ...IDENTITY_PROVIDERS.map(identityKey)] as const;
export function identityKey(p: string): string; export function identityProvider(key: string): string | null; export function isBuiltinKey(key: string): boolean;
// lib/forms/visible-when.ts
export function evaluateCondition(c: Condition, answers: Answers): boolean; export function visibleFields(schema: FormSchema, answers: Answers): FormField[];
// lib/forms/validate.ts — generic rules only (required, regex incl. DEFAULT_PATTERNS mirror, options, number/date shape)
export function validateAnswer(field: FormField, value: unknown, t: Translate): string | null;
// lib/forms/form-errors.ts
export interface FormErrors { fields: Record<string, string>; form: string | null; stale: boolean }
export function fieldErrorsFrom(error: unknown, t: Translate): FormErrors;   // ApiError.details[] → code table `forms.errors.<code>` with {field label?} params; unknown code → detail.msg; code "form_version_stale" → stale=true
```
Services: `registrationService.register(tournamentId, input: RegistrationSubmitInput)`, `.updateMyRegistration(tournamentId, input: RegistrationSubmitInput)`; new `registrationFormTemplatesService` (`list/create/update/remove/apply/saveFromForm`) in `services/registration-form-templates.service.ts`.

- [ ] **Step 1:** Tests: `visible-when.test.ts` mirrors the Python `test_evaluate_condition_ops`; `validate.test.ts` (required checkbox, default discord pattern, explicit error_message wins, select option); `form-errors.test.ts` (two field errors map to two labels; unknown code falls back to msg; 409 stale sets `stale`). Fixture the `ApiError` exactly like `registration-team-errors.test.ts` does.
- [ ] **Step 2:** Implement; `bun run typecheck` will now list every consumer of the deleted fields — that list is the worklist for Tasks 12–14. Commit only when the three test files pass: `feat(frontend): form schema types, generic validation and error mapping`

### Task 12: `SchemaForm`, generic renderers, builtin renderers, `RegistrationSchemaForm`

**Files:**
- Create: `frontend/src/components/forms/{types.ts,SchemaForm.tsx,GenericField.tsx,AnswerValue.tsx,SchemaForm.behavior.test.tsx}`, `frontend/src/components/registration/fields/{BattleTagField,SmurfTagsField,IdentityField,RolesField,StreamPovField,NotesField}.tsx`, `frontend/src/components/registration/registrationRenderers.ts`, `frontend/src/components/registration/RegistrationSchemaForm.tsx`
- Modify: `RegistrationWizard.tsx`, `TeamRegistrationWizard.tsx`, `InviteAcceptWizard.tsx`, `RoleStep.tsx` (props: `params: RolesParams`, `lockedRole`, `value: RoleInput[]`, `onChange`), `components/tournaments/*` admin editor callers of `UnifiedRegistrationForm` (graft `trace_calls UnifiedRegistrationForm`)
- Delete: `UnifiedRegistrationForm.tsx`, `AccountStep.tsx`, `DetailsStep.tsx`, `DetailsStep.behavior.test.tsx`, `CustomField.tsx`, `customFieldValue.tsx`, `validation.ts`, `validation.test.ts`, `StepIndicator.tsx` only if unused after the change

**Interfaces:**
```ts
// components/forms/types.ts
export interface FieldRendererContext { mode: "public" | "admin"; verifiedAccounts: SocialAccount[]; subroleCatalog: SubroleCatalog; heroes: Hero[]; lockedRole: RoleCode | null; t: Translate }
export interface FieldRendererProps { field: FormField; value: unknown; onChange: (value: unknown) => void; error: string | null; context: FieldRendererContext }
export type FieldRenderer = React.ComponentType<FieldRendererProps>;
export type RendererRegistry = Partial<Record<string, FieldRenderer>>;   // key = builtin key or kind
// components/forms/SchemaForm.tsx
export interface SchemaFormProps { schema: FormSchema; answers: Answers; onChange: (key: string, value: unknown) => void; renderers: RendererRegistry; context: FieldRendererContext;
  serverErrors: Record<string, string>; step: number; onStepChange: (i: number) => void; showErrors: boolean; readOnly?: boolean; footer: (state: { canGoBack: boolean; isLast: boolean; stepError: string | null }) => React.ReactNode }
export function schemaSteps(schema: FormSchema, answers: Answers): FormSection[];   // sections with ≥1 visible field; [] → [schema.sections[0]]
```
`RegistrationSchemaForm` props: `mode`, `form: RegistrationForm`, `initial?: Registration | AdminRegistration`, `userProfile`, `lockedRole`, `onSubmit(input: RegistrationSubmitInput & { admin?: AdminExtras })`, `onCancel`, `submitPending`, `hideTitle`. Builtin default answers in public mode: identities prefilled from `userProfile.social_accounts` per provider (once), `roles` from `createRoleSelections(params.flex_mode)` semantics moved into `RolesField`. On a submit error: `const e = fieldErrorsFrom(err, t); if (e.stale) { await queryClient.invalidateQueries(tournamentQueryKeys.registrationForm(...)); notify.error(t("forms.errors.form_version_stale")) } else setServerErrors(e.fields)` and jump to the first step containing an erroring field.

- [ ] **Step 1: Test** `SchemaForm.behavior.test.tsx`: (a) a section whose only field is hidden by `visible_when` is not a step; (b) toggling the controlling checkbox reveals the field; (c) `serverErrors={{ vk: "bad" }}` renders "bad" under the `vk` control with `aria-invalid`; (d) required custom field blocks Next only after an advance attempt (`showErrors`). Follow `RoleStep.behavior.test.tsx` conventions for rendering and i18n.
- [ ] **Step 2:** Implement `SchemaForm` (reducer-free; parent owns `answers`), `GenericField` (one component, `switch (field.kind)`; `date` is `<input type="date">`; `multi_select` = checkbox group), `AnswerValue`, the six builtin renderers wrapping the existing components (`SmurfTagsInput`, `VerifiedAccountSelect`, `AccountCombobox`, `RoleStep`), `registrationRenderers` (`{ battle_tag: BattleTagField, smurf_tags: ..., roles: RolesField, stream_pov: ..., public_notes: NotesField, organizer_notes: NotesField, identity_discord: IdentityField, ... }`), then `RegistrationSchemaForm` and rewire the three wizards and the admin editor. Public-mode required checks come from `validateAnswer`; role composition errors arrive from the server (no client copy).
- [ ] **Step 3:** Delete the files listed. `bun run typecheck && bun run test:vitest -- registration forms` → PASS. Commit — `feat(frontend): schema-driven registration form`

### Task 13: Builder as a schema editor, templates screen

**Files:**
- Modify: `frontend/src/components/balancer/form/RegistrationFormBuilder.tsx`, `frontend/src/app/admin/tournaments/[id]/registration/form/page.tsx`, `frontend/src/app/admin/tournaments/[id]/settings/useRegistrationFormSection.ts`, `frontend/src/components/admin/workspace-settings/sections.ts`
- Create: `frontend/src/components/balancer/form/_components/{SectionList.tsx,FieldEditor.tsx,RolesParamsEditor.tsx,AddFieldMenu.tsx,TemplateMenu.tsx}`, `frontend/src/app/admin/settings/registration-forms/page.tsx`, `frontend/src/components/balancer/form/RegistrationFormBuilder.behavior.test.tsx`
- Delete: `_components/{BuiltInFieldsCard.tsx,BuiltInFieldsCard.behavior.test.tsx,CustomFieldsCard.tsx,SubrolesTab.tsx,formConfig.ts}` (move `makeUniqueCustomFieldKey` → `lib/forms/keys.ts::makeUniqueFieldKey` first)

Builder state: `draft: FormSchema | null` (null = untouched, server's). Left rail = sections (`@dnd-kit/sortable`, add, rename, description, delete when empty). Main = fields of the selected section (sortable; drag across sections through the rail drop targets). `AddFieldMenu` lists remaining builtin keys (label by key from `registrationFormAdmin.builtins.<key>`; identity keys grouped) and the eight custom kinds. `FieldEditor`: label/help/placeholder (custom), required, visibility (disabled + explanatory hint when the builtin fixes it: `battle_tag`, `roles`, `stream_pov`, both notes), validation regex + error message (text/textarea/url/number/battle_tag/smurf_tags/identity_*), options list (select/multi_select), `visible_when` (select over earlier fields + op + value input typed by the target's kind), `show_in_draft` (custom only, disabled when `organizers`), `params` editor for `battle_tag`/`identity_*` (`require_verified`) and `roles` (`RolesParamsEditor`: primary/additional required, flex allowed, flex mode, subroles per role from `subrole_catalog` — the former `SubrolesTab` — top heroes enabled/required/max). Key of a custom field: `makeUniqueFieldKey(label, existing)` once, then locked (`keyLocked`). Preview tab: `<SchemaForm readOnly ... />` with `registrationRenderers`. Save: `upsertRegistrationForm({ ...toggles, form_schema: draft })`; after save show `stale_registrations` badge from the refetched form. `TemplateMenu`: load (list → confirm replaces the draft), save as (name prompt → `saveFromForm`). Workspace page `/admin/settings/registration-forms`: list, create (opens the same builder in schema-only mode), rename, delete.

- [ ] **Step 1: Test** — add a section, add a custom `select` field with two options, set `visible_when` to an earlier `stream_pov` builtin, save → the upsert body carries the expected `form_schema`; loading a template replaces the draft after confirm.
- [ ] **Step 2:** Implement; `bun run typecheck && bun run lint && bun run lint:zones`. Commit — `feat(admin): registration form builder edits the schema; workspace templates`

### Task 14: Remaining consumers — admin table, participants page, helpers, draft inspector

**Files (from `bun run typecheck` after Task 11; known today):** `components/balancer/registrations/RegistrationsTable.tsx:999-1088`, `_components/balancerRegistrationColumns.tsx:105-110,354-404,608-619`, `components/balancer/workspace-helpers.ts:224-229,525-533`, `balancer-page-helpers.ts:67-77`, `app/(site)/tournaments/[slug]/_views/TournamentParticipantsPage.tsx:826-880`, `TournamentOverviewPage.*`, `components/draft/PlayerInspector.tsx:89-93` (server now sends `public_notes` as `notes` — no change unless the field was renamed on `DraftPlayerRead`; keep `notes` on the wire there), `components/registration/MyTeamPanel.tsx` and any other `Registration` consumer, tests listed in the design §9, `app/(site)/docs/diagrams.ts:905-906` (ERD text)

- [ ] **Step 1:** Admin table: one column per schema field (`schema.fields()` minus `battle_tag`/`roles`, which keep their dedicated columns) rendering `<AnswerValue field value={registration.answers[field.key]} />`; search values from `answers`. Participants page: identity chips from `answers[identityKey(p)]` for public identity fields; `public_notes` block; `stream_pov` badge from `answers.stream_pov`. Helpers use `answers`.
- [ ] **Step 2:** `bun run typecheck && bun run lint && bun run lint:zones && bun run test:split && bun run test:vitest && bun run test:bun` → all PASS. Commit — `refactor(frontend): read registration answers through the schema`

---

## Phase E — cleanup and verification

### Task 15: Dead code, docs, full gates

- [ ] Delete anything Tasks 8/12/13 left behind: graft `find_all` for `built_in_fields|custom_fields_json|discord_nick|twitch_nick|boosty_nick|BuiltInFieldConfig|CustomFieldDefinition|UnifiedRegistrationForm|BUILT_IN_FIELDS|validateCurrentStep` across `backend/` and `frontend/src/` must return only the migration, `docs/`, and `EncounterReportForm` code.
- [ ] Docs: regenerate ERD and OpenAPI (`cd backend && uv run python scripts/export_erd.py && bash scripts/export_openapi_schemas.sh`); add a "Registration form schema" paragraph to `docs/architecture.md` pointing at `docs/registration-form-schema/design.md`; set this file's and `design.md`'s status line to `implemented (YYYY-MM-DD)`.
- [ ] Gates: `cd backend && uv run bash scripts/lint.sh && for s in shared tournament-service balancer-service app-service stream-service parser-service analytics-service identity-service discord-service; do uv run pytest $s/tests -q || exit 1; done && uv run pytest tests -q`; `cd frontend && bun run typecheck && bun run lint && bun run lint:zones && bun run test:split && bun run test:vitest && bun run test:bun`; gateway `cd gateway && go test ./...`.
- [ ] Browser smoke (dev stack up, `make migrate` applied): open the admin builder for a tournament in REGISTRATION → add a custom `select` and an `organizer_notes` builtin → save → public tournament page → register with the wizard (custom answer + organizer note) → participants list shows the select answer, not the organizer note → admin registrations table shows both → builder: change the select's options → save → admin form page shows "1 registration on an older version" → the player's "edit registration" submit with the cached form returns 409 and the wizard reloads the new schema. Record what was observed in the final report.
- [ ] Commit — `chore(registration): remove legacy form config code; docs`

---

## Self-review (run before handing off)

1. **Spec coverage** — §3 schema/catalog (Tasks 1–2), §5 pipeline/errors (3, 7, 8), §4 storage/versions (4–6), §6 frontend (11–14), §7 templates (10, 13), §8 migration (5), §9 tests (each task), identities (4, 5, 8, 9), notes split (4, 5, 8, 12, 14), visibility stripping (8, 14), `flex_allowed` (2, 5, 7, 11).
2. **Placeholders** — none; every step names files, symbols and commands.
3. **Type consistency** — `RegistrationSubmit{form_version_id, answers}` (backend) ↔ `RegistrationSubmitInput` (frontend); `form_schema`/`version_id`/`version_number`/`stale_registrations` on both reads; `answers`/`form_version_id`/`form_version_stale` on both registration reads; `FieldError.field` ↔ `ApiExc.field` ↔ `fieldErrorsFrom().fields`; `RolesParams` field names identical in Python and TS.
