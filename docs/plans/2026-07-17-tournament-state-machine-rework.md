# Tournament State Machine Rework: Time-Driven Phase Transitions

**Date:** 2026-07-17
**Status:** Implemented and verified (2026-07-17)

## Understanding Summary

- **What:** Rework the tournament state machine so that (1) new tournaments start in
  `REGISTRATION` instead of `DRAFT`; (2) statuses auto-advance on a schedule stored in a
  dedicated table; (3) action availability (registration, check-in, draft) is gated by
  status as the single source of truth.
- **Why:** Today a freshly created tournament lands in `DRAFT` and can never legally
  transition to `REGISTRATION` (no such edge in the machine). Time fields exist on the
  tournament but never move the status. The truth about "is registration open" is
  scattered across the registration form (`is_open`/`opens_at`/`closes_at`), tournament
  timestamps, and status.
- **Who:** Workspace admins (fewer manual switches) and players (registration/check-in
  open on time automatically).
- **Non-goals:** `DraftStatus` (draft-session machine) untouched; no auto-completion by
  `end_date`; `is_hidden`/preview mode untouched; no new gates on encounter/result
  editing (admins fix results after completion — must keep working).

## Assumptions (NFR)

1. **Tick:** APScheduler job in the existing tournament-worker `serve.py` scheduler,
   every 30 s. Switching precision of ±1 minute is acceptable.
2. **Scale:** tens of active tournaments — one indexed query per tick.
3. **Concurrency:** single worker today, but the job is idempotent and uses
   `FOR UPDATE SKIP LOCKED`, so replicas/restarts are safe.
4. **Events:** auto-transitions go through the same `transition_status` path as manual
   ones — same outbox events, cache invalidation, and group-stage auto-generation.
5. **Data migration:** no balancer tournaments currently sit in `DRAFT` (confirmed by
   user); the migration stays defensive but performs no status rewrites.

## Decision Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | `DRAFT` = team-draft phase (between REGISTRATION and CHECK_IN), skipped for `team_formation="balancer"` | Remove DRAFT entirely; repurpose DRAFT as pre-publication draft | Draft phase is a real lifecycle stage for draft tournaments; "unpublished" is already covered by orthogonal `is_hidden` |
| 2 | "Stages depend on state" = **action gating by status** (registration, check-in, draft session start) | Stage-entity activation; UI sections only | User selection; status becomes the single source of truth for what is currently possible |
| 3 | Time drives transitions **only up to LIVE**; `PLAYOFFS`/`COMPLETED` stay manual/event-driven | Auto-complete on `end_date` | Tournaments regularly overrun; automation must not close a tournament mid-final |
| 4 | Automation moves **forward only**; any manual transition sets the tournament to manual mode (`auto_transitions_enabled = false`) until an admin re-enables it | Always-active automation (rollback requires moving timestamps); fully automatic (no manual control below LIVE) | Admin rollback (e.g. extend registration) must not be instantly overridden by the next tick |
| 5 | Registration openness derives from status + `allow_late_registration` flag; `form.is_open` remains only as an emergency kill switch; form `opens_at`/`closes_at` removed | Form stays independent; automation mutates `form.is_open` on status change | One clear contract; supports "registration stays open during the tournament" |
| 6 | Schedule lives in a dedicated `tournament_phase_schedule` table; `start_date`/`end_date` remain purely informational | Reuse flat timestamp columns on tournament | User decision: `start_date` is "when the tournament takes place", not a trigger; the table becomes the single home for phase timings |
| 7 | Schedule rows carry `ends_at` (nullable) — closes the phase's **action window** early; it never switches status | starts_at-only rows | User decision: allows gaps between phases (e.g. check-in closes 18:45, matches start 19:00) |
| 8 | Approach A: persisted status + interval tick reusing `transition_status` | B: derived status computed on read; C: per-transition scheduled jobs | B breaks SQL status filters, outbox events, cache invalidation, realtime. C needs persistent jobstores and rescheduling on every date edit. A reuses all existing infrastructure; date edits are picked up on the next tick with zero rescheduling |
| 9 | Existing tournaments get `auto_transitions_enabled = false` on migration; new tournaments default `true` | Enable for all | Deploy safety: nothing flips status unexpectedly on release |
| 10 | Admin-facing auto-mode toggle in UI | Only implicit disable via manual transition | User requirement |

## Final Design

### 1. State machine (`shared/core/tournament_state.py`)

New transition matrix — forward edges allow phase skipping, plus rollback edges
to prior effective phases for admins **without** `force`:

```
REGISTRATION → CHECK_IN | DRAFT | LIVE
CHECK_IN     → DRAFT | LIVE | REGISTRATION          (back)
DRAFT        → LIVE | CHECK_IN | REGISTRATION       (back)
LIVE         → PLAYOFFS | COMPLETED | DRAFT | CHECK_IN (back)
PLAYOFFS     → COMPLETED
COMPLETED    ⇄ ARCHIVED
```

New pure helpers next to the matrix:

- `PHASE_ORDER` — canonical ordering of the pre-terminal phases.
- `next_due_status(current, schedule_rows, now)` — returns the **latest by phase order**
  scheduled phase with `starts_at <= now` that is strictly ahead of `current`, else
  `None`. One direct transition (skips are legal per matrix).

Initial status: `REGISTRATION` — model default, `server_default`, and
`TournamentCreate` schema default all change from `DRAFT`.

### 2. Schedule table

```
tournament.tournament_phase_schedule
  id             PK
  tournament_id  FK → tournament.tournament(id) ON DELETE CASCADE
  status         tournamentstatus   -- target phase; allowed: REGISTRATION, CHECK_IN, DRAFT, LIVE
  starts_at      timestamptz NOT NULL
  ends_at        timestamptz NULL   -- NULL = "until the next phase starts"
  created_at / updated_at
  UNIQUE (tournament_id, status)
  CHECK  (ends_at IS NULL OR ends_at > starts_at)
  INDEX  (starts_at)
```

**Two-level semantics (key invariant):**

1. Only `starts_at` switches status — forward, monotonic. `ends_at` never changes
   status (there is no "between phases" status in the enum).
2. `ends_at` closes the phase's *action window*: an action is available iff
   `status == X` **and** `now` is inside `[starts_at, ends_at]` of the row for X
   (no row / `ends_at IS NULL` → window equals the whole phase).

A `REGISTRATION` row is legal and useful: its `starts_at` opens the form later than
creation, its `ends_at` closes it before the next phase. This fully replaces the
dropped `registration_opens_at/closes_at` and `check_in_opens_at/closes_at` columns.

`PLAYOFFS`/`COMPLETED` rows are rejected by validation (manual phases).

### 3. Gating (status = source of truth)

- **Registration** (`registration/service.py::register_participant` — currently checks
  only `form.is_open`):

  ```
  open ⟺ form.is_open                                  # admin kill switch
       ∧ status ∉ {COMPLETED, ARCHIVED}
       ∧ ( status == REGISTRATION ∧ now ∈ window(REGISTRATION row, if any)
         ∨ tournament.allow_late_registration )
  ```

- **Check-in:** `is_check_in_window_active` is duplicated in
  `registration/lifecycle.py` and `registration/service.py` — collapse into one shared
  helper; logic becomes `status == CHECK_IN ∧ now ∈ window(CHECK_IN row)`.
- **Draft session** (`balancer-service` — currently no tournament-status check):
  creating/seeding a session stays allowed ahead of time; *starting* the draft
  (session `READY → LIVE`) requires `tournament.status == DRAFT`.
- **Encounters/results:** explicitly ungated (non-goal).

### 4. Tick job

New module `src/services/tournament/auto_transitions.py`, registered in the
tournament-worker `serve.py` scheduler (30 s interval, next to `drain_outbox`):

```sql
SELECT t.* FROM tournament.tournament t
WHERE t.auto_transitions_enabled
  AND t.status IN ('registration','draft','check_in')
  AND EXISTS (SELECT 1 FROM tournament.tournament_phase_schedule s
              WHERE s.tournament_id = t.id AND s.starts_at <= now())
FOR UPDATE OF t SKIP LOCKED
```

Per candidate: `next_due_status(...)`; if due — call the existing
`transition_status(session, id, target)` (matrix validation, outbox
`tournament_state_changed`, cache invalidation, `_maybe_auto_start_group_stage` on
LIVE). Coarse SQL filter + precise pure function; no logic duplication.

- **Error isolation:** one transaction per tournament; exceptions logged, loop
  continues (pattern of `sync_due_google_sheet_feeds`).
- **Idempotency:** forward-only + unique schedule rows + re-reads current status;
  `SKIP LOCKED` covers concurrent replicas.
- **Pause:** manual `tournament_status` RPC sets `auto_transitions_enabled = false` in
  the same transaction. Re-enabling (tournament update) lets the next tick catch up on
  overdue phases immediately — expected behavior, UI warns about it.
- **Observability:** structlog line per auto-transition
  (`tournament_id`, `old → new`, `scheduled_at`, `lag`).

### 5. API surface

- **Model:** `TournamentPhaseSchedule` in `shared/models/tournament/`.
- **Tournament columns:** `+ auto_transitions_enabled` (default `true`; backfill
  `false` for existing rows), `+ allow_late_registration` (default `false`);
  `status` server_default → `'registration'`; **drop**
  `registration_opens_at`, `registration_closes_at`, `check_in_opens_at`,
  `check_in_closes_at`.
- **Registration form:** drop `opens_at`, `closes_at` (model, `RegistrationFormUpsert`,
  `admin_use_cases.py`, `serializers.py`, `registration_build.py`).
- **Migration:** converts old windows into schedule rows
  (`check_in_opens_at/closes_at` → `CHECK_IN` row;
  `registration_opens_at/closes_at` → `REGISTRATION` row). Enum unchanged.
- **RPC:** new `rpc.tournament.tournament_schedule_set` — bulk upsert (full replace) of
  the tournament's schedule rows; validation: allowed phases only,
  `ends_at > starts_at`, `starts_at` monotonic in phase order. Register in
  `openapi_docs.py` / `openapi_schemas.py`. Schedule + both flags included in
  `TournamentRead`; flags edited via existing tournament update.
- **Mirrors:** `parser-service/src/services/admin/tournament.py` duplicates
  `transition_status` / `_maybe_auto_start_group_stage` — mirror the changes there.

### 6. Frontend

- `tournament.types.ts`: remove the 4 dropped fields; add `phase_schedule[]`,
  `auto_transitions_enabled`, `allow_late_registration`.
- Admin tournament form: schedule editor (one row per phase with start/end pickers),
  "Auto mode" toggle (warn: enabling immediately catches up overdue phases), late
  registration toggle.
- `TournamentRegisterButton`, `TournamentParticipantsPage::isCheckInWindowActive`,
  `tournamentOverview` — switch to the new model (window from schedule row, status is
  truth). Default status in creation flows → `registration`.

### 7. Testing strategy

- Unit: `next_due_status` (phase skipping, no-row, overdue multiple phases, manual-mode
  exclusion), new transition matrix (forward skips, one-back rollbacks, rejected
  PLAYOFFS/COMPLETED scheduling), gating helpers (registration window × late-reg flag ×
  kill switch; check-in window with `ends_at` gap).
- Integration: tick job transitions a due tournament and emits
  `tournament_state_changed`; manual transition pauses automation; re-enable catches
  up; `SKIP LOCKED` no-double-fire.
- Existing suites to update: `test_registration_self_register_gate`,
  `test_preview_access_admin`, `test_tournament_visibility_reads` (DRAFT defaults),
  frontend `tournament-section-nav.test`, `tournamentOverview.behavior.test`.
