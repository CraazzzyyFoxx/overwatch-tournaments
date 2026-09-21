# Registration form schema — one field model, versions, templates, identities
**Status:** implemented (2026-09-21)

Design produced against the shipped registration pipeline (`balancer.registration*`,
`tournament-service/src/services/registration/*`, `frontend/src/components/registration/*`).
Companion implementation plan: [`plan.md`](./plan.md). Agent launch prompt: [`agent-prompt.md`](./agent-prompt.md).

## 1. Summary

**What.** Replace the two parallel field systems of the registration form — hard-coded built-in
fields (`built_in_fields_json`) and a thin custom-field list (`custom_fields_json`) — with one
ordered, sectioned `FormSchema`. The schema is versioned (append-only snapshots), reusable across
tournaments through workspace templates, carries per-field visibility, supports conditional
visibility, and is validated in exactly one place on the server with structured, localisable
errors. Social handles move out of per-provider columns into `balancer.registration_identity`.
Player notes split into `public_notes` and `organizer_notes`.

**Why.** Adding one built-in field today touches an ORM column, a Pydantic model, two validators
(Python and TypeScript, which have already drifted — default regexes exist only on the client),
a builder catalog, a wizard step and i18n. `stream_pov` is read by the wizard but absent from the
builder catalog, so it cannot be enabled. Form edits after registrations exist silently orphan
answers. Every answer — including free-text notes and any organizer-defined custom field — is
published on the anonymous roster. `EncounterReportForm` is a second copy of the same design.

**Decisions taken with the organizer (2026-09-20/21):**

| # | Question | Decision | Rejected alternative |
|---|---|---|---|
| 1 | Direction | **B — unified `FormSchema`** in `shared/domain/forms`, registration adopts it first | A — declarative registry over the existing two systems (no new field kinds, no templates, no versions). C — full form engine with cross-field logic (YAGNI) |
| 2 | Edits after registrations exist | **Append-only snapshot versions, no blocking.** Registration stores `form_version_id`; old answers render by their own version; admin sees a stale count | 409 on breaking edits (extra branch + dialog). Version counter without snapshot (history lost) |
| 3 | Templates | **Copy-on-apply, schema only.** `registration_form_template(workspace_id, name, schema_json)`; apply = upsert the tournament schema; no link afterwards | Template + toggles (team_* depend on `team_formation`). Reference with propagating edits (conflicts with versions) |
| 4 | Conditional visibility | **One condition per field**: `visible_when: {field, op: eq\|neq\|in\|truthy, value}`, target must be an earlier field | Boolean trees (AND/OR) |
| 5 | Roles fields | **`primary_role/additional_roles/flex_role/top_heroes` collapse into one builtin `roles`** with structured `params` | Four independent enabled/required flags with unreachable combinations |
| 6 | Social handles | **Table `balancer.registration_identity(provider, handle, handle_normalized)`**, one builtin kind `identity` keyed `identity_<provider>` | JSON map on the row (no constraints, no per-handle uniqueness path). Keeping per-provider columns |
| 7 | Notes | **Two builtin fields**: `public_notes` (player → everyone, fixed public) and `organizer_notes` (player → organizers, fixed organizers). Existing `admin_notes` (organizer → self) is unchanged and not a form field | Renaming `notes` only. Single `notes` with configurable visibility (cannot hold both a public and a private note) |
| 8 | Answer visibility | **`visibility: public \| organizers` on every field**; catalog fixes it for roster data (`battle_tag`, `roles`, `stream_pov`, both notes); public reads strip `organizers` answers | Keep everything public (PII on the anonymous roster) |
| 9 | Wire shape | **Flat `answers: dict[key, value]` + `form_version_id`** on submit/update, public and admin | Column-shaped body per built-in (per-field code on every layer) |
| 10 | Report form | **Not migrated now.** `FormSchema` lives in `shared` so `EncounterReportForm` can adopt it with its own builtin catalog later | Migrating both (doubles the blast radius) |

**Non-goals.** Migrating `EncounterReportForm`; notifying players whose registration is on a
stale version (badge only; the notification transport exists and is a follow-up); team-scoped
custom fields (rejected in the 2026-08-20 team-registration design §11); cap/waitlist; a
client-side draft autosave.

## 2. Grounded facts (verified against source, 2026-09-20/21)

- `BalancerRegistrationForm` (`shared/models/registration/registration.py:29-115`) is 1:1 with a
  tournament: ~20 flat toggles plus `built_in_fields_json: dict[key → BuiltInFieldConfig]` and
  `custom_fields_json: list[CustomFieldDefinition]`.
- Built-in keys are enumerated in four places: `frontend/.../formConfig.ts:37-129`
  (`BUILT_IN_FIELDS`, ten keys, **no `stream_pov`**), `validation.py:347-354`,
  `UnifiedRegistrationForm.tsx:223-238,374-501`, and as ORM columns. The wizard reads
  `built_in_fields.stream_pov` (L236) that the builder can never write.
- Default regexes live only on the client (`formConfig.ts:30-35`); the server checks only what
  the saved config carries (`validation.py:239-259`). Server errors are English strings
  (`_validation_error`, L207-210), first failure only.
- `RegistrationFormUpsert` is a full-replace body with comments about the "full-replace trap"
  (`schemas/registration.py:121-152`). No version concept anywhere.
- Custom field types: `text|number|select|checkbox|url`; answers stored as strings
  (`buildCustomFieldsPayload`, checkbox as `"true"`); `custom_fields_json: dict[str, Any]`.
- `notes` is deliberately public (`registration_build.py:248-251`) and reaches the draft
  inspector (`DraftPlayerRead.notes`). `_reg_to_read` strips nothing for anonymous callers.
- `discord_nick/twitch_nick/boosty_nick` have four real consumers, all "handle for provider X":
  `team_eligibility._identity_keys` (discord), `repository/stream.py::list_self_declared_channels`
  (SQL `twitch_nick IS NOT NULL` behind `stream_pov`), `registration/export.py::_registration_identity_handles`,
  `PlayerRoster` → `RosterEngine.full_export`. No cross-row query, no index.
- Readers of `built_in_fields_json` outside the validator: `shared/domain/roster.py::flex_role_mode`
  (27 callers route through it), `registration_build._resolve_top_heroes_config`,
  `lifecycle.py:256,404`, `validation.validate_verified_identity`, `serializers.serialize_registration_form`,
  `registration_build._form_to_read`, `_common.form_custom_field_defs`,
  `balancer-service/src/services/draft/board.py::visible_custom_fields`.
- Structured-error pattern already exists: `ApiHTTPException(detail=[ApiExc(msg, code)])`
  (`shared/core/errors.py:12-52`) → `ApiError.details[].code` → `lib/registration-team-errors.ts`
  → i18n. `ApiExc` has no `field`.
- `DraftPlayerCustomFieldRead.value: Any`; `full_export` passes `dict(roster.custom_fields)`.
  Typed answers are safe for backend consumers.
- `EncounterReportForm` (`shared/models/tournament/encounter_report.py:171-192`) repeats the
  `built_in_fields_json + custom_fields_json` pair with its own `_merge_defaults`/upsert.
- Migrations do not import `shared` (`roledps01`, `regteam0004` define helpers inline).
- `@dnd-kit/core|sortable|utilities` are already frontend dependencies.
- RBAC: form routes use resource `registration_form` with actions `read`/`update`
  (`rpc/registration_admin.py:263-296`).
- `SocialProvider` = `battlenet, discord, twitch, boosty, vk, youtube` (`shared/core/social.py:60-65`).
- Google-sheet feeds persist target keys in `registration_google_sheet_feed.mapping_config_json`
  (`registration.py:344`); `mapping_catalog._build_builtin_specs` names `discord_nick`, `twitch_nick`,
  `boosty_nick`, `admin_notes` as targets.

## 3. Schema model (`backend/shared/domain/forms/`)

Pure Pydantic + functions. No database access. Package layout:

| File | Responsibility |
|---|---|
| `schema.py` | `FormSchema`, `FormSection`, `FormField`, `FieldValidation`, `Condition`, invariants, `canonical_json`, `default_schema()`, `schema_from_form()` |
| `builtins.py` | The **only** list of builtin keys; per-builtin params models; fixed visibility; default patterns; identity key helpers |
| `validate.py` | `normalize_answers`, `visible_fields`, `evaluate_condition`, `FieldError`, `ErrorCode`, `raise_field_errors` |

```python
FieldKind = Literal["builtin", "text", "textarea", "number", "select", "multi_select", "checkbox", "url", "date"]
Visibility = Literal["public", "organizers"]
ConditionOp = Literal["eq", "neq", "in", "truthy"]
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

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
    label: str | None = None          # builtin: None (client localises by key); custom: required
    help: str | None = None
    placeholder: str | None = None
    required: bool = False
    visibility: Visibility = "public"
    options: list[str] | None = None  # select / multi_select only
    validation: FieldValidation | None = None
    params: dict[str, Any] = {}       # builtin only, validated by the catalog's params model
    show_in_draft: bool = False       # custom only
    visible_when: Condition | None = None

class FormSection(BaseModel):
    key: str
    title: str | None = None          # None → client localises by key (accounts/roles/details)
    description: str | None = None
    fields: list[FormField]

class FormSchema(BaseModel):
    schema_version: Literal[1] = 1    # format of the schema itself
    sections: list[FormSection]
```

**Builtin catalog** (`builtins.py`):

| key | storage | params model | fixed visibility |
|---|---|---|---|
| `battle_tag` | `registration.battle_tag` + `battle_tag_normalized` | `BattleTagParams(require_verified: bool=False)` | `public` |
| `smurf_tags` | `registration.smurf_tags_json: list[str]` | — | configurable |
| `identity_<provider>` (`discord`, `twitch`, `boosty`, `vk`, `youtube`) | `registration_identity` row | `IdentityParams(require_verified: bool=False)` | configurable |
| `roles` | `registration_role` + `registration_role_hero` | `RolesParams(primary_required=True, additional_required=False, flex_allowed=True, flex_mode: optional\|all_roles\|forced="optional", subroles: dict[role, list[slug]]={}, top_heroes: TopHeroesParams(enabled=False, required=False, max=5))` — `flex_allowed=False` is today's `flex_role.enabled=False` (an all-primary submission is refused) | `public` |
| `stream_pov` | `registration.stream_pov` | — | `public` |
| `public_notes` | `registration.public_notes` | — | `public` |
| `organizer_notes` | `registration.organizer_notes` | — | `organizers` |

`DEFAULT_PATTERNS` (applied when `field.validation.regex` is absent; today these live only in the
client): `battle_tag`/`smurf_tags` `([^#]{2,12}#[0-9]{4,})`, `identity_discord` `^[a-z0-9_.]{2,32}$`,
`identity_twitch` `^[a-zA-Z0-9_]{4,25}$`, `identity_boosty` `^[^#]{2,50}$`, kind `url` `^https?://.+$`.

**Invariants** (a `model_validator` on `FormSchema`; violations are `schema_invalid` 422s whose
`field` is the offending path such as `sections[1].fields[3].visible_when`):

1. Section keys unique and match `KEY_PATTERN`; at least one section (a section may be empty —
   the wizard skips it).
2. Field keys unique across the whole form and match `KEY_PATTERN`.
3. `kind == "builtin"` ⇒ key is a catalog key or `identity_<known provider>`; `params` validate
   against the catalog's params model; `visibility` equals the fixed one when the catalog fixes
   it; `options` is `None`; `show_in_draft` is `False`.
4. `kind != "builtin"` ⇒ `label` non-empty; key is not a builtin key and does not start with
   `identity_`; `params == {}`.
5. `select`/`multi_select` ⇒ `options` non-empty and unique; every other kind ⇒ `options is None`.
6. `visible_when.field` names a field that appears **earlier** in flattened order and is not the
   field itself. Ordering alone rules out cycles.
7. `show_in_draft` ⇒ `visibility == "public"`.

Helpers: `FormSchema.fields()` (flattened, in order), `.field(key)`, `.builtin(key)`,
`.public_keys() -> frozenset[str]`, `.canonical_json() -> str` (sorted keys, no whitespace; used
for version dedupe), `default_schema()` (today's default form: sections `accounts`
[`battle_tag`, `smurf_tags`, `identity_discord`, `identity_twitch`], `roles` [`roles`], `details`
[`public_notes`]), `schema_from_form(form) -> FormSchema | None` (reads
`form.current_version.schema_json`; `None` when the form or version is missing).

## 4. Storage and versions

```
balancer.registration_form                      -- toggles stay: auto_approve, require_open_profile, open_profile_scope,
                                                --   show_ranks, hide_registrations, max_participants, require_subscription,
                                                --   subscription_stage, subscription_scope, max_substitutes, team_*
  + current_version_id  FK registration_form_version.id  NULL   -- nullable on purpose: form↔version FKs form a cycle and NOT NULL is
                                                --   never deferrable in PG; the service creates form and version #1 together and
                                                --   readers treat NULL as "not configured"
  - built_in_fields_json, custom_fields_json    -- DROP after backfill

balancer.registration_form_version              -- NEW, append-only
  id, form_id FK registration_form CASCADE, number int, schema_json JSON NOT NULL,
  created_at timestamptz, created_by FK auth.user SET NULL
  UNIQUE (form_id, number)

balancer.registration_form_template             -- NEW
  id, workspace_id FK workspace CASCADE, name varchar(64), schema_json JSON NOT NULL,
  created_by FK auth.user SET NULL, created_at, updated_at
  UNIQUE (workspace_id, lower(name))

balancer.registration_identity                  -- NEW
  id, registration_id FK registration CASCADE, provider varchar(32), handle varchar(255),
  handle_normalized varchar(255), created_at, updated_at
  UNIQUE (registration_id, provider)
  INDEX  (provider, handle_normalized)

balancer.registration
  ~ notes → public_notes                        -- RENAME; semantics unchanged (public)
  + organizer_notes text NULL
  + form_version_id FK registration_form_version SET NULL, NULL
  - discord_nick, twitch_nick, boosty_nick      -- DROP after backfill
  (admin_notes, custom_fields_json, smurf_tags_json, stream_pov, battle_tag* unchanged)
```

ORM names follow the package: `BalancerRegistrationFormVersion`, `BalancerRegistrationFormTemplate`,
`BalancerRegistrationIdentity`. `BalancerRegistrationForm.current_version` and
`BalancerRegistration.identities` / `.form_version` are relationships that must be eager-loaded
(same standing rule as `roles`); `shared/services/roster.py::registration_load_options()` adds
`selectinload(identities)` and `selectinload(form_version)`.

Rules:

- **Upsert** compares `canonical_json` of the incoming schema with the current version. Different
  → insert `number + 1`, move `current_version_id`. Same → toggles update, version unchanged.
- **Submit** carries `form_version_id`. The server always validates against the **current**
  version; `form_version_id != current` → `409 form_version_stale`; the stored registration gets
  `form_version_id = current`.
- **Update** (player or admin) validates against the current version and moves the registration's
  `form_version_id` to it.
- **Read** of a registration renders its answers against **its** version (public-key set and field
  definitions come from `registration.form_version`, falling back to the form's current version
  when `form_version_id` is NULL — legacy/manual rows).
- **Stale badge**: `count(*) FROM registration WHERE tournament_id = ? AND deleted_at IS NULL AND
  form_version_id IS DISTINCT FROM current_version_id` on the admin form read.
- **Typed answers** in `custom_fields_json`: `number → int|float`, `checkbox → bool`,
  `multi_select → list[str]`, `date → "YYYY-MM-DD"`, everything else `str`. Normalisation happens
  in one place (§5); sheet sync goes through it too.
- `ponytail:` version rows are never pruned; add retention if a form is edited thousands of times.

## 5. Validation, errors, write path

**Wire.**

```python
class RegistrationSubmit(BaseModel):
    form_version_id: int
    answers: dict[str, Any]     # {"battle_tag": "...", "identity_discord": "...", "roles": [...], "vk": "...", ...}

class RegistrationUpdate(BaseModel):       # partial: only the keys present are validated/written
    form_version_id: int
    answers: dict[str, Any]
```

Admin create/update requests carry the same `answers` plus admin-only fields (`display_name`,
`status`, `balancer_status`, `admin_notes`, `exclude_reason`, role rows with ranks) which are not
questions to the player and stay outside the schema. Sheet sync builds `answers` from the parsed
row. The public list read returns `RegistrationRead.answers` (public keys only) beside the
top-level `battle_tag` and `roles`; `smurf_tags_json`, `discord_nick`, `twitch_nick`, `boosty_nick`,
`stream_pov`, `notes`, `custom_fields_json` leave the read model.

**Pipeline** — `shared/domain/forms/validate.py` (pure), plugins in tournament-service:

1. `visible_fields(schema, answers)` evaluates `visible_when` against the raw answers. A hidden
   field is neither required nor stored: its answer is dropped.
2. `normalize_answers(schema, answers, *, partial=False, enforce_required=True) -> NormalizedAnswers(values, errors)`
   coerces per kind and collects **every** error: `required`, type (`number`, `checkbox` — a
   required checkbox must be `True`, `multi_select ⊆ options`, `select ∈ options`, `date` ISO,
   `url`), `regex` fullmatch (explicit or `DEFAULT_PATTERNS`), `identity_*` → `normalize_social_handle`
   then pattern, `battle_tag` → canonical form for the pattern check, `smurf_tags` → list of
   tags, `roles` → structurally a list of `{role, subrole?, is_primary, top_heroes?}` (rules in
   step 3), unknown keys → `unknown_field`.
3. tournament-service plugins with dependencies: `roles_rules.validate_roles(field, roles, *, subrole_catalog, hero_catalog) -> list[FieldError]`
   (the current rules from `validation.py:89-177,378-430`, unchanged in behaviour) and
   `require_verified` → async check against `SocialAccount(provider)` → `not_verified`.
4. Errors → `ApiHTTPException(422, [ApiExc(msg, code, field)])`. `ApiExc.field: str | None = None`
   is the single change to `shared/core/errors.py`, backward compatible.

**Codes** (stable; `msg` is an English fallback): generic `required`, `invalid_format`,
`invalid_type`, `invalid_option`, `too_many`, `not_verified`, `unknown_field`; roles
`roles.primary_required`, `roles.additional_required`, `roles.flex_unavailable`,
`roles.one_priority_or_flex`, `roles.unknown_role`, `roles.subrole_not_allowed`,
`roles.too_many_heroes`, `roles.hero_wrong_class`; form `form_version_stale` (409),
`schema_invalid` (422 on upsert, `field` = schema path).

**Writer** — `RegistrationAnswerService.apply(registration, values, *, schema, hero_catalog)`:
builtins → columns / `identities` rows (upsert by provider, delete rows for providers no longer
in the schema or answered empty) / `roles` rows (**preserving `rank_value` on roles that remain**,
otherwise a player editing roles would erase organizer-set ranks) / custom → typed
`custom_fields_json`. Replaces `built_in_payload_values`, the ten-keyword `create_registration`
and the per-field branches in `lifecycle.update_registration_profile:355-368`.

**Read-side projection** — `answers_of(registration) -> dict[str, Any]`:
`{"smurf_tags", "stream_pov", "public_notes", "organizer_notes", identity_<provider>…, **custom_fields_json}`.
`_reg_to_read(..., public_keys: frozenset[str] | None)`: `None` = organizer context (everything);
public list and draft board pass the version's `public_keys()`. Anonymous-list caching stays valid:
the result is a pure function of `form_version_id`.

## 6. Frontend

Zone-neutral library `frontend/src/components/forms/` (web + admin; new i18n namespace `forms`
listed in both zones of `zone-namespaces.json`):

- `SchemaForm` — `schema`, `answers`, `onChange(key, value)`, `mode: "public" | "admin"`,
  `serverErrors: Record<string, string>`, `renderers`, `context` (verified accounts, subrole
  catalog, heroes, locked role). Sections → wizard steps; a section with no visible field is
  skipped (preserves today's "only steps with content"). `visible_when` evaluated client-side with
  the same semantics. Live validation of generic rules only (required/regex/options/max) — a thin
  mirror of §5 step 2, never builtin logic.
- `GenericField` renders `text/textarea/number/select/multi_select/checkbox/url/date`
  (`<input type="date">`). `AnswerValue` renders a stored answer by kind (`bool` → check, `list`
  → chips, `date` → locale) for the admin table, export views and the draft inspector.
- `lib/forms/form-errors.ts` — `fieldErrorsFrom(error): { fields: Record<string, string>; form: string | null; stale: boolean }`
  from `ApiError.details[].{field, code, params}` through a `code → i18n` table with `msg`
  fallback, modelled on `registration-team-errors.ts`.
- Builtin renderers in `components/registration/fields/`: `BattleTagField`, `SmurfTagsField`
  (wraps `SmurfTagsInput`), `IdentityField` (wraps `VerifiedAccountSelect`/`AccountCombobox`;
  prefill from `social_accounts` by provider — one loop instead of four copies), `RolesField`
  (wraps the existing `RoleStep` + `role-step/*`; takes `lockedRole`), `StreamPovField`,
  `NotesField`. Registered in `registrationRenderers`.
- `UnifiedRegistrationForm.tsx` (878 lines) → `RegistrationSchemaForm.tsx` (≈150): `SchemaForm`
  plus, in admin mode, a trailing non-schema "Organizer" panel (account picker, statuses, ranks,
  `admin_notes`). State is `answers: Record<string, unknown>`. `RegistrationWizard`,
  `TeamRegistrationWizard`, `InviteAcceptWizard` keep their shells and pass `form.form_schema` /
  `form.version_id`. A `form_version_stale` response refetches the form and re-renders.
- Deleted: `components/registration/validation.ts` builtin tables, `AccountStep.tsx`,
  `DetailsStep.tsx`, `CustomField.tsx`, `customFieldValue.tsx`, `formConfig.ts::BUILT_IN_FIELDS`
  and `DEFAULT_*_REGEX`, `BuiltInFieldsCard.tsx`, `CustomFieldsCard.tsx`, `validateCurrentStep`.
- **Builder** `RegistrationFormBuilder` becomes a schema editor: sections (add/rename/describe,
  dnd reorder), fields (dnd within and across sections), "add builtin" from a fixed client list
  of builtin keys (identity providers from `SocialProvider`), "add custom" by kind. Field editor:
  label/help/placeholder/required/visibility/validation/options/`visible_when` (earlier fields
  only)/`show_in_draft` (disabled when `organizers`). `SubrolesTab`, top-heroes and flex-mode
  become the `roles` params editor. **Preview** tab renders `SchemaForm` read-only. Buttons "Load
  template" / "Save as template". Custom keys derive from the label once, then lock
  (`MatchReportFormBuilder.keyLocked` pattern).
- Admin registrations table, participants page, draft inspector: columns and chips come from the
  schema (`answers[key]` + `AnswerValue`); the admin form page shows the stale-registrations badge.

## 7. Templates

RPC ops in tournament-service (`rpc/registration_admin.py`), workspace scope, permission
`registration_form` `read`/`update`: `regform_template_list`, `regform_template_create`,
`regform_template_update`, `regform_template_delete`, `regform_template_apply(tournament_id,
template_id)` (= schema upsert on the tournament form, so a new version by the common rule),
`regform_template_save_from_form(tournament_id, name)`. Gateway REST routes follow the existing
`registration_admin` routes; `backend/tests/test_rpc_route_parity.py` must stay green. Admin UI:
`registration-forms` section in `WORKSPACE_SETTINGS_SECTIONS` (group Competitive) with the same
builder in schema-only mode.

## 8. Migration `regform01_form_schema`

1. Create `registration_form_version`, `registration_form_template`, `registration_identity`.
2. Add `registration_form.current_version_id` (nullable), `registration.form_version_id`,
   `registration.organizer_notes`; rename `registration.notes → public_notes`.
3. Backfill with an **inline** converter (pure function in the migration module, covered by a
   golden test that loads the module by path): for every form, `built_in_fields_json +
   custom_fields_json → schema v1` with sections `accounts / roles / details` in today's field
   order, `visibility="public"` everywhere, `primary_role/additional_roles/flex_role/top_heroes →
   roles.params`, `*_nick → identity_*`, `notes → public_notes`; `INSERT version #1`; set
   `current_version_id`; set `form_version_id = #1` on every registration of that tournament;
   move `discord_nick/twitch_nick/boosty_nick → registration_identity` (`handle_normalized` =
   strip + casefold; the provider normaliser applies on the next write); rewrite target keys in
   `registration_google_sheet_feed.mapping_config_json` (`discord_nick → identity_discord`,
   `twitch_nick → identity_twitch`, `boosty_nick → identity_boosty`, `notes → public_notes`).
4. Drop `built_in_fields_json`, `custom_fields_json`, `discord_nick`, `twitch_nick`, `boosty_nick`.
   `current_version_id` stays nullable (see §4); after the backfill every existing form has one.

A tournament without a form row stays without a version ("not configured" in readiness).
Downgrade recreates the dropped columns and reverses the JSON/identity moves best-effort
(schema → legacy JSON for builtins present in the legacy catalog; custom kinds outside
`text|number|select|checkbox|url` become `text`).

## 9. Testing

- `shared/tests/test_form_schema.py`: invariants 1–7; normalize matrix per kind (coercion,
  required incl. required checkbox, options, regex, defaults, hidden field dropped and not
  required, unknown key, partial); `evaluate_condition` per op; `canonical_json` dedupe.
- Migration golden test (`backend/tests/test_regform01_convert.py`): today's default form and a
  form with every toggle → expected schema; nick rows; sheet mapping remap.
- tournament-service: `_form` SimpleNamespace fixtures (`test_registration_role_validation`,
  `test_registration_verified_identity`, `test_registration_rank_layers`, `test_forced_flex_roles`,
  `test_registration_write_path_fields`, `test_registration_audit`, …) move to a `schema_fixture()`
  helper; role rules produce codes with unchanged behaviour; `form_version_stale`; role update
  preserves `rank_value`; public read strips `organizers`, admin read does not; identity rows on
  create/update; version dedupe on upsert; stale count.
- shared/stream/balancer: `backend/tests/test_stream_repository.py` SQL assertion moves to the
  identity join; draft board reads `show_in_draft` through the current version;
  `test_owt_player_export` private block carries `identities` and `public_notes`.
- Frontend: `SchemaForm.behavior.test.tsx` (empty section skipped; `visible_when`; server field
  error lands on its field; stale → refetch), `form-errors.test.ts`, builder behaviour test (add
  section/field, roles params, apply template), `messages.parity.test.ts` picks up new keys.
- Browser smoke against the dev stack: public registration → admin edit → builder changes the
  schema → stale badge → the player's resubmit gets 409 and reloads.

## 10. Follow-ups (out of scope, recorded)

- `EncounterReportForm` adopts `FormSchema` with its own builtin catalog.
- Per-handle uniqueness per tournament (`registration_identity` partial unique) if organizers ask
  for "one Discord account per tournament" beyond the current team-level check.
- Notify registrations on a stale version through the existing notification transport.
