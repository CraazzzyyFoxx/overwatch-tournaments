# Agent launch prompt — registration form schema

Copy everything below the line into a fresh agent session started in the repo root
(`E:/projects/anak-tournaments`). The prompt is self-contained; the agent reads the design and the
plan from disk.

---

You are implementing an approved architectural change in the OWT monorepo (Python backend
services + Next.js frontend + Go gateway). Read these two files completely before doing anything
else, in this order:

1. `docs/registration-form-schema/design.md` — the approved design. Every decision in its §1 table
   is final; do not reopen them.
2. `docs/registration-form-schema/plan.md` — the implementation plan: 15 tasks in five phases, each
   with files, interfaces, tests, commands and a commit.

Also read `AGENTS.md`, `CONTRIBUTING.md` and `.claude/CLAUDE.md` at the repo root: they define the
code-intelligence routing (graft / CodeGraph first, grep as fallback) and the test/lint commands.

## What "done" means

All 15 tasks of the plan are implemented, every gate in Task 15 passes, the browser smoke test in
Task 15 has been performed against the running dev stack with the observed behaviour written down,
and the status lines of `design.md` and `plan.md` read `**Status:** implemented (YYYY-MM-DD)`.
Nothing short of that is done: no "phase 1", no "follow-up PR", no TODO, no shim left for later.
If a prerequisite is genuinely missing (a service that cannot start, credentials you do not have),
finish every reachable task and report exactly what is missing and what you tried.

## How to work

- Use the `superpowers:subagent-driven-development` skill if available (one fresh subagent per plan
  task, review between tasks); otherwise `superpowers:executing-plans`. Work strictly in plan order
  — the tasks are dependency-ordered (shared domain → migration/models → backend pipeline →
  readers → templates → frontend types → renderers → builder → consumers → cleanup). Tasks 1+2
  and 8+9 may be committed together, as the plan says.
- Before editing a symbol, run `graft_trace_calls` on it (or `graft callers <symbol>`) and migrate
  every caller in the same task. Missed call sites are bugs, not follow-ups.
- Tests first for every task: write the failing test from the plan, run it, implement, run it
  again. Use the plan's commands verbatim. Do not run the whole monorepo suite between tasks;
  Task 15 does that once.
- Contracts are fixed by the plan's **Interfaces** blocks. Names, field names and codes there are
  shared between backend and frontend (`RegistrationSubmit{form_version_id, answers}`,
  `RegistrationFormRead.form_schema/version_id/version_number/stale_registrations`,
  `RegistrationRead.answers/form_version_id/form_version_stale`, `ApiExc.field`, `RolesParams`
  field names, error codes). If you must deviate, change both sides in the same commit and update
  the plan.
- Clean cutover: delete the legacy code the plan lists (`validation.py`, `UnifiedRegistrationForm`,
  `formConfig.ts::BUILT_IN_FIELDS`, the two JSON columns, the three nick columns). No dual writes,
  no re-exports of deleted types, no `extra="ignore"` tolerance for old wire keys.
- Structured errors only: `ApiHTTPException(status, [ApiExc(msg, code, field)])`. Never raise a
  bare-string 422 from new code.
- Migrations are hand-written Alembic revisions and must not import `shared`; the legacy→schema
  converter lives inside `regform01_form_schema.py` and is covered by the golden test the plan
  specifies. Prove `upgrade → downgrade -1 → upgrade head` on the dev database.
- Regenerate generated artefacts when the plan says so (`docs/database_erd.md`, the gateway
  OpenAPI manifest) and commit them; CI fails when they are stale.
- Commit after every task with the message the plan gives. Do not squash.
- Do not add features the plan does not name (no autosave, no waitlist, no report-form migration,
  no notification of stale registrations). Do not narrow scope silently either: if a task turns out
  larger than written, finish it.

## Report

When everything is green, reply with: the list of commits; the output tail of every gate command
from Task 15 (backend per-service pytest, lint, frontend typecheck/lint/zones/test:split/vitest/bun,
gateway `go test ./...`); what you saw at each step of the browser smoke test; and any deviation
from the plan with its reason.
