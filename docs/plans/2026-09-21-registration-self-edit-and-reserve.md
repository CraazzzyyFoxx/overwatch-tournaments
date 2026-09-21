# Self-service registration editing + reserve (замена) opt-in

**Status:** implemented (2026-09-21). Migration `regres01` is the new head.

**Goal:** Two things a registrant cannot do today.
1. **Edit their own registration** after it was approved. The PATCH route exists (`rpc.tournament.reg_pub_update_me`) but
   `update_registration` refuses anything whose `status != "pending"`, and with `auto_approve` on — the common configuration — a
   submission is `approved` immediately, so self-edit is dead on arrival. There is also no UI entry point: `MyRegistrationCard`
   offers check-in and withdraw only. And the route has **no window check**, so a pending row can still be edited after
   registration closed.
2. **Declare themselves a reserve** — "I do not need a starter slot, call me if a replacement is needed." Nothing in the schema
   expresses player-side consent to be a sub.

**Architecture:** One server-owned edit policy (pure function, shipped in the read model, never re-derived by the client) plus one
new builtin boolean field `reserve` backed by a column, modelled exactly on `stream_pov`. No new state machine, no new endpoint.

---

## As built — where it differs from the plan above

1. **`roles` is floored on ANY team, not just a locked one.** On a team tournament the roster slot is the captain's decision, so
   a member changing their own roles is wrong whatever the team's status is — and the simpler rule needs no team-status
   vocabulary inside the policy module (which would have been an import cycle: `teams.py` → `service.py` → `self_edit.py`).
2. **The policy is an allowlist end to end.** `FormSchema.editable_keys()` (not `locked_keys()`), `SelfEditPolicy.writable_keys`,
   `RegistrationRead.edit_writable_keys`. "Answered" is computed by `self_edit._answered_keys`, which adds `battle_tag` and
   `roles` to `answer_service.answers_of` — they have storage of their own, and without them a frozen BattleTag would read as
   "never answered", hence writable, on every row ever made.
3. **`reserve` is published unconditionally** (`registration_build._ALWAYS_PUBLIC`). Its visibility is fixed public by the
   catalog, and the schedule imposes it on late sign-ups whether or not the form asks the question — resolving it from the
   schema alone would hide exactly the rows the reserve group exists to show.
4. **Lateness has its own predicate and its own SQL clause**: `shared.services.registration_window.is_registration_late` /
   `registration_late_clause`, wrapped by `windows.is_late_registration`, and read for the public form through
   `windows_service.load_registration_state` (one round trip, `(is_open, is_late)`).
5. **The self-edit audit row** is staged in `rpc/public_rpc.py::_reg_pub_update_me` as `registration.self_update` with the new
   `AuditSource` value `player`, from the VALIDATED document. `audit.profile_changes` gained an `answers["roles"]` branch
   (`_answer_roles`) projecting both sides to what an answer can express — without it a player's role change diffed as empty.
6. **The admin table filters client-side.** It already fetches the whole pool in one request and filters in the browser, so
   `reserve` / `not_reserve` ride the existing `inclusion` URL param next to `included`/`excluded`. The server's new
   `inclusion_filter` values exist and are tested, for any caller that wants server-side narrowing.
7. **Not verified in a browser**: the stack (Postgres, RabbitMQ, the services, Next) was not running in this environment. Proof
   is the backend unit suites and the component-level behavior tests listed under Verification, which mount the real dialog,
   the real participants page and the real builder.

---

## Part 1 — Self-edit with limits

### What decides: the schema says it, the system floors it

Editability is a **property of the question**, declared in the form engine, exactly like `required`, `visibility` and
`show_in_draft`. `FormField` gains one flag:

```python
class FormField(BaseModel):
    ...
    #: May the REGISTRANT change this answer after submitting? The organizer's
    #: own edit is never gated by it. Default FALSE: a question is frozen at
    #: submit unless the organizer deliberately opens it.
    editable: bool = False
```

plus one reader beside `public_keys()`:

```python
def editable_keys(self) -> frozenset[str]:
    return frozenset(f.key for f in self.fields() if f.editable)
```

**Closed by default, and that makes the deploy a no-op.** Today self-edit is refused for every non-pending row, i.e. in practice
for everything (`auto_approve`). With `editable=False` as the default, every stored version — and every form an organizer never
re-opens — keeps exactly that behaviour: `can_edit` is false with reason `nothing_editable` until somebody ticks a box in the
builder. No data migration, no silent widening of what players may rewrite, and the feature ships dark.

It also does not churn versions: `form_service.apply_schema` re-validates the STORED document through `FormSchema` before
comparing canonical JSON, so an old document gains the default on both sides of the comparison and compares equal.

**Storage.** No column and no migration: the flag rides the schema document in
`balancer.registration_form_version.schema_json` (`mapped_column(JSON)`), which is append-only and already the only home of
`required` / `visibility` / `show_in_draft`. Old rows simply omit the key and pick up the default on read; new saves write it
explicitly (`model_dump(mode="json")` emits defaults). Templates carry it in their own `schema_json` and it survives
copy-on-apply. Known ceiling: `JSON`, not `JSONB`, and no GIN index, so "which forms in this workspace pinned `roles`" is a
Python scan over versions rather than a query — fine, because every read path loads one form by `tournament_id`.

**Which version governs an edit: the CURRENT one.** `reg_pub_update_me` already validates against
`_require_current_schema(form, body.form_version_id)` and refuses a stale `form_version_id` with `form_version_stale`, so
`self_edit_policy` reads `schema_from_form(form)`. `registration.form_version_id` stays what it is today — the "answers are
older than the questions" marker — and never decides permissions, or an organizer pinning a field would leave every existing
registrant editing it under their own older version.

Three rules the schema deliberately does **not** get to decide:

| Floor | Why the organizer cannot switch it off |
|---|---|
| `battle_tag` locked once `reviewed_at IS NOT NULL` | It is the row's identity anchor: partial unique index per tournament, `workspace_member` → `player_id` resolution, and every inherited rank layer reads through it. Renaming it post-review silently re-points all of that. |
| `roles` locked once the row is in the pool (`_common.is_included_in_balancer`) or its team is locked | The balancer / draft has already consumed them. Before that they are free, which is the point. |
| `reserve` locked on a LATE sign-up | See "Late sign-up ⇒ reserve" below: the flag was imposed by the schedule, so the registrant must not be able to untick their way into the main field. |

And one rule that goes the other way — a key the row has **never answered** is writable regardless of the flag. Otherwise a new
form version that adds a question leaves every existing registrant in a `form_version_stale` state they cannot clear, which with
a closed-by-default flag would be the normal case rather than an edge one.

Gate rules for the request as a whole stay as they were (nothing per-field about them):

| Rule | Why |
|---|---|
| Registration window must be open (`windows.is_registration_open`) | Same gate `submit_public_registration` uses. `allow_late_registration` lifts it for free. |
| `status ∈ {pending, approved}` | Widening from pending-only is the point of this plan. `withdrawn` / `rejected` / `banned` / custom / `deleted_at IS NOT NULL` stay refused — a rejected row must not be edited back into shape. |
| `checked_in == false` | Check-in freezes the entry the organizer is about to balance. |
| every visible key locked | Then `can_edit` is false with reason `nothing_editable`. That is the whole-form kill switch, for free — no `allow_self_edit` column on `registration_form`. |

### Where it lives

New pure module `backend/tournament-service/src/services/registration/self_edit.py`:

```python
@dataclass(frozen=True, slots=True)
class SelfEditPolicy:
    can_edit: bool
    reason: str | None       # "window_closed" | "status_locked" | "checked_in" | "nothing_editable"
    writable_keys: frozenset[str]

def self_edit_policy(registration, tournament, schema, *, now=None) -> SelfEditPolicy:
    """writable = (schema.editable_keys() | keys this row has never answered) - system_floor(registration)"""
```

An **allowlist**, not a denylist — that is what "closed by default" means mechanically, and it is also the safe direction for a
form version whose questions this server does not recognise yet.

Pure and session-free for the same reason `is_registration_open` is: it has to be callable from the read path (per row, no I/O)
and from the write path. `registration_team` is already eager-loaded by `registration_read_loaders()` and the stored answers come
from `answer_service.answers_of`, so neither clause costs a query.

**Write path** — `service.RegistrationService.update_registration` (`service.py:621`): replace the `status != "pending"`
check with the policy.

- `not can_edit` → `409` with `detail=reason`.
- `values.keys() - writable_keys` → `raise_field_errors([FieldError(key, ErrorCode.LOCKED, …)])`, so the message lands under the
  offending control through the existing `fieldErrorsFrom` plumbing instead of as an opaque toast.

**Window check** also lands here (it is missing today), so it holds for the RPC route and any future caller.

**Read path** — `RegistrationRead` gains three fields, filled only on the `reg_pub_*_me` paths (same rule as `queue_*`):
`can_edit: bool`, `edit_locked_reason: str | None`, `edit_writable_keys: list[str]`. The client must not re-derive this — same
reason the admission chips are computed server-side: three consumers would grow three different answers to "may I edit".

**Audit.** `services/registration/audit.py` is wired into the admin RPC only, so a self-edit currently leaves no trail. With
approved rows editable, a player changing roles after approval must be visible to organizers: stage one `record_audit` row on the
self-edit path with the registrant as actor, reusing `audit.profile_changes` / `role_snapshot` so the feed entry is shaped like
the admin edit it sits next to.

### Frontend — the builder (organizer side)

`editable` is one more per-field toggle, following `show_in_draft` line for line — worded as an opt-in ("Разрешить менять после
отправки"), because that is what it is:

- `types/forms.types.ts` — `editable?: boolean` on `FormField`. **Optional**, unlike `show_in_draft`: the server always sends it
  (Pydantic dumps defaults), and `field.editable === true` reads the same while leaving ~15 existing test fixtures untouched.
  Optional-plus-closed-default is also the fail-safe direction: a fixture or payload missing the key reads as locked.
- `FieldEditor.tsx` — a `SwitchRow` next to `showInDraft`: label + hint. On `battle_tag` / `roles` the hint also names the floor
  ("после проверки / после добавления в пул поле всё равно закрывается"), same shape as `showInDraftBlocked` — stated, not
  silently overridden, because opening those two still leaves the floor in force.
- `_components/schemaEdits.ts::sanitizeSchema` — normalize the flag (`field.editable === true`) the way it already normalizes
  `show_in_draft`, so a hand-edited or imported schema cannot reach the save with `undefined`.
- `AddFieldMenu.tsx::newBuiltinField` / `newCustomField` and `lib/forms/default-schema.ts` — `editable: false`, matching the
  server default so a freshly added question is frozen until the organizer says otherwise.
- i18n `en` + `ru`: `registrationFormAdmin.fieldEditor.editable` / `editableHint` / `editableFloorHint`
  (`RegistrationFormBuilder.i18n.test.tsx` enforces the pair).
- Templates need nothing: `RegistrationFormTemplate` stores the same `FormSchema`, so the flag travels with a copy-on-apply.

### Frontend — the registrant side

- `MyRegistrationCard` (`TournamentParticipantsPage.tsx:335`) gets an **Edit** action, enabled from `registration.can_edit`,
  with `edit_locked_reason` as the disabled tooltip. With the closed default this button is absent on every existing tournament
  until an organizer opens a question — intended.
- New `MyRegistrationEditDialog.tsx`: `RegistrationSchemaForm` in `mode="public"` with `initial={registration}` +
  `registrationService.updateMyRegistration`, invalidating `tournamentQueryKeys.registration` / `registrationsList`.
- `RegistrationSchemaForm` gains `writableKeys?: readonly string[]` (fed from `edit_writable_keys`, **not** from
  `field.editable` — the server's answer already folds in the floor, the late-reserve lock and the never-answered exception),
  threaded to `FormField` → renderer `disabled` with a hint. A step with no writable field is skipped in the wizard's step list.
- Free reuse: `form_version_stale` already exists on the read model. The same dialog is the "the organizer added questions,
  answer them" path, which today has no UI at all.

## Part 2 — Reserve

### Shape: a builtin boolean, like `stream_pov`

`reserve` is a **player-declared** flag, stored in its own column.

Rejected alternatives:
- **Custom `checkbox` question.** Works today with zero code — and the answer lands in `custom_fields_json`, where no SQL
  predicate, no list split and no organizer filter can see it. The flag has to be queryable.
- **A custom balancer status `reserve` (`excludes_from_balancer`).** Already possible, and it is the *organizer's* decision about
  pool membership. It cannot express consent, and promoting a reserve requires knowing who agreed to be one.
- **Reuse `is_substitute`.** That is a team roster bench slot, captain-assigned, exported as `Player.is_substitution`. Different
  subject, and it would collide on team tournaments.

### Backend touchpoints

1. **Migration** `backend/migrations/versions/regres01_registration_reserve.py` (`down_revision = "chat01"`):
   `balancer.registration.is_reserve BOOLEAN NOT NULL DEFAULT false`. No index — the participants list already scans every row of
   the tournament and the admin filter rides the same scan. Add a partial index only if a field size ever makes it measurable.
2. `shared/models/registration/registration.py` — `BalancerRegistration.is_reserve`.
3. `shared/domain/forms/builtins.py` — `_STATIC["reserve"] = BuiltinSpec("reserve", "public", None)`. Public visibility is fixed:
   a reserve who is hidden from the roster cannot be found when a replacement is needed.
4. `shared/domain/forms/validate.py` — `_BOOL_KEYS = frozenset({"stream_pov", "reserve"})`.
5. `services/registration/answers.py` — `_ANSWER_COLUMNS["reserve"] = "is_reserve"`, and the `apply` coercion
   `bool(value) if column == "stream_pov"` becomes a `_BOOL_COLUMNS` membership test. `answers_of` then projects it for free.
6. `services/registration/audit.py` — `_ANSWER_FIELDS["reserve"] = "is_reserve"`.
7. `domain/registration/mapping_catalog.py` — one builtin spec next to `stream_pov`, so sheet import can map a reserve column.

### Pool behaviour: one guard, not a new rule

Reading the write paths: entry into the balancer pool is **always** an explicit organizer action —
`add_to_balancer`, `bulk_add_to_balancer`, `_reg_include_balancer`, or rank autofill with `will_add_to_balancer`.
`approve_registration` deliberately leaves `not_in_balancer`, and `sync_included_balancer_status` only moves `ready ↔ incomplete`
for rows already in. So a reserve stays out of the pool with **no change at all**, and the organizer adding them *is* the
"замена нужна" action.

The one thing that would break: the **bulk** sweeps would hoover reserves into the pool. Guard exactly those two —
`lifecycle.bulk_add_to_balancer` and the rank-autofill `will_add_to_balancer` sweep skip `is_reserve` rows. Single-row add stays
an unconditional override, because an organizer clicking one name means it.

### Late sign-up ⇒ reserve, automatically

A sign-up that lands **after the REGISTRATION window's `ends_at`** is a reserve, whatever the registrant ticked. No new organizer
toggle: `Tournament.allow_late_registration` is *already* the switch that admits these people, and "you are in, as cover" is the
honest meaning of it. With the flag off there are no late sign-ups to classify.

**One new predicate**, beside the one that already answers the openness question — `shared/services/registration_window.py`:

```python
def is_registration_late(status, schedule, now=None) -> bool:
    """Inside the window only thanks to ``allow_late_registration``: the REGISTRATION
    row exists, has started, has an ``ends_at``, and ``now`` is past it."""
```

plus `registration_late_clause()` mirroring it in SQL, for the same reason `registration_open_clause` exists — and
`windows.is_late_registration(tournament)` as the `Tournament`-taking wrapper next to `is_registration_open`. It is deliberately
NOT `not is_registration_open(...)`: closed is closed, late is open-by-override, and a window with no `ends_at` is never late.

**Write path.** `submit_public_registration` already holds the `tournament` and calls `is_registration_open`; it computes `late`
from the same object and passes `reserve=late` to `create_registration`, which sets `registration.is_reserve = True` **after**
`answer_service.apply` — so the schedule overrides the checkbox rather than racing it. That is also the method that already owns
"the gate, the review state and the enrolment", which is exactly this kind of decision.

Two deliberate exclusions:
- **Team placements.** When `team_placement` is not `None` the rule does not fire: on a team tournament the bench is
  `is_substitute`, assigned by the captain, and a starter carrying `is_reserve` would mean two different things at once.
- **Admin-created rows.** `create_manual_registration` is untouched: an organizer entering somebody by hand after the deadline
  has already decided what they are.

**Edit path.** `reserve` joins the system floor for a row whose `submitted_at` is past the window's `ends_at` — recomputed, not
stored, so no column and no backfill. Without it, opening `reserve` for editing would hand every latecomer a one-click promotion
into the main field.

**Told before submitting, not after.** `RegistrationFormRead` gains `registration_late: bool`, resolved in `_reg_pub_form`
alongside `is_open` — one `sa.select(registration_open_clause(), registration_late_clause())`, same round trip. The wizard then
renders the reserve switch forced on and disabled with "приём заявок закрыт — вы регистрируетесь в резерв", and
`MyRegistrationCard` says the same on the row afterwards. A player who discovers this only after submitting will read it as a bug.

### Read models and surfaces

- `answers["reserve"]` rides the public list already (fixed public visibility, existing `public_keys()` filter).
- `RegistrationListResponse` gains `reserve_count: int`, counted in Python where `_role_counts` already runs.
  `total` and `role_counts` stay **all live rows**: `total` is the queue denominator (`queue_position` counts the same rows in
  SQL) and `Tournament.registrations_count` is cached separately — two numbers disagreeing is worse than one extra number. The
  capacity line subtracts `reserve_count` client-side.
- Participants list: reserves render as their own group (`VirtualParticipantsList` / `ParticipantsPool`) off the row's own
  `answers.reserve`; overview registration card shows `N участников (+M резерв)`.
- Admin registrations table: reserve badge + a `reserve` / `not_reserve` clause on the existing `inclusion_filter` matrix in
  `lifecycle.list_registrations`. Without a filter, "who agreed to sub in" is unanswerable at 200 rows.
- **Check-in is unchanged and correct**: `assert_admitted_at(stage=check_in)` blocks on `blockers` only (profile / subscription);
  pool membership is a `decision`, not a blocker. A reserve can check in — which is exactly how they signal "I am here today".
- Exports are unchanged: reserves are `not_in_balancer`, so `team_export` / roster reads already skip them.

### Frontend touchpoints

- `lib/forms/builtin-keys.ts` — `BUILTIN_FIELD_KEYS` + `FIXED_VISIBILITY["reserve"] = "public"`. The builder palette
  (`AddFieldMenu`) picks it up from that list; `RegistrationFormBuilder.i18n.test.tsx` will demand the label keys.
- `components/registration/fields/StreamPovField.tsx` → generalize to `SwitchField.tsx` with a per-key fallback label/help map
  (`stream_pov`, `reserve`); register `reserve: SwitchField` in `registrationRenderers.ts`. The component is already generic apart
  from two i18n fallbacks.
- i18n `en` + `ru`: `registration.details.reserve` / `reserveLabel`, `registrationFormAdmin.builtins.reserve`.

## Verification

- `shared/tests/test_form_schema.py`: `editable` defaults to **False**; a stored document that omits it round-trips to the same
  `canonical_json()` as one carrying the default (i.e. deploying this does NOT append a version to every existing form);
  `editable_keys()` reports exactly the opened fields.
- `shared/tests/test_registration_window.py`: a window with `ends_at` in the past and `allow_late_registration` on is
  simultaneously **open** and **late**; the same window with the flag off is neither; a window with `ends_at IS NULL` is never
  late; a window that has not started is never late; the Python predicate and `registration_late_clause()` agree on all four.
- `test_registration_self_edit.py`: a field the organizer opened edits successfully inside the window; an unopened field → field
  error under that key; an unopened field the row has never answered IS writable; a form with nothing opened → 409
  `nothing_editable`; window closed → 409 `window_closed`; `battle_tag` after review and `roles` once pooled → field errors even
  with `editable: true`; withdrawn → refused; a self-edit leaves one audit row.
- `test_registration_reserve.py`: `reserve: true` under `auto_approve` still lands `not_in_balancer`; `bulk_add_to_balancer`
  skips it while single-row `add_to_balancer` promotes it; `answers_of` round-trips the flag; public list reports `reserve_count`
  without moving `total`; **a sign-up past `ends_at` under `allow_late_registration` lands `is_reserve=True` even when the answer
  said false, an on-time one does not, a late `team_placement` acceptance does not, and the late row cannot untick `reserve`
  through the self-edit path even with the field opened.**
- Frontend behavior tests: edit button absent while nothing is opened and disabled-with-reason when the server says so; a
  non-writable key renders disabled; the builder offers the reserve builtin and its editable toggle; the wizard shows the reserve
  switch forced on when `registration_late` is true.
- Smoke: open one question → register → edit it → observe the changed answer and the audit row; move the window's `ends_at` into
  the past with late registration on → register → confirm the row is reserve, sits outside the pool, and shows in the reserve
  group.
