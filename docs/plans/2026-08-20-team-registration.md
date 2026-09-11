# Team-based registration — pre-formed teams register instead of players — design

Design produced against the shipped individual-registration pipeline
(`balancer.registration*`) and the two existing team-export paths
(`admin/balancer.py::export_balance`, `draft/export.py::export`).
Status: **design complete, peer-reviewed (3 rounds), APPROVED for implementation**
— conditional on the two release gates in §13. See §13 for the arbitration record.

## 1. Understanding summary

**What.** A per-tournament *team registration* mode. A captain creates a team,
fills typed `RosterShape` slots by inviting players, each invitee accepts and
supplies their own rank and OAuth-verified accounts, and an organizer then
explicitly materializes completed teams into `tournament.Team` +
`tournament.Player`. The balancer and the draft are not run at all for such a
tournament.

**Why.** Rosters that are decided outside the platform currently have to be
pushed through a free-agent pool and re-assembled by the balancer or a live
draft — a lossy, pointless round trip. There is today **no** notion of a team,
captain, group or invite anywhere in the registration slice.

**Who.** Captains and invited players (public surfaces), workspace
organizers/admins (moderation and materialization).

**Decisions taken with the organizer (2026-08-20):**

| # | Question | Decision | Rejected alternative |
|---|---|---|---|
| 1 | Intake model | **Teams only** — balancer and draft fully bypassed; `team_formation` gains a third value | Mixed pool (locked groups + free agents) — needs a "locked group" concept inside the balancer algorithm and `export.py`, plus top-up rules for short rosters. Grouping-only (`group_key` as a balancer soft constraint) — does not actually deliver pre-formed teams |
| 2 | Roster acquisition | **Hybrid** — captain drafts the roster, each member accepts an invite; the team is valid only once every slot is accepted | Captain types everything (`require_verified` becomes unenforceable for teammates, no consent). Pure invite-code self-registration (more steps, captain loses roster control) |
| 3 | Invite addressing | **Both** — one invite entity with a targeted `auth_user` mode (in-app) *and* a revocable expiring token link for people not yet on the site | Site-account-only (cannot invite a newcomer). Token-only (no in-app inbox, link leakage is the only path) |
| 4 | Roster shape | **Strict `RosterShape`** for the active roster **plus configurable substitutes** | Shape-only, no substitutes (real tournaments carry a bench). Free size 2..12 (loses completeness validation and bracket invariants) |
| 5 | Role & rank ownership | **Captain fixes the slot; the member supplies rank + their own verified accounts on acceptance** | Member picks roles freely via the existing `RoleStep` (team can assemble mis-shaped, needs a renegotiation screen). Captain proposes + member may swap slots (needs slot-race logic) |
| 6 | Materialization | **Explicit organizer action**, idempotent by team name, linked via `exported_team_id` — same contract as `export_balance` | Automatic on last acceptance (any later roster edit becomes a destructive re-export, painful once a bracket exists). Team status machine + phase-transition hook (implicit trigger, hard to test) |
| 7 | Capacity | **No cap, no waitlist** — existing time gates only | `max_teams` + 409 (needs race handling and a "do incomplete teams hold a slot" answer). Cap + waitlist promotion (a whole new state class for a scenario that does not exist today) |
| 8 | Mode switch placement | **`Tournament.team_formation = 'registration'`** — single source of truth for "how teams form" | A new `RegistrationForm.registration_mode` (two fields answering overlapping questions, needs a cross-validator) |
| 9 | Registration activation | **Schedule-only.** The `REGISTRATION` phase row becomes required and is the sole switch; `RegistrationForm.is_open` and `Tournament.allow_late_registration` are **removed** | Status + phase window only (flips the default from closed to open). One boolean moved onto `Tournament` (still two concepts, merely co-located) |
| 10 | Team-name collisions | **`unique (tournament_id, lower(name)) WHERE deleted_at IS NULL`** | Auto-suffix at export ("Alpha (2)" surprises people in the bracket). Organizer resolves manually (silent-merge risk if the warning is missed) |
| 11 | Team-level data | **Name + optional logo only** (`Team.name`/`balancer_name`/`image_url` already exist) | A second `custom_fields` engine scoped to the team |
| 12 | Roster edits pre-export | **Symmetric** — captain kicks, member self-withdraws, captaincy transferable; a departing captain must transfer or disband | Revoke pending invites only, organizer kicks. Captain-only control |
| 13 | Public read surface | **A separate "Teams" view** beside participants, plus one meta column on the participants list | Flat list + column only (rosters read poorly). Collapsible grouping inside `VirtualParticipantsList` (requires reworking its flat count/`getItemKey` model — highest-risk item in the feature) |
| 14 | Export approach | **Reuse the export seam**, preceded by consolidating the duplicated writer into `shared` | Direct `Team`/`Player` INSERT (re-implements newcomer flags, member creation, role mapping; becomes a third writer). Seed a `DraftSession` and draft-export (fabricates a completed draft that never happened) |
| 15 | Service placement | **Domain + invites in tournament-service**; materialization via RPC into balancer-service, which stays the single writer | Whole feature in balancer-service (registration gates would be pulled across a service boundary) |
| 16 | Refactor scope | **Migrate all three export paths onto the shared core inside this feature** | Only the new path (temporarily three copies of the orchestration — the exact debt this decision exists to remove) |
| 17 | Invite delivery surface | **The existing per-user "Your Registration" card on the tournament page** (`TournamentParticipantsPage.tsx:406-461`) — the place the invitee already visits to register, already translated, already carries personal state. A full notification subsystem is explicitly deferred | A dedicated "my invites" page (nobody would visit it — there is no bell, inbox, `/me` route, or email/push transport anywhere in the product). Token-links-only (would abandon targeted invites entirely). Building notifications now (its own feature; would block this one) |
| 18 | Rank on a role-less roster | **Not collected.** In a `has_role_slots=false` team tournament rank is meaningless — people arrive as teams — so only the nominal slot/role is recorded and `Player.rank` is written as `0` | Asking for a rank anyway (an unanswerable question: ranks are keyed `tank\|dps\|support` and `REGISTRATION_ROLE_CODES` has no `flex`). Extending `REGISTRATION_ROLE_CODES` with `flex` (blast radius across the rank and balancer machinery, outside this feature) |

**Non-goals.** Mixed pools and balancer "keep together" constraints; a team cap
or waitlist; automatic materialization; collapsible team grouping inside the
virtualized participants list; team-scoped custom fields; roster edits *after*
materialization (organizers use existing admin tooling, as today).

## 2. Grounded facts (verified against source, this session)

- `BalancerRegistration` is strictly one row per player:
  `uq_balancer_registration_user (tournament_id, workspace_member_id)` and
  `uq_balancer_registration_tournament_tag_active (tournament_id,
  battle_tag_normalized)`, both `WHERE deleted_at IS NULL`
  (`shared/models/registration/registration.py:133-156`).
- Identity is anchored **only** on `workspace_member_id` → `WorkspaceMember.player_id`;
  the column is nullable by design for admin/sheet rows with no resolved player
  (`registration.py:158-166`).
- **No** team/captain/group/invite concept exists in the registration slice.
  `team_name|captain|invite_token|party|squad` returns nothing across
  `shared/models/registration/`, `tournament-service/src/services/registration/`
  and `schemas/registration*.py`. The `captain_*` RPCs in `public_rpc.py:184-455`
  are match reporting on already-formed teams.
- Both existing team-formation paths converge on **one** writer:
  `export_balance` (`admin/balancer.py:241`) and draft `export` (`draft/export.py:139`)
  each build `list[BalancerTeam]` and call
  `balancer-service/src/services/team.py::bulk_create_from_balancer`.
- That writer is the sole place that resolves battle tags to users, calls
  `get_or_create_workspace_member`, computes `is_newcomer`/`is_newcomer_role` via
  `shared/services/newcomer_status.py::load_prior_participation`, and maps a slot
  code to `HeroClass` (`team.py:26-44`, `162-196`).
- A **second, near-duplicate** implementation lives in
  `parser-service/src/services/team/flows.py:162-275`, flagged as temporary debt
  in `docs/tournament-service-write-path-inventory.md:31`. The two diverge
  materially:

  | | balancer-service | parser-service |
  |---|---|---|
  | Unresolvable battle tag | silently skips the player (`team.py:164-166`), captain → `captain_id=None` | aborts with 400 `not_found` (`flows.py:150-158`) |
  | WorkspaceMember | `get_or_create_workspace_member` | `resolve_workspace_member_ids` |
  | Transaction | commits internally (`team.py:198`) | flush only, caller commits |
  | Substitutes | omitted → server defaults | explicit `is_substitution=False, related_player_id=None` |

- Neither writer supports substitutes. `Team.avg_sr`/`total_sr` are
  `column_property` correlated subqueries filtered on
  `Player.is_substitution.is_(False)` (`team.py:106-121`), so excluding the bench
  is automatic.
- `Player.rank` is `Integer NOT NULL`; `Player.workspace_member_id` is NOT NULL.
- Both export paths are **destructive-then-idempotent**: prior
  `Standing`/`Player`/`Team` rows reachable via `exported_team_id` are deleted and
  re-created (`admin/balancer.py:228-234`, `draft/export.py:128-136`), then
  `exported_team_id` is backfilled by matching `Team.balancer_name`.
- Registration openness is today a conjunction across two owners
  (`services/registration/windows.py:32-55`):

  ```
  form.is_open  AND  not is_finished_for_status(status)
                AND ( (status == REGISTRATION AND is_within_phase_window(REGISTRATION, …))
                      OR tournament.allow_late_registration )
  ```

- `is_within_phase_window` returns **True when no schedule row exists**
  (`shared/core/tournament_state.py:154-156`), whereas `form.is_open` defaults to
  **false** (`registration.py:39`). Rolling back to `REGISTRATION` from
  `CHECK_IN`/`DRAFT`/`LIVE` is already legal (`tournament_state.py:22-38`).
- `get_registration_count_by_tournament` counts `deleted_at IS NULL AND status != 'withdrawn'`
  with no notion of a placeholder (`services/registration/service.py:609-614`); it
  feeds the public `registrations_count` (`services/tournament/flows.py:101-107`),
  whose cache invalidation is documented as firing on every registration write
  (`cache_invalidation.py:56`).
- Safe by construction: the balancer pool export and draft pool both filter
  `status == "approved"` (`registration/export.py:74-79`,
  `draft/lifecycle.py:712-714`).
- `RosterShape` is the single shape authority: `ROSTER_SLOT_CODES =
  ('tank','dps','support','flex')`, `DEFAULT_ROSTER_SLOTS = {tank:1, dps:2, support:2}`,
  `MIN_TEAM_SIZE=2`, `MAX_TEAM_SIZE=12`, `has_role_slots` false only when every
  slot is `flex`, and `resolve_roster_shape(tournament_slots, workspace_slots)`
  resolves override → workspace default → default (`shared/domain/roster_shape.py`).
- `REGISTRATION_ROLE_CODES` is `tank/dps/support` only — `flex` is a **slot** code,
  not a registration role, so `registration_role` rows cannot express a role-less
  roster's slot.
- `Tournament.roster_locked_by_draft` already exists as a write-path guard against
  changing the shape mid-draft (`frontend/src/types/tournament.types.ts:124-128`).
- Frontend registration is player-centric end to end: `RegistrationForm` →
  `UnifiedRegistrationForm` (3 conditional steps) → `RegistrationCreateInput` →
  `Registration` → flat `VirtualParticipantsList` keyed by `registration.id`.
  `Tournament.team_formation` (`'balancer'|'draft'`) is the only existing
  "how teams form" switch, edited in `TournamentSettingsTab.tsx:284-289` and
  `RulesStep.tsx:36-41`.
- `flexMode: 'forced'` already hides per-row priorities and must seed the reducer's
  **initial** state, per the load-bearing comment at
  `UnifiedRegistrationForm.tsx:133-141` — the seam a locked-slot mode extends.
- The admin `AuthUserSearchCombobox` is gated by `auth_user:read` via `rbacService`.

## 3. Data model

Two new tables in the `balancer` schema (where every registration sibling lives),
and **three nullable columns** on `balancer.registration`. No slot table: the
roster *is* the set of registrations.

### 3.1 `balancer.registration` — additive only

| Column | Type | Notes |
|---|---|---|
| `registration_team_id` | FK → `balancer.registration_team.id` `ON DELETE SET NULL`, nullable, indexed | `NULL` = not on a team, so existing rows need no backfill |
| `team_slot_code` | `String(16)` nullable | The captain-assigned slot. **Not derivable** from `registration_role`: `REGISTRATION_ROLE_CODES` has no `flex`, but `_resolve_hero_role` maps `'flex'` → `HeroClass.flex` |
| `is_substitute` | `Boolean` default `false` | Bench member |

Deliberately *not* done: making an unaccepted invite a registration row. It would
silently inflate `get_registration_count_by_tournament` — a user-visible count with
no compiler to catch the regression. A registration row keeps meaning
"a real person registered".

### 3.2 `balancer.registration_team`

`tournament_id` FK CASCADE, indexed · `workspace_id` FK CASCADE, indexed ·
`name` `String(255)` · `name_normalized` `String(255)` (mirrors the
`battle_tag_normalized` convention) · `image_url` nullable ·
`captain_registration_id` FK → `balancer.registration.id` SET NULL ·
`status` `String(16)` default `'forming'` (`forming|complete|rejected|disbanded`) ·
`exported_team_id` FK → `tournament.team.id` SET NULL, indexed ·
`exported_at` · `export_status` · `deleted_at`/`deleted_by`.

Indexes:
- `unique (tournament_id, name_normalized) WHERE deleted_at IS NULL` — mirrors the
  export dedup rule, making a silent roster merge structurally impossible
- `(tournament_id, status) WHERE deleted_at IS NULL`

### 3.3 `balancer.registration_team_invite`

`team_id` FK CASCADE, indexed · `slot_code` `String(16)` · `is_substitute` `Boolean` ·
`target_auth_user_id` FK → `auth.user.id` SET NULL, nullable ·
`token_sha256` `String(64)` nullable · `expires_at` ·
`state` `String(16)` (`pending|accepted|revoked|expired`) · `invited_by` ·
`accepted_registration_id` FK SET NULL · `invited_at`/`accepted_at`.

- `unique (token_sha256) WHERE token_sha256 IS NOT NULL`
- `(team_id, state)`

**Token handling** (hardened after review — an earlier draft stored a raw
`token String(64)` with unspecified entropy). Redeeming this token creates a
registration bound to the redeemer's account inside a third party's roster and
consumes a shape slot, so it is a capability secret, not a room address. It must
match the repo's capability tier, not the scrim-room tier:

| Concern | Requirement | In-repo precedent |
|---|---|---|
| Entropy | `secrets.token_urlsafe(32)` (≥128-bit) | `ApiKey` uses `secrets.token_hex(32)` (`identity-service/src/services/api_key_service.py:258-259`) |
| At rest | store `sha256` only; the raw token is returned once, at creation | `ApiKey.secret_hash` (`shared/models/identity/api_key.py:30`), `code_sha256` (`shared/subscriptions/challenge_code.py:36-37`), OAuth state (`oauth_flows.py:187-188`) |
| Comparison | `hmac.compare_digest` | `oauth_flows.py:187-188`, pinned by `tests/test_oauth_state.py:93-105` |
| Expiry | folded **into** the guarded UPDATE (`… AND state='pending' AND expires_at > now()`), never checked separately | otherwise an expired token stays redeemable through the very race §8 exists to close |

`secrets.token_urlsafe(12)` stored raw (`shared/models/tournament/scrim.py:55-58`)
is explicitly **not** the bar to match: a scrim token only addresses a room.

Team completeness = group the team's registrations by `team_slot_code` and compare
to the resolved `RosterShape`.

## 4. Lifecycle and RPC surface

Naming follows the existing split — public `rpc.tournament.reg_pub_*`, admin
`rpc.tournament.reg_*`.

**Public (captain):** `regteam_pub_create` (team **and** the captain's own
registration in one transaction — the captain occupies a slot),
`regteam_pub_invite`, `regteam_pub_revoke_invite`, `regteam_pub_kick`,
`regteam_pub_transfer_captain`, `regteam_pub_disband`.

**Public (invitee):** `regteam_pub_accept` (targeted or token),
`regteam_pub_decline`. Leaving reuses the existing `reg_pub_withdraw_me`, which
additionally releases the slot.

**Public (read):** `regteam_pub_list`, `regteam_pub_get_me`.

**Admin:** `regteam_list`, `regteam_reject`.
**Materialization:** `rpc.balancer.teams.export_registered`.

### 4.1 Gate composition

`regteam_pub_create` and `regteam_pub_accept` are the only write paths that admit
a *person*, so both run the full existing stack, in order:

1. registration window (new schedule-only gate, §6)
2. `self_register` capability (`service.py:478-483`)
3. `assert_subscription_allows_registration`
4. `validate_registration_input`
5. `validate_verified_identity`
6. duplicate defence via `uq_balancer_registration_user` → `IntegrityError` → 409

`accept` delegates to the existing `create_registration`, so nothing is
reimplemented — the gates, the race defence and `assign_workspace_system_role` are
inherited. `accept` adds only: invite is `pending` and unexpired, the slot is still
unfilled against `RosterShape`, and `exported_team_id IS NULL`.

### 4.2 Mutation gates

Invite/kick/transfer/disband require the caller to be the team's captain and
require `exported_team_id IS NULL` (409 afterwards). A departing captain must
transfer captaincy or disband — never a silent orphan.

### 4.3 Realtime

> **Corrected after review.** An earlier draft published team/invite writes on the
> workspace-gated `balancer` topic and treated that as sufficient. Two errors:
>
> 1. **Too broad.** That topic's ACL is `IsWorkspaceMember`, and *every* successful
>    registration creates a `workspace_member` row via `create_registration` →
>    `ensure_player_identity` → `get_or_create_workspace_member`
>    (`registration/service.py:279`). Membership is **workspace**-scoped, not
>    tournament-scoped, so the real audience is anyone who has ever registered for
>    any tournament in that workspace — far wider than "not spectator data" implies.
> 2. **Cannot reach the invitee.** A *pending* invitee has no registration, hence no
>    `workspace_member` row, hence cannot subscribe at all. The in-app notification
>    path would miss the one person it exists for.

Resolution, following the repo's established thin-signal convention
(`logs.updated`, `subscription.updated`, `map_veto.updated` — a nudge carrying no
record data, client refetches through an authorized read):

- Publish a thin `registration_team.updated` on the existing `balancer` topic
  carrying **only** `tournament_id` and `team_id` — no names, no invite targets, no
  roster composition. Authorized clients refetch via `regteam_pub_list`, which
  applies its own visibility rules.
- **Invite delivery is pull-based in v1.** A new `regteam_pub_my_invites` read,
  authorized by the caller's own `auth_user_id`, is the invitee's source of truth;
  the token link works without any subscription. No realtime push to non-members,
  and no new public topic.

## 5. Materialization — one service, two paths

`backend/shared/services/team_export/`.

The orchestration sequence is **already** duplicated between `export_balance` and
draft `export`; a third copy is unacceptable. A single
`TeamMaterializationService` owns it once:

```
_run(plan) →  guard: refuse if Standing rows exist for the tournament
           →  cleanup prior Standing/Player/Team by exported_team_id
           →  insert Teams + Players (consolidated writer, §5.1)
           →  backfill exported_team_id by matching Team.balancer_name
           →  plan.finalize(session)   # per-path: stamp + optional event
           →  single commit
```

**Failure contract — two transactions, mandatory** (added after review; this is a
data-loss hazard, not a nicety). Today `export_balance` deletes the prior
`Standing`/`Player`/`Team` rows with no intervening commit and documents that
"the failure path below commits too, so the final state is identical either way"
(`admin/balancer.py:229-237`); its `except` branch sets `export_status="failed"`
and calls `session.commit()` (`:263-267`), which **flushes those pending
DELETEs** — a failed re-export already leaves the tournament with its old teams
gone and no replacements. Moving the commit out of the writer (§5.1) makes the
uncommitted destructive set strictly larger, so "single commit" is not a
sufficient specification. Required:

1. On success: one commit, as above.
2. On failure: **`await session.rollback()` first** — discarding the deletes and
   the partial inserts — then open a *fresh, short* transaction that re-loads the
   stamp target and writes `export_status='failed'` + `export_error`, then commit
   that. Rolling back alone would lose the operator diagnostics
   `admin/balancer.py:265-266` provides today; committing alone destroys data.
3. The stale comment at `admin/balancer.py:235-237` becomes false and must be
   rewritten in the same change, not left to mislead the next reader.

**Eager-load plan — required, not optional** (added after review).
`materialize_from_registered_teams` traverses `registration_team → registration →
workspace_member` plus `registration.roles`, all `relationship()` attributes
carrying the standing instruction "Readers needing the domain player must
eager-load this relationship (selectinload / explicit join) — never rely on a lazy
load in async code" (`registration.py:200-202`). In async SQLAlchemy an
unspecified access pattern does not merely get slow, it raises `MissingGreenlet`.
The consolidated writer already batches for exactly this reason — its docstring
records the fix ("Previously this issued ~5 sequential queries per player … It now
front-loads a handful of batch queries", `services/team.py:53-59`). The
registration path must therefore front-load: one query for the teams, one
`selectinload` for their registrations joined to `workspace_member`, one for
`registration.roles`. The same requirement applies to `regteam_pub_list` and the
Teams view (§7) — "no virtualization" answers render cost, never query shape.

> **Corrected after review.** An earlier draft put "enqueue the downstream
> analytics event" in the shared core and claimed the registration path could
> reuse it. Both are false. `enqueue_balance_exported_event` is called from
> exactly one place — `admin/balancer.py:260` — and takes a
> `models.BalancerBalance`; draft export emits **nothing**. `BalanceExportedEvent`
> requires `balance_id` (`balancer.balance.id`), `algorithm`, `avg_sr_overall`,
> `sr_std_dev`, `sr_range` and per-player `discomfort`/`was_off_role`
> (`shared/schemas/events.py:315-331`) — a registered team has none of them and no
> balance row at all. Event emission therefore belongs to `plan.finalize`, not the
> core: the balance path keeps emitting `balance_exported`, the draft path keeps
> emitting nothing, and the registration path emits nothing in v1. Analytics
> balance snapshots are consequently **not** produced for registration-sourced
> teams — an explicit non-goal, not an oversight. Standings, encounters,
> achievements and the analytics reads that join `Team`/`Player` are unaffected,
> since they never read `analytics.balance_snapshot`.

Two public entry points:

- **`materialize_from_balancer_payload(session, tournament_id, teams, *, on_unresolved="skip")`**
  — identity by battle tag, lenient. Used by balance export and draft export,
  which keep only their own mapping concern (`_draft_to_balancer_payload` is
  already exactly that pure function).
- **`materialize_from_registered_teams(session, tournament_id)`** — identity
  pre-resolved via `workspace_member_id`, strict, substitutes supported. Reads
  `registration_team` rows with `status='complete' AND deleted_at IS NULL`.

The plan object carries what differs: the team list, the prior-export ids to clean,
and a `finalize` callback that stamps its own row (a `balance`, a `draft_session`,
or a `registration_team`) and emits that path's event, if any.

**Bonus correctness win.** `admin/balancer.py:215-218` documents that
`enqueue_balance_exported_event` reads `balance.variants`, and that a lazy load
there "would blow up … *after* `bulk_create_from_balancer` already committed the
tournament teams" — a split-brain caused precisely by the writer's internal
commit. Moving the commit to the caller removes that hazard rather than adding
risk. `test_balance_exported_event.py:159-163` pins the eager-load requirement and
must keep passing.

### 5.1 Consolidating the writer

`bulk_create_from_balancer` moves to
`shared/services/team_export/materialization.py`, reconciling the two divergences
deliberately:

- **Identity.** The member input carries `workspace_member_id | None` *and*
  `battle_tag | None`. Team registration passes the former — no tag lookup, and the
  silent-skip class of bug becomes unreachable.
- **Strictness.** Explicit `on_unresolved: "skip" | "error"`. balancer-service
  export keeps `"skip"` (preserves today's behaviour), parser-service keeps
  `"error"`, team registration uses `"error"`.
- **Transaction.** Flush only; callers own the commit. This is the one genuinely
  invasive edit — `admin/balancer.py:241` and `draft/export.py:139` currently rely
  on the internal `session.commit()` at `team.py:198`.
- **Substitutes.** Emit `is_substitution=True` with `related_player_id=NULL`.
  Semantically honest: `related_player_id` means "the player this sub *replaced*",
  and at registration time nobody has been replaced. `avg_sr`/`total_sr` filter on
  `is_substitution` alone, so the exclusion stays correct with a null link.

`Team.captain_id` comes from the captain registration's
`workspace_member.player_id` — no battle-tag resolution in this path at all.

## 6. Registration activation — consolidation

Today's three knobs across two surfaces collapse to one.

**Removed:** `BalancerRegistrationForm.is_open`, `Tournament.allow_late_registration`.

**New rule:** registration is open iff the tournament has a `REGISTRATION` phase
schedule row and `now ∈ [starts_at, ends_at]`. The row becomes **required**.

Four implementation constraints:

- The "missing row ⇒ **closed**" inversion must live in a **dedicated** helper in
  `services/registration/windows.py`. Do **not** change
  `tournament_state.is_within_phase_window`: its "missing row spans the whole
  phase" contract is also relied on by `is_check_in_window_active`.
- `is_finished_for_status` stays as a non-configurable safety floor, so a mis-set
  `ends_at` can never reopen a COMPLETED/ARCHIVED tournament.
- **A SQL-expressible predicate is required, not just a Python helper** (found in
  review). `is_open` is read directly — bypassing `is_registration_open` — in four
  places, three of which need the predicate inside a query:

  | Reader | Use |
  |---|---|
  | `app-service/.../readiness.py:188` — `form_open is not None` | `registration_form_configured`: **does a form row exist at all** |
  | `app-service/.../readiness.py:189` — `bool(form_open)` | `registration_open`: is it currently open |
  | `app-service/src/services/dashboard/service.py:53` | counts tournaments with `is_open.is_(True)` |
  | `parser-service/src/services/subscription_collection/service.py:90` | selects forms with `require_subscription AND is_open` — **drives subscription-collection targeting** |
  | `tournament-service/src/services/registration/subscription_config.py:266` | admin preview counter for the same rule |

  > ⚠️ **`readiness.py` is two uses of one nullable scalar, not one** (found in the
  > third review round). `form_open is not None` answers "a form row exists" and
  > `bool(form_open)` answers "it is open" — they drive two separate checklist rows.
  > Migrating both to `registration_open_clause(now)` would collapse them, so every
  > tournament whose window merely *ended* would report **"Registration form: not
  > configured"**. Required: `registration_form_configured` becomes an `EXISTS` on
  > the form row, independent of openness; only `registration_open` takes the new
  > clause. Additionally the `registration_open` checklist row's `href` points at the
  > registration tab (`frontend/src/components/admin/tournament-checklist.ts:116-122`)
  > while the governing control moves to Settings → Phase schedule — it must be
  > repointed, or the organizer clicks a red item and lands somewhere that cannot fix it.

  Ship a shared `registration_open_clause(now)` SQL clause alongside the Python
  gate, following the existing `balancer_pool_included_clause` precedent
  (`registration/export.py:79`). The write/serialize surface must be removed in the
  same cutover: `schemas/registration.py:78,107`, `registration_build.py:110`,
  `serializers.py:130`, `service.py:920,932`.
- **A backfill migration and a wizard change are mandatory** (found in review).
  `isWizardStepRequired` returns true **only** for `"basics"`
  (`frontend/src/app/admin/tournaments/new/wizard-model.ts:56-58`), and
  `canCreateNow` creates a tournament with defaults for the remaining steps — so
  tournaments with **no** `REGISTRATION` schedule row demonstrably exist today and
  rely on `is_open`/`allow_late_registration` alone. Without a backfill they would
  have registration silently and permanently closed the moment this ships, and the
  effect is **universal**, not scoped to team-registration mode.

  > ⚠️ **The backfill must evaluate the OLD predicate per tournament, not read
  > `is_open` alone.** An earlier draft mapped `is_open=true ⇒ ends_at = NULL`.
  > That is wrong in the *opposite* direction and was caught in review: the new
  > rule intentionally drops the `status == REGISTRATION` conjunct (that is what
  > makes late registration expressible as an `ends_at` beyond the LIVE start), and
  > `ends_at IS NULL` already means "open-ended" (`tournament_state.py:155-158`).
  > Composing the two, every non-finished tournament with `is_open=true` — including
  > those already in CHECK_IN, DRAFT or LIVE — would become **permanently open** for
  > self-service registration on deploy. `self_register` and the subscription gate
  > are per-user capability checks and do not restore a phase gate.

  Required backfill, for every non-finished tournament with no `REGISTRATION` row:

  | Old state | `starts_at` | `ends_at` | Rationale |
  |---|---|---|---|
  | `is_open=false` | `created_at` | `now()` | was closed ⇒ stays closed |
  | `is_open=true`, `status == REGISTRATION` | `created_at` | `NULL` | genuinely open now; open-ended preserves it |
  | `is_open=true`, `allow_late_registration=true`, status past REGISTRATION | `created_at` | `NULL` | today's predicate returns open ⇒ faithful |
  | `is_open=true`, `allow_late_registration=false`, status past REGISTRATION | `created_at` | `now()` | **today's predicate returns CLOSED** — the case the naive mapping would have silently reopened |

  Also required: (a) make the `REGISTRATION` row required in the creation wizard and
  in `canCreateNow`'s defaults; (b) a migration test asserting that for each of the
  four rows above, the new predicate returns exactly what
  `is_registration_open` returned pre-migration.

Extending registration is now one edit to that row's `ends_at`; closing it early is
the same edit. `test_registration_form_is_open_is_a_kill_switch` is replaced by
schedule-based equivalents.

## 7. Frontend

**Admin.**
- `TournamentSettingsTab.tsx:284-289` and wizard `RulesStep.tsx:36-41`:
  `team_formation` gains `'registration'`; `allow_late_registration` removed; the
  schedule editor must treat the `REGISTRATION` row as required.
- `RegistrationFormBuilder.tsx`: drop the `isOpen` toggle from
  `RegistrationStatusCard`; add a Team card (`max_substitutes`, invite-link TTL)
  beside `BuiltInFieldsCard`/`CustomFieldsCard`.

**Public captain flow.** Team identity (name + logo) → a slot matrix derived from
`RosterShape` (`has_role_slots=false` renders N undifferentiated `flex` slots) →
per-slot invite with live `open`/`invited`/`accepted` state.

> **Security — rewritten after review; the original premise was false.** An
> earlier draft mandated exact-identifier-match resolution on the grounds that a
> public browse/autocomplete search would be a user-enumeration surface, inferring
> that from `AuthUserSearchCombobox` being `auth_user:read`-gated. Both halves are
> wrong. That combobox is gated because it searches **auth accounts by
> email/username and renders `user.email`**
> (`AuthUserSearchCombobox.tsx:24-27,46-47,91-92`) — email, not player identity. And
> a public, **anonymous, partial-match** player search already exists and is
> load-tested: `GET /api/v1/users/search` is `edge.AuthNone`
> (`gateway/internal/app/routes.go:47`), as are `/api/v1/users` and
> `/api/v1/users/{name}` (`:46`, `:64`); participants' battle tags are already public
> through `reg_pub_list` (`registration/serializers.py:83-84`). Player enumeration
> is therefore an *existing, intentional* property of the platform, and exact-match
> buys almost no marginal privacy.
>
> The real exposure is different and was unaddressed: **there is no authenticated
> rate limit anywhere in the stack.** `authLimiter` is wired only onto `/api/auth/*`
> (`gateway/cmd/gateway/main.go:184-213`), `AnonRateLimit` defaults to `0 = disabled`
> (`gateway/internal/config/config.go:210`), and authenticated requests bypass
> `WrapAnon` even when it is enabled (`ratelimit_test.go:105-110`). The remaining
> backstops are `GATEWAY_RPC_MAX_INFLIGHT=64` (a bulkhead, not a rate limit) and
> coarse nginx `limit_req`. So the invite endpoint would be an unmetered
> invite-spam primitive.
>
> Required controls, in order of value:
> 1. A per-`(workspace, auth_user)` counter on **both** resolve and invite, reusing
>    `assert_redeem_attempt_allowed`
>    (`registration/subscription_status.py:128-155`). Note that helper deliberately
>    fails **open** on Redis error — defensible behind a high-entropy code, **not**
>    defensible when the limiter is the only control on a spam primitive, so this
>    path must fail **closed**.
> 2. A cap on outstanding `pending` invites per team and per actor. Precedent: the
>    per-creator open-room cap `ix_scrim_room_open_by_creator`
>    (`shared/models/tournament/scrim.py:47-51`).
> 3. A uniform response for "no match" and "match but not invitable", so the
>    endpoint is not a membership oracle.
>
> Partial-match resolution is acceptable given the above; exact-match is retained
> only as the default UX (it is a better interaction for entering a known teammate),
> not as a security control.

**Invitee flow.** `UnifiedRegistrationForm` in `mode="public"` with the slot
pre-assigned; the `RoleStep` matrix collapses to "confirm rank for your slot". This
extends the existing `flexMode` seam (which already seeds reducer-initial state and
hides priorities) rather than fighting it.

**Read surfaces.** A new Teams view beside participants (plain component — tens of
teams, no virtualization), plus one `ColumnDefinition` with `category:'meta'` and a
`searchValue` of the team name so existing search/filter keep working.

**i18n.** New `registrationTeam.*` namespace in **both** `en.json` and `ru.json`;
parity is enforced by the `RegistrationFormBuilder.i18n.test.tsx` pattern (real
message bundles under `NextIntlClientProvider`, which renders the raw key path on a
miss).

## 8. Edge cases and invariants

- **Token race.** Acceptance is a guarded transition —
  `UPDATE … SET state='accepted' WHERE id=? AND state='pending'` with a rowcount
  check — never read-then-write, or a leaked link races two people into one slot.
- **Slot overfill** (tightened after review). Comparing accepted
  `team_slot_code` counts to `RosterShape` "inside the transaction" is **not**
  sufficient on its own: two concurrent accepts for the last slot can both read a
  below-cap count before either commits, and no DB constraint can express
  "at most 2 dps". The count MUST be taken under a row lock on the parent team —
  `SELECT … FROM balancer.registration_team WHERE id = :id FOR UPDATE` — which
  serializes all accepts, kicks and materialization for that one team while
  leaving other teams fully concurrent. Contention is trivial at this scale (a
  team has ≤12 slots). The invite-state guard remains a separate atomic `UPDATE`;
  identity collisions still fall through to `uq_balancer_registration_user`.
- **Lock ordering and materialization lock scope** (added after review). The
  per-team lock above covers accepts and kicks, where exactly one team row is
  locked. Materialization is different: it locks **every** complete team of the
  tournament in one transaction, so the "≤12 slots, trivial contention" argument
  does not extend to it. Two requirements follow:
  1. The multi-row acquisition MUST be `… WHERE tournament_id = :t AND status =
     'complete' ORDER BY id FOR UPDATE`. Without a deterministic `ORDER BY id`,
     two concurrent or retried `export_registered` calls can acquire in opposite
     orders and deadlock — and retry is realistic, because the gateway's write
     timeout can elapse while the RPC is still running.
  2. The locks are held across delete → insert → backfill, blocking every accept
     and kick in that tournament for the duration. That is acceptable **only**
     because materialization is an explicit, rare organizer action (decision 6) and
     the registration window is normally closed by then; it would not be
     acceptable under the rejected auto-export-on-completeness alternative.
- **Already registered.** Solo or on another team, the same partial unique index
  rejects it. Needs a test asserting a comprehensible message, not a raw
  constraint name.
- **Roster-shape change while teams exist.** Requires the exact analogue of the
  existing `roster_locked_by_draft` guard — changing `roster_slots_json` while
  non-disbanded `registration_team` rows exist would silently invalidate every
  roster.
- **Withdrawal.** Soft-deletes the registration; both unique indexes are
  `WHERE deleted_at IS NULL`, so the slot *and* the battle tag are genuinely freed
  and the team drops back to `forming`.
- **Incomplete at close.** No cap, no waitlist — the team never materializes and
  shows as incomplete in `regteam_list`.
- **Re-export.** Blocked once `Standing` rows exist: re-export is
  destructive-then-idempotent, not diffed.
- **Subscription staging.** `subscription_stage='registration'` blocks acceptance;
  `check_in` defers to per-member check-in, which works unmodified because members
  are ordinary registrations.
- **Unlinked substitutes render as starters** (verified defect, must ship with
  step 5). `sortTeamPlayers` buckets a player into `children` only when
  `is_substitution && relatedPlayerId !== null && playerById.has(relatedPlayerId)`;
  otherwise it falls to `roots.push(player)` (`frontend/src/utils/player.ts:76-84`).
  Because registration-time substitutes carry `related_player_id = NULL` (§5.1),
  a team with two bench players would render as a seven-player starting lineup,
  sorted by role priority alongside the starters. `Team.avg_sr`/`total_sr` are
  unaffected — they filter on `is_substitution` in SQL. Required change: give
  `sortTeamPlayers` a third bucket for unlinked substitutes, emitted after all
  starters and their replacement chains, and mark them as bench in
  `TournamentTeamTable`/`TeamRosterEditor`. `TeamRosterEditor.tsx:91` and
  `admin/team.py:115` are already null-safe and need no change.

## 9. Testing strategy

**Backend** (pytest, following `test_registration_self_register_gate.py`):
schedule-only gate including **missing row ⇒ closed**; `self_register` denial on
accept creates zero rows; both duplicate-defence layers; token single-use race;
captaincy transfer and disband; completeness vs shape including an all-`flex`
roster; export idempotency; export strictness (`"error"` on unresolved);
substitute rows and the `avg_sr` exclusion; the `Standing`-exists guard.

**Regression (load-bearing for decision 16):** `test_balance_exported_event` and
`test_draft_integration` must pass **unchanged**, plus new tests that the shared
core commits exactly once on success and, critically, that **a failed export
leaves the prior teams intact** — the failure contract in §5 exists because the
current code path commits its own destructive delete
(`admin/balancer.py:229-237,263-267`). Also required: a deadlock/ordering test
that two concurrent `export_registered` calls serialize rather than deadlock (§8),
and a migration test pinning old-vs-new predicate equivalence for all four
backfill cases (§6).

**Frontend:** bun:test + happy-dom harness (per `RoleStep.behavior.test.tsx`) for
the slot matrix and the locked-slot `RoleStep`; a `sortTeamPlayers` unit test
asserting an unlinked substitute (`is_substitution: true`,
`related_player_id: null`) sorts **after** every starter rather than among them
(§8); vitest + real `en`/`ru` bundles for the new admin Team card.

## 10. Implementation order

1. ✅ **DONE — Refactor.** Consolidated into `shared/services/team_export/`
   (`identity.py`, `materialization.py`, `service.py`). All **four** writer callers
   migrated: `export_balance`, draft `export`, `rpc/binary.py::teams_import`
   (balancer-service) and `rpc/bootstrap.py::teams_create_balancer` (parser-service).
   Two further divergences surfaced during implementation and are now explicit
   parameters or preserved deliberately:
   - The slot-code resolver also diverged: parser **raised** on an unknown code and
     did not accept `"damage"`; balancer returned `None` and did. `on_unresolved`
     now governs both identity *and* slot resolution, since each old caller was
     uniformly strict or uniformly lenient.
   - Parser raised **404** for an unknown tournament where balancer logged a no-op.
     Preserved by keeping parser's explicit `tournament_flows.get` before the call.
   - `rpc/binary.py` and parser's `bootstrap.py` had **no commit of their own** and
     depended entirely on the writer's internal commit — routing them through the
     orchestrator (which commits once) is what keeps them working.
   - The battle-tag resolver was a *third* byte-identical duplicate pair; it moved
     to `identity.py` and both service-local copies became re-exports.
     Verification: 1365 tests pass (`balancer-service` 348, `parser-service` 288,
     `shared`+root 1077 minus overlap); the failure contract is pinned by 6 new tests
     in `shared/tests/test_team_export_service.py`. The 3 remaining failures
     (`test_db_pool_config`, `test_rank_snapshots`, `test_repository_boundaries`) were
     confirmed **already failing at HEAD** in a clean worktree.

     ✅ **DB-backed verification done (2026-08-20).** Against real Postgres 18.1 on
     the Stockholm server (ssh tunnel, isolated scratch database built from this
     tree's own migration chain — see the note under 2a for why `anak_dev` itself
     could not be used): `test_draft_integration` **27 passed**, including
     `test_full_run_autopick_to_completion_then_export` and
     `test_export_is_idempotent` — the end-to-end proof this refactor needed;
     `test_draft_custom_rules` + `test_admin_summary` **9 passed**. The scratch
     database was dropped afterwards and `anak_dev` is byte-identical to before
     (same revision, same row counts).

   > ⚠️ **`anak_dev` is on a different migration lineage.** It reports revision
   > `mtchlog001`, which does not exist in this tree (local head before this work
   > was `ncscope01`), and its `workspace` table lacks `discord_guild_id` — a
   > column created by this tree's **base** migration `initial_v6`. So `anak_dev`
   > was not built from this chain at all: `alembic upgrade head` cannot run there,
   > and this tree's ORM-backed integration tests fail at setup on the missing
   > column. All DB verification therefore used an isolated scratch database on the
   > same server, created from this chain and dropped afterwards. Reconciling that
   > divergence is a separate decision, and it blocks using `anak_dev` for
   > ORM-level testing until it is resolved.
2. **Activation consolidation** — the widest-blast-radius step, and it is
   **cross-service and universal**, not team-registration-specific. **Ship this on
   its own, before any team-registration code**, and split it expand/contract,
   because `is_open` is selected by three separately-deployed images
   (`app-service`, `parser-service`, `tournament-service`) against one shared
   Postgres — a migration landing before the old containers are replaced yields
   `UndefinedColumn` on the readiness card, the dashboard count, and the
   `subscription_collection` worker that drives subscription targeting:
   - ✅ **2a (expand) — DONE.** `shared/services/registration_window.py` provides
     both forms: `is_registration_window_open` (Python) and
     `registration_open_clause(now)` (SQL), so the per-tournament and in-query
     answers cannot drift. `windows.py::is_registration_open` delegates and **lost
     its `form` parameter** — keeping it would imply the form still had a say.
     All four direct readers migrated, `readiness.py`'s conflated scalar split in
     two, and the API's `is_open` became a **derived, read-only** field (passed
     into the sync serializers exactly as `subscription_requirement` already was);
     `RegistrationFormUpsert` dropped it, tolerated via the module's existing
     `extra="ignore"` convention rather than 422'ing stale clients.
     Migration `regwin0001` backfills. Frontend: the dead `is_open` toggle became
     a read-only status line, and `allow_late_registration` is gone from the
     settings tab, the creation wizard, the review step and all four TS types.

     Two things this step found that no review round had:
     - **A fifth reader**: `frontend/src/lib/tournament-status.ts::isRegistrationOpen`
       is a client-side duplicate of the whole gate (form flag + phase window +
       late flag). Found by `tsc`, not by grep — the reviews had enumerated
       backend readers only. Now schedule-only, with the missing-row inversion.
     - **An off-by-one in the backfill**, found by the equivalence test: `ends_at`
       is *inclusive* (`now <= ends_at`), so closing a window with
       `ends_at = now()` leaves it open at that instant. The migration now closes
       strictly before now, guarded by `GREATEST` against the CHECK constraint.

     Verification: 1966 backend tests pass (3 failures pre-existing at HEAD,
     confirmed in a clean worktree); 916 vitest + 574 bun frontend tests pass;
     ruff, tsc and eslint clean. `shared/tests/test_registration_window.py` pins
     the predicate and checks old-vs-new equivalence across the full 120-case
     cross product of status x is_open x allow_late x 5 window shapes.

     **Not done in 2a, deliberately:** the "Close registration now" one-click
     affordance (§12.3) and making the `REGISTRATION` row required in the wizard
     (§6). Both are additive UX; omitting them is safe because a missing row means
     *closed*, so the untouched default direction is the conservative one. The
     schedule editor is currently the only way to close registration — that is the
     usability regression §12.3 exists to fix, and it is the top of the 2b list.
   - **2b (contract).** Only once no deployed image references them, drop
     `BalancerRegistrationForm.is_open` and `Tournament.allow_late_registration`,
     and replace the kill-switch test. This is the step with no rollback, so it
     must be its own migration.
3. ✅ **DONE — Data model.** Migration `regteam0001` (revises `regwin0001`) creates
   `balancer.registration_team` (16 columns) and `balancer.registration_team_invite`
   (14), and adds the three additive columns to `balancer.registration`. Models in
   `shared/models/registration/registration.py`; guard in
   `shared/services/registration_team_guards.py`, a deliberate sibling of
   `draft_guards.py` with the same three-function shape.

   Decisions worth recording because the obvious choice was the wrong one:
   - The captain FK is **circular** with `registration.registration_team_id`, so it
     carries `use_alter` (the pattern `draft_session.current_pick_id` already uses)
     and both FKs are added after the tables exist. Pinned by a test that asserts
     the captain FK is **not** emitted inside `CREATE TABLE`.
   - Deleting a team is `SET NULL` on the member, never a cascade: a captain
     disbanding must not destroy real people's registrations. Pinned by a test.
   - The guard treats `disbanded`/`rejected`/already-exported teams as **not**
     blocking — a released team holds no slots, and an exported one already froze
     its shape into `tournament.player` rows. That set is the entire content of the
     guard, so the test asserts the emitted SQL, not the constants.
   - The read side gained `roster_locked_by_teams` alongside
     `roster_locked_by_draft` rather than widening the existing flag's meaning: the
     name is specific and renaming it would be a breaking API change. The Settings
     tab must disable the shape editor when **either** is set — frontend work,
     step 6.

   Verification: applied against real Postgres 18.1 (isolated scratch database,
   dropped after) — both partial unique indexes carry their `WHERE` clauses
   (`deleted_at IS NULL`, `token_sha256 IS NOT NULL`), both circular FKs land as
   `SET NULL`, and `downgrade -1` → `upgrade head` round-trips cleanly (tables and
   columns gone, revision restored). Suites: 1984 + 288 + 348 pass; the only 3
   failures remain the ones pre-existing at HEAD. Ruff caught a missing import that
   the tests could not, for the second time in this feature — the lazy RPC/read
   handlers mean an undefined name surfaces at call time, not at import.
4. ✅ **DONE — Backend flows.** Eleven flows in
   `tournament-service/src/services/registration/teams.py`: `create_team`,
   `invite_member`, `revoke_invite`, `accept_invite`, `decline_invite`,
   `kick_member`, `leave_team`, `transfer_captaincy`, `disband_team`, plus the
   organizer's `list_teams` and `reject_team`. Two pure-domain modules carry the
   risky logic: `shared/domain/team_roster.py` (slot accounting) and
   `shared/domain/invite_token.py` (256-bit url-safe token, sha256 at rest,
   `compare_digest`).

   **Reuse instead of a second writer.** The captain and invitee flows delegate to
   `submit_public_registration`, which gained exactly two optional parameters:
   `team_placement` (the three team columns) and `commit` (transaction boundary).
   Both default to today's behaviour. Copying that function's form/subrole/hero/
   verified-identity validation into a team path would have been the third
   divergent duplicate of a validated writer in this codebase — the same class of
   debt step 1 spent its whole budget consolidating.

   **`commit=False` was forced, not preferred.** Consuming the invite, writing the
   registration and updating the team's denormalized `status` must land together:
   the row lock is released at commit, so a status written afterwards can drift
   from the roster it describes. Same split the team-export orchestrator uses.
   A caller passing it also owns `IntegrityError` mapping, since that now fires
   outside the helper's own `try`.

   **Two asymmetries are the whole design.** A pending invite *reserves* its slot
   for offering (else ten offers can be held open for one place, and the invite
   table becomes an unmetered spam surface in the slot dimension) but must *not*
   block its own acceptance (else every invite is un-acceptable). `can_offer` and
   `can_accept` are separate methods for exactly this, and both directions are
   pinned by test.

   **Ordering, so a failed accept never burns the invite.** Every knowable
   rejection — closed window, terminal team, exported team, already registered,
   slot taken — is raised *before* the guarded `UPDATE`. A later failure rolls the
   consume back with it, since there is no commit in between.

   **§12.1 implemented.** The guard folds state and expiry into the `UPDATE`
   (`now()`, the database clock — a Python timestamp would be evaluated before the
   lock is granted). On rowcount 0 `_diagnose_dead_invite` re-reads for reporting
   only and returns `invite_already_accepted` / `invite_revoked` /
   `invite_declined` / `invite_expired`. Pending-and-unexpired maps to
   `already_accepted`, not `expired` — reporting an expiry there would be a lie.

   **§12.2 implemented.** Every rejection is `ApiHTTPException(detail=[ApiExc(msg,
   code)])`, which already existed. Codes are split where the recourse differs:
   `slot_taken` vs `slot_already_offered` (revoke the outstanding invite),
   `bench_full` vs `roster full`, and `slot_not_in_shape` is a **400** not a 409 —
   no future team state makes `tank` valid on a role-less tournament.

   **Corrections found while building.** `WorkspaceMember` has no `auth_user_id`
   (`dbarch02` dropped it); identity runs member → player → auth user. I had
   hand-rolled the wrong join twice before checking how `get_registration` does it
   — now one `_owned_by` predicate. Ruff caught an unused import; the tests could
   not have.

   **`max_substitutes` was missing from step 3.** Decision 4 promised configurable
   substitutes but `regteam0001` shipped no knob for it. Added by `regteam0002` on
   `registration_form`, not on `Tournament.roster_slots_json`: a substitute holds
   no starter slot, so the shape and the `roster_locked_by_teams` guard stay
   untouched.

   Verification: **1253** tournament + **782** shared/root + **288** parser +
   **338** app + **348** balancer pass; the only failures are the 3 confirmed
   failing at HEAD. `regteam0002` applied on real Postgres 18.1 (isolated scratch
   DB, dropped after), `downgrade -1` → `upgrade head` clean, and the expand
   proven against **4 real `registration_form` rows in `anak_dev`** inside a
   rolled-back transaction — all backfilled to 0. The **36 DB-backed export tests**
   (`test_draft_integration`, `test_draft_custom_rules`, `test_admin_summary`) pass
   against the migrated schema, which is what proves the new mapped column and the
   `commit=False` split did not break the export path.

   **Not done, deliberately:** RPC subjects and gateway routes — the flows are not
   yet reachable over HTTP. Also no rate limiter (§7 control 1), so public invite
   creation is unmetered *per actor*; the slot reservation above caps it per team
   but not per attacker. Both are named in step 4's remainder below.

   **Deploy ordering is now load-bearing.** `max_substitutes` is a mapped column,
   so SQLAlchemy emits it in every `registration_form` SELECT. `regteam0002` must
   land before any image carrying this code, or every form read 500s.

   **Step 4 remainder — transport, ✅ DONE.** Eleven RPC subjects
   (`rpc.tournament.regteam_*`: nine public in `public_rpc.py`, plus
   `regteam_list`/`regteam_reject` in `registration_admin.py`), eleven gateway
   routes, and `src/schemas/registration_team.py` with the request/read models and
   two serializers. `apidocs/groups.go` generates from the same route tables, so
   the OpenAPI surface needed no hand-editing.

   **A new static guard: `tests/test_rpc_route_parity.py`.** A gateway route naming
   a subject nobody subscribes to is the one wiring bug in the RPC layer with *no*
   signal — the gateway publishes happily, the caller sees a request timeout, and
   nothing logs "unknown subject". With 11 new subject/route pairs a typo on either
   side was a real risk, so the two literal-string sides are now compared
   statically (text parsing; no Go toolchain, no broker). The sweep found no
   pre-existing orphans across all ~50 tournament subjects. It also pins the two
   security decisions that live in the route table itself: every team route is
   `AuthRequired`, and no route carries `{token}` in its path.

   **Three corrections the wiring surfaced:**
   - `reject_team` had no tournament scope. It is authorized by
     `_tournament_ctx` against *one* tournament's workspace, so accepting a bare
     `team_id` let an organizer of event A reject teams in event B. Now
     `tournament_id` is keyword-only without a default and asserted against the
     locked row — returning **404, not 403**, since confirming the team exists
     elsewhere leaks roster membership across workspaces. Both the boundary and the
     un-omittable signature are tested.
   - Query params must be read with `_q1`, not `data.get`: `AllQuery` nests the
     query string, so `include_terminal` would have silently been `False` forever.
   - Accept/decline take the invite reference in the **body**, not the path. A raw
     token in a URL lands in access logs, browser history and `Referer` headers.

   Verification: **1258** tournament + **789** shared/root + **288** parser +
   **338** app + **348** balancer pass (only the 3 known-at-HEAD failures);
   `go build ./...` and `go test ./...` clean; ruff clean.

   **§7 controls 1 and 2 — ✅ DONE**, in
   `tournament-service/src/services/registration/team_rate_limits.py`. These are
   the **only authenticated rate limits in the stack**: the gateway's
   `internal/ratelimit` is per-IP, per-process and scoped to `/api/auth/*`, and
   nginx is coarser still. Neither bounds what one logged-in account can do.

   **The fail direction is deliberately NOT uniform, and that corrects this
   design's own earlier note.** The note said "fail-closed per-actor limiter"; on
   implementation that is right for one endpoint and wrong for the other.
   - `invite` **fails closed** (503 → `rate_limit_unavailable`). Each call mints a
     bearer credential — a token whose holder writes a registration into someone
     else's roster — and will send a notification once step 6 lands. Losing Redis
     must not turn an amplifier unmetered. Accepted cost: during a Redis outage
     captains cannot invite.
   - `accept`/`decline` **fail open**, matching the existing
     `assert_redeem_attempt_allowed` for challenge codes. What a limiter protects
     there is a 256-bit token against guessing, which is already infeasible, so it
     is defence in depth. A *successful* accept is self-limiting anyway: one
     registration per player per tournament means a second cannot succeed.

     Uniform fail-closed would trade a real availability loss for protection
     against an attack 256 bits of entropy already prevents. One test asserts both
     directions together, so unifying them fails exactly one line.

   **Control 2 is a cumulative cap, not a pending cap.** Reserving a slot bounds
   *concurrent* pending invites at the number of open slots — but `invite → revoke
   → invite` in a loop satisfies every slot rule. `TEAM_INVITE_TOTAL_CAP` counts
   every invite ever created for a team, revoked and declined included, so the loop
   terminates even inside one rate-limit window.

   **The limiter runs BEFORE the row lock.** Metering behind it would let a flood
   serialize on the team row and hold it, turning the throttle into a
   lock-contention amplifier.

   **A vocabulary gap this surfaced.** The service raised 503, but
   `shared/schemas/rpc.py`'s `status_to_code` had no 503 entry, so it degraded to
   `internal` → **500 at the client**: the worker said "retry shortly" and the
   caller was told "we are broken". Added `unavailable` (503) to both the Python
   vocabulary and `gateway/internal/rpc/envelope.go`, plus
   `tests/test_rpc_error_code_parity.py` — a cross-language guard pinning the
   round-trip for all ten statuses, since nothing tied the two declarations
   together before. Both sides degrade safely: an unknown code is still 500.

   **Deployment note:** invite creation now has a hard Redis dependency by design.
   Redis down = no new invites (everything else keeps working).
5. ✅ **DONE — Materialization path.** `rpc.balancer.teams.export_registered`,
   implemented as `shared/services/team_export/registered.py` (synthesizer) plus
   `balancer-service/src/services/registered_teams.py` (the flow), and one gateway
   route. Decision 14 held up: **no third writer was needed.** Step 1's
   consolidation had already put `workspace_member_id`, `is_substitute`,
   `captain_player_id` and `guard_standings` into the seam, so this step added a
   caller and nothing else — the writer itself is untouched.

   **Two settings differ from the other two callers, both deliberately.**
   `guard_standings=True`: the balancer and draft exports re-export destructively
   by design, but doing that here would silently invalidate a bracket already built
   on these teams. `on_unresolved="error"`: registered members arrive pre-resolved,
   so `"skip"` would materialize an under-sized roster with nothing raised — the
   exact failure the shared writer's docstring warns about. Both are asserted on
   the plan, because a copy-paste from `draft/export.py` would drop them silently.

   **Both rank rules are borrowed, not invented.** `Player.rank` is NOT NULL while
   `BalancerRegistrationRole.rank_value` is nullable, so a rank source had to be
   chosen. Missing rank → `0`, matching `registration/export.py::build_class`
   (raising would make the feature unusable for tournaments that never collect
   ranks); which rank → mirrors `draft/ranks.py::slot_rank`, role-specific on a
   role shape and the maximum on a role-less one. A cross-file test reads the other
   module's source, since the two live in different services and cannot import each
   other — otherwise the same player would rank differently depending on which path
   materialized their team.

   **One constraint the seam forced:** a registered team name may not contain
   `"#"`. The seam derives `Team.name` by splitting `balancer_name` on it (the
   battle-tag convention), so `"Team #1"` would materialize as `"Team "` *and* the
   name-keyed `exported_team_id` backfill would then miss. Rejected at creation
   (`team_name_invalid`), which is the only place it is cheap.

   Verification: **8 new DB-backed integration tests pass against real Postgres
   18.1** (isolated scratch DB at `regteam0002`, dropped after) — a complete team
   becomes a `tournament.team` with the right name, slot codes become player roles,
   ranks come from the registration roles, the substitute is written as one and
   **excluded from `total_sr` (7500, not 8500)**, the `exported_team_id`/
   `export_status`/`exported_at` stamp lands, re-export replaces rather than
   duplicates (new team id, same player count), an incomplete team is skipped with
   `team_incomplete` and writes nothing, and a withdrawn member releases their slot.
   The pre-existing **36 DB-backed export tests** still pass, which is what proves
   the shared writer was not disturbed. Unit suites: 1261 tournament + 733 shared +
   67 root + 355 balancer + 288 parser + 338 app, only the 3 known-at-HEAD
   failures. `go build`/`go test` clean, ruff clean.

   **The parity guard found two real gaps when extended to `rpc.balancer`.** Its
   original `@broker.subscriber("...")`-anchored regex reported eleven false
   orphans, because two registration styles defeat it: five balancer draft subjects
   register through a `_make_lifecycle(subject, …)` factory, and the whole
   `rpc.tournament.admin.*` CRUD family registers from `services/admin/registry.py`
   — outside `src/rpc` entirely. It now matches any subject literal outside the
   doc-only modules. A second test's premise was simply **wrong** and was
   corrected rather than made to pass: several subjects are deliberately exposed at
   two paths, so "no subject is routed twice" is false repo-wide and is now scoped
   to the subjects this feature added.

   **Kept off the repository-boundary exemption list.** `session.get` became
   `session.scalar(select(...))` (a read has no business counting as a write), and
   the failure hook stayed a row-by-row `inner.get` loop rather than one
   `sa.update` — the guard's regex is name-based, so `inner.get` needs no
   exemption, which is exactly why `draft/export.py` needs none either. Zero new
   allowlist entries.
6. ✅ **DONE — Frontend.** Captain flow, invitee flow, Teams view, participants
   column, admin Team card, i18n parity.

   **6a — read surface + backend prerequisites: ✅ DONE.** Scoping this step
   surfaced **three gaps that blocked all UI work**, none of which were in the
   plan:
   - **The team columns were exposed nowhere.** `registration_team_id` /
     `team_slot_code` / `is_substitute` existed on the table since step 3 but not
     on `RegistrationRead`, so the participants table's team column and the §12.5
     "your team is incomplete" line had **no data source at all**. Added
     `RegistrationTeamBrief` (deliberately not the full read model: it rides in
     every row of a public list, and it carries **no invites** so the roster cannot
     leak who declined).
   - **No public teams list existed** — only the admin `regteam_list`. A public
     Teams tab had nothing to read. Added `rpc.tournament.regteam_list_public`
     (`AuthOptional`, invites omitted server-side, terminal teams excluded).
   - **Six load sites needed the eager load**, and forgetting one does not raise —
     it silently serializes `team: null`. Added `registration_read_loaders()`
     *colocated with `_reg_to_read`*, since the invariant is "if you serialize with
     this, load these" and the two must not drift.

   **§12.2 implemented — the first code→i18n mapping in the codebase.**
   `friendlyMessage` in `api-error.ts` prefers the server's `msg` **verbatim**, and
   every backend message is English, so the audience being Russian-first meant raw
   English error text. `lib/registration-team-errors.ts` maps all **31** codes to
   translated strings, scoped to this feature rather than grown into the
   English-only generic `ERROR_CODE_MESSAGES` table. Unmapped codes fall through to
   the old path, so a future backend code degrades rather than blanks.

   **A scout brief was wrong and the correction matters.** It reported "no
   whole-file ru/en parity test exists"; `frontend/src/i18n/messages.parity.test.ts`
   asserts **identical nested key paths across both entire files**. It is a
   `bun:test` file, which is why a vitest-only search missed it. Verified by
   reading and running it — adding a key to one locale *does* fail CI.

   Parity alone is not enough, though: both dictionaries can be symmetric and both
   missing a code. `registration-team-errors.test.ts` ties the TS code list to the
   dictionaries and additionally asserts the Russian tree is not an English
   copy-paste (no en/ru value identical, every ru value contains Cyrillic) — which
   key-based assertions cannot catch.

   Also landed: `registration-team.types.ts`, `registration-team.service.ts` (all
   13 calls), and two query-key factories. `include_terminal` is part of the admin
   key because the two results are different data, not a filtered view of one entry.

   Verification: **1276** tournament + **733** shared + **74** root pass (only the
   3 known-at-HEAD failures); frontend **916 vitest + 588 bun** pass; `tsc`,
   `eslint`, `ruff` and `go build` clean. Two project lint rules fired during
   review and were complied with rather than suppressed (`Set`→`Record` for a
   static table; inlined a one-expression wrapper).

   **6b — remaining UI: ✅ DONE.** Built as four parallel slices against the 6a
   contracts (types, service, query keys, error map, all 114 i18n keys settled up
   front, which is what made parallel work safe).

   **`lockedRole`** on `RoleStep` + `UnifiedRegistrationForm`: the matrix collapses
   to one row, `normalize()` is bypassed (its cross-role rebalancing would demote
   the invite's own slot by reading the two hidden rows), the priority control is
   hidden, and both role rules in `validateCurrentStep` are skipped — a locked slot
   *is* the answer to "which role", and an invitee has no second row to fill nor
   authority to change the first. `buildRolesPayload` submits exactly that role
   with `is_primary: true`.

   **Surfaces:** `TeamRegistrationWizard` (captain), `InviteAcceptWizard`
   (invitee), `MyTeamPanel` (roster management: invite with one-time token reveal,
   revoke, kick, transfer, disband, leave), `MyTeamSection` (the entry point, self-
   contained so the tab hosts it in one line), the public Teams tab on its own
   section id `registration-teams`, the participants team column, the §12.5 line on
   the registration card, and the admin `RegistrationTeamsBrowser`.

   **Four real problems surfaced by building it:**

   - **The feature was unreachable.** Nothing could set
     `team_formation = "registration"` — the three admin selects offered only
     `balancer` and `draft`, and the backend column is a free string with no
     writer. Added in all three, plus `ReviewStep`, which summarised a registration
     tournament as "Auto-balance (Balancer)". Hardcoded English deliberately: all
     three files hardcode their existing two options, and one translated option
     beside two hardcoded ones is worse than consistent debt.
   - **`myCard.rejected`/`disbanded` were dead, and that was §12.5's dead end
     again.** `disband_team` and `reject_team` cleared `registration_team_id` on
     every member, and the brief is derived from that FK — so a player whose team
     was rejected saw only an unexplained withdrawal. Now the link is **retained**
     on disband and on reject-with-withdrawal (safe: `_roster_members` filters
     withdrawn rows, so slot accounting and the export are unaffected), and cleared
     only on kick/leave and reject-without-withdrawal. The distinction is real:
     kick/leave means "you are not on this team", disband/reject means "this team
     ended".
   - **The server's `shortfall` string leaked English into Russian sentences.**
     `describe_shortfall()` renders `"1x dps, 2x support"` — raw slot codes. Now
     built client-side from `open_slots` via `formatShortfall`. My first version
     used `ROLE_LABELS` (hardcoded English, **no `flex` entry**), which a slice
     caught: one card read "1× DPS" beside a translated "Урон" chip and a flex slot
     degraded to its raw code. It now takes the `rosterShape.slotCodes` translator
     every other slot display already uses. The server field remains the source of
     truth; only its presentation moved.
   - **next-intl types its translators narrowly.** `ErrorTranslator` was
     `(key: string) => string`, which the real scoped translator is not assignable
     to — and the same applied to `has`. Both now take the code union, so a missing
     key is a *type* error rather than a runtime fallback.

   **Deliberate `defaultVisible` choice** on the team column, worth recording: it
   is data-derived (`any registration carries a team`), not a constant. Hardcoded
   `true` puts a permanently blank column on every solo tournament; hardcoded
   `false` is equally wrong because search only walks *visible* columns, so
   find-players-by-team — the column's entire purpose — would be off until the user
   hunted through the picker.

   Verification: frontend **934 vitest + 588 bun** pass, `tsc`/`eslint` clean, the
   vitest include allow-list check passes; backend **1276** tournament + **733**
   shared + **74** root + **355** balancer, only the 3 known-at-HEAD failures;
   `go build`/`go test` clean. New tests include a mount-based i18n test rendering
   `MyTeamPanel` in both locales (fails on any unresolved key, and asserts the copy
   actually differs per locale), an executable leak guard proving the public teams
   tab renders nothing from an invites-carrying payload, and 8 admin-card behaviour
   tests including one that a real `ApiError` code renders the translated string
   rather than the server's English `msg`.

## 11. Open risks

- Step 2 is now understood to be the riskiest part of the feature, not step 1: it
  silently changes registration availability for **every** existing tournament and
  touches subscription-collection targeting in parser-service. The backfill is the
  single highest-consequence artifact in the whole plan.
- Step 1 touches two live critical paths (balance and draft export). The
  transaction-boundary change is the sharpest edge: a missing commit surfaces as
  "export silently did nothing". Mitigating factor discovered in review: it also
  removes the documented `balance.variants` lazy-load-after-commit hazard
  (`admin/balancer.py:215-218`).
- The new public invite/resolve endpoints are the only new externally reachable
  surface. The binding constraint is **not** enumeration (already public by design,
  §7) but the total absence of authenticated rate limiting in the stack: they must
  ship with a fail-**closed** per-actor limiter and a pending-invite cap, or not
  ship.
- Two destructive operations now have explicit contracts that did not exist before
  review: the export failure path (§5 — rollback, then stamp in a fresh
  transaction) and the activation backfill (§6 — evaluate the old predicate per
  tournament). Both were wrong in the first draft in the *silent* direction; treat
  their tests as release gates, not nice-to-haves.
- `registration_team.status` is a denormalization of "do the member rows fill the
  shape". It cannot drift because every transition is written under the same
  `FOR UPDATE` team lock that accepts/kicks take (§8), and materialization re-reads
  membership under that lock rather than trusting the column blindly.
- **Discharged (verified this session).** `is_substitution=True,
  related_player_id=NULL` is a new row shape for `tournament.player`. Every
  backend consumer excludes substitutes via `is_substitution.is_(False)` and never
  dereferences the link; the two that expose it type it `int | None`
  (`app-service/src/schemas/user.py:115`, `analytics_read/flows.py:140`); both
  frontend dereferences are null-guarded. The one real consequence is the
  `sortTeamPlayers` bucketing defect now specified in §8 — not an unknown.

## 12. User-experience requirements (review round 3)

Neither earlier review round examined the human path. These are mandatory, not
polish.

### 12.1 Failure diagnosis must survive the security hardening

§3.3 folds `expires_at` into the guarded `UPDATE … WHERE state='pending' AND
expires_at > now()`. That is correct for the race, but it means **expired,
revoked, already-accepted and already-materialized all return rowcount 0** — four
situations with four different recourses collapse into one opaque failure. On
rowcount 0 the handler MUST re-read the row **for reporting only** and return a
distinct machine code per case (`invite_expired`, `invite_revoked`,
`invite_already_accepted`, `team_already_exported`, `slot_taken`). The re-read is
not part of the guard and cannot reintroduce the race.

### 12.2 Error copy must be translatable — the current path cannot translate

`friendlyMessage` prefers the server's `msg` verbatim and
`defaultTitleForStatus` returns hardcoded English (`frontend/src/lib/api-error.ts:144-156`);
no `registration.errors.*` namespace exists in either bundle. Since the captain and
invitee flows are **public** and the user base is Russian-first, every new rejection
must carry a stable machine `code`, and the new surfaces must map code → translated
string via next-intl rather than rendering `msg`. Codes needed at minimum:
team name taken, already registered, slot taken, invite expired/revoked/consumed,
team already exported, window closed, rate limited (§7 control 1), invite cap
reached (§7 control 2).

### 12.3 Emergency close must remain one action

Decision 9 is kept, but the organizer's one-click `is_open` switch
(`RegistrationStatusCard.tsx:30-38`) must not degrade into "navigate to Settings,
open a calendar, type a time in the workspace timezone, save the whole settings
form". Ship a **"Close registration now"** button on the registration admin page
that writes `ends_at = now()` to the `REGISTRATION` schedule row. One action, and
the schedule stays the single source of truth — this is an affordance, not a second
knob. Note the two traps in the existing editor it must avoid: a blank time input
defaults to 12:00, and `getPhaseSchedulePayload` drops any phase with a blank
`starts_at` from its full-replace.

### 12.4 The lost phase lever must be stated

Dropping the `status == REGISTRATION` conjunct also removes a lever organizers use
today: **advancing the tournament to CHECK_IN no longer closes registration.** §6
treats this only as backfill correctness. It is a behaviour change that must be
called out in the admin UI (a hint on the schedule editor) and in the release notes.

### 12.5 The incomplete-team dead end must be visible to the people in it

§8 answers "incomplete at close" with `regteam_list` — an **admin** RPC. Two people
are left with no explanation:

- the **captain**, who gets no deadline warning and no post-close status;
- the **invitee who accepted**, who now holds a live approved registration for a
  tournament they cannot play in.

The platform's established contract is the opposite: the "Your Registration" card
carries a stepper plus a translated explanatory sentence for every state, including
terminal ones (`TournamentParticipantsPage.tsx:406-461`,
`registration.myCard.*` in both bundles). Both roles must get a team-aware state in
that card. **This is also the right home for the pending-invite surface** — see the
open question below.

### 12.6 Captain interaction weight

Five slots means five invite actions plus five acceptance states to track. The
existing wizard holds itself to 1–3 steps and actively drops any content-free step
(`UnifiedRegistrationForm.tsx:196-226`). Provide a bulk-invite path (paste several
identifiers at once) and one progress affordance ("3 of 5 confirmed"), not five
independent widgets.

### 12.7 No hardcoded strings on new public surfaces

The i18n test named in §7 catches an *unresolved key*, not a *hardcoded English
string* — and hardcoded English is the codebase's dominant admin-mode habit
(`UnifiedRegistrationForm.tsx:221-223`, `DetailsStep.tsx:79,103,105`). Because the
captain and invitee flows are public and Russian-first, the design forbids
user-visible literals on those surfaces; admin-only surfaces may follow the existing
convention.

### 12.8 Invite surface (decision 17)

There is no notification transport in the product: no bell or badge
(`UserMenu.tsx`), no inbox, no `/me` or my-registrations route, no email and no
push, and the backend's `workspace_notifications` topic has **zero** frontend
consumers. A standalone "my invites" page would therefore never be seen, and
captains would silently fall back to pasting token links.

So the invite lives where the invitee already goes: the per-user card on the
tournament page (`TournamentParticipantsPage.tsx:406-461`). Requirements:

- A pending invite for the viewer renders in that card as an actionable state
  ("Team *Alpha* invited you as **DPS**" + Accept / Decline), using the card's
  existing stepper-plus-explanation pattern and the `registration.myCard.*`
  translation convention already present in both bundles.
- `regteam_pub_my_invites` remains the read, but it feeds that card rather than a
  new page. The token link keeps working standalone for people with no account yet.
- The same card carries the two dead-end states from §12.5: captain of an
  incomplete team after close, and accepted member of a team that never completed.
- A future notification subsystem can add a badge on top without changing this
  contract. That work is explicitly out of scope.

### 12.9 Rank-free rosters (decision 18)

When `has_role_slots` is false, rank is not collected and `Player.rank` is written
as `0`; only the nominal slot is recorded, exported as `HeroClass.flex`. Verified
safe rather than assumed:

- `resolve_division_from_rank` always resolves a tier for `0` — `rank_min <= 0 <=
  rank_max` or the final-tier fallback (`shared/domain/division_rank.py:21-25`);
  no crash, no division by zero anywhere.
- The one heuristic that cares already guards it: `rank_suspicious = rank > 0 and
  rank <= rank_cutoff` (`analytics-service/src/services/ml/models/anomalies.py:113-114`),
  so zero-rank players are excluded rather than mis-flagged as low-rank.
- Consequence to state plainly in the admin UI: `Team.avg_sr`/`total_sr` will be
  `0` for such teams, and rank-gap features in `standings_v2` carry no signal for
  that tournament. The OpenSkill mu features still do.

In a roster **with** role slots, decision 5 stands unchanged: the member supplies a
rank for their slot's role, with autofill from history.

## 13. Arbitration record (multi-agent review)

Three constrained reviewers were run sequentially over this document, each with a
hard scope limit, with revisions applied between rounds.

| Round | Reviewer | Verdict | Objections | Disposition |
|---|---|---|---|---|
| 1 | Skeptic / Challenger | BLOCK | 4 | 4 accepted, 0 rejected |
| 2 | Constraint Guardian | BLOCK | 8 | 7 accepted, 1 accepted-with-amendment |
| 3 | User Advocate | BLOCK | 11 | 9 accepted, 2 escalated to the organizer |

**Every load-bearing objection was independently verified against source before
being accepted** — the reviewers' evidence was checked, not trusted. Four claims
proved this document factually wrong and were corrected: the `is_open` blast radius
(§6), the reuse of `BalanceExportedEvent` (§5), the realtime topic's audience and
its inability to reach an invitee (§4.3), and the public-search premise behind the
§7 security control.

**Accepted with amendment.** Constraint Guardian #7 (public resolver). The finding
that the exact-match rationale was false is accepted in full: `/api/v1/users/search`
is already `AuthNone`, so player enumeration is intentional platform behaviour and
exact-match is not a security control. Amendment: exact-match is **retained as the
default interaction** (entering a known teammate is the common case) while the real
controls become the fail-closed limiter and the pending-invite cap. The reviewer's
conclusion is adopted; only its framing of exact-match as useless is narrowed.

**Escalated rather than arbitrated.** User Advocate #1 and #8 each showed a *locked*
decision resting on a false premise — decision 3 assumed an in-app inbox that does
not exist, and decision 5 had no answer for a `flex` slot's rank. The Arbiter may
not silently reopen a locked decision, so both went back to the organizer and became
decisions 17 and 18.

**Nothing was rejected.** Every objection was either evidence-backed and adopted, or
adopted with the narrowing recorded above.

### Exit criteria

- Understanding Lock completed and explicitly confirmed — ✅
- All three reviewer roles invoked, in order, with revisions between rounds — ✅
- All objections resolved or explicitly narrowed; none left open — ✅
- Decision Log complete (18 decisions with rejected alternatives, §1) — ✅
- Arbiter declares the design acceptable — ✅

**Disposition: APPROVED for implementation**, conditional on two release gates that
are not negotiable, both of which exist because the first draft was wrong in the
*silent* direction:

1. §10 step 2 ships **alone and expand/contract-split**, with the §6 backfill
   equivalence test green for all four cases, before any team-registration code.
2. The export **failure-path** test ("a failed export leaves the prior teams
   intact", §5) is green before step 5.
