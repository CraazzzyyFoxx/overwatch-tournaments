# Encounter Captain Reports Rework

**Date:** 2026-07-18
**Status:** Design approved (brainstorming complete), ready for implementation
**Author:** design facilitated via `superpowers/brainstorming`

## 1. Problem / Understanding Summary

- **What:** replace the single-slot, blocking encounter result flow with a
  dedicated per-captain report table. Each captain independently submits their
  own report: series score (`home:away`), a closeness rating (1..10), and
  per-map match codes (replay codes). Both reports are visible separately.
- **Why:** today captain A calls `submit_match_report` → encounter goes
  `PENDING_CONFIRMATION`; captain B can only confirm/dispute and **cannot record
  their own closeness rating**. We want independent reports + a final closeness
  computed as the average.
- **Who:** the two teams' captains (auth via `team.captain_id → players.user`),
  and admins (dispute resolution / overrides).
- **Finalization:** when both captains have reported and their `home:away`
  scores match → `result_status=CONFIRMED` automatically (via existing
  `finalize_encounter_score`, which propagates bracket advancement), and
  `Encounter.closeness = avg(both closeness)/10`. If scores differ →
  `DISPUTED`, resolved by admin.
- **Editing:** a captain may re-submit (upsert) their report while the encounter
  is not `CONFIRMED`; after confirmation, edits are admin-only.
- **Map pool integration:** per-map codes unify with the map-veto pool when one
  exists. Map pool is **optional** — the same report UX works with or without a
  pool. When the pool is complete, code slot `map_index` resolves to the PICKED
  map at that pick `order` (soft binding).
- **Clean cutover:** remove old RPC `submit_result` / `confirm_result` / old
  `submit_match_report` / `dispute_result` and their gateway routes; replace with
  a new report endpoint + a reports read endpoint. `Encounter.closeness /
  home_score / away_score / result_status` remain as **derived final** fields.

## 2. Assumptions

1. **NFR/scale:** internal tournament platform, low traffic. Concurrent double
   submission is serialized by the existing `with_for_update` lock on the
   encounter row. Encounter cache (`encounters:*`) and realtime/recalc events
   are invalidated as they are today on finalize.
2. **Map codes:** free string (e.g. 6-char OW replay code), optional; number of
   code rows ≤ `best_of`; binding `report → map_index (1-based) → (map_id?, code)`.
   Format validation is soft (not blocking).
3. **Per-map scores are NOT entered** — only the series score.
4. **Disputes are automatic** on score mismatch; there is no separate captain
   "dispute" button/endpoint anymore. `admin_confirm_result` remains for
   resolving disputes.
5. **Closeness is required** in each report (1..10); score required; codes
   optional.
6. **`Encounter.closeness = NULL` until CONFIRMED**; the avg is written only on
   auto-CONFIRMED (and admin dispute-resolve). Individual captain closeness
   values always live in the report table and are always visible.
7. Challonge auto-push (`auto_push_on_confirm`) fires on auto-CONFIRMED, exactly
   as it does on confirm today.
8. Map-pool binding is **soft** (resolve `map_id` where possible, never 4xx on a
   `map_index` beyond the picked count).

## 3. Decision Log

| # | Decision | Alternatives | Why |
|---|---|---|---|
| D1 | Both captains report independently; auto-CONFIRMED on matching score, else DISPUTED | admin-always-finalizes; first-sets-score-second-adds-closeness | Least manual work, clear agreement, satisfies "both can rate closeness" |
| D2 | Report = series score + closeness + list of per-map codes | full per-map breakdown; closeness+codes only (shared score) | Simple, covers the ask; avoids cross-report per-map reconciliation |
| D3 | Upsert while not CONFIRMED; admin-only after | upsert-always (re-opens result); one-shot no-edit | Fixes typos safely without re-opening finished brackets |
| D4 | Clean cutover: remove old RPC, backfill new table | keep legacy side-by-side; no backfill | Repo rules favor clean cutover; single source of truth |
| D5 | Two relational tables (`encounter_captain_report` + `encounter_map_code`) | single table w/ JSONB codes; reuse `matches.match` | Normalized, queryable codes, clean constraints; matches table is log-sourced |
| D6 | Store `team_id` (not a `side` enum) on the report | `side` enum home/away | Directly identifies team; robust to orientation. Side derived from `encounter.home_team_id` |
| D7 | `Encounter.closeness = NULL` until CONFIRMED; avg only on confirm | avg always over available reports | Keeps final closeness meaningful for stats |
| D8 | Map pool integration is optional + soft binding | required pool; strict index↔pick validation | Unifies map UX without coupling; tolerant to partial/changed pools |
| D9 | Denormalize `team_id` onto `EncounterMapPool` (alongside `picked_by`); do NOT rewrite veto to team_id | full veto rewrite to team_id; side-only + helper | Veto is positional (turn/seed) and needs a non-team `decider`; denorm exposes team_id in the pool without touching turn logic |

## 4. Data Model

Both tables live in the `tournament` Postgres schema (like `encounter`), inherit
`TimeStampIntegerMixin` (`id BigInteger`, `created_at`, `updated_at`).

### `tournament.encounter_captain_report`
| column | type | notes |
|---|---|---|
| `encounter_id` | FK → `tournament.encounter.id` `ON DELETE CASCADE`, index | |
| `team_id` | FK → `tournament.team.id` `ON DELETE CASCADE` | reporting captain's team; validated as one of home/away |
| `reporter_user_id` | FK → `identity`.`user.id` `ON DELETE SET NULL`, nullable | who submitted |
| `home_score` | Integer, `CHECK >= 0` | series score (encounter orientation) |
| `away_score` | Integer, `CHECK >= 0` | |
| `closeness` | Integer, `CHECK 1..10` | |

Constraints: `UNIQUE(encounter_id, team_id)`; `CHECK (closeness BETWEEN 1 AND 10)`;
`CHECK (home_score >= 0 AND away_score >= 0)`.

### `tournament.encounter_map_code`
| column | type | notes |
|---|---|---|
| `report_id` | FK → `encounter_captain_report.id` `ON DELETE CASCADE`, index | |
| `map_index` | Integer, `CHECK >= 1` | 1-based map number in the series |
| `map_id` | FK → `overwatch.map.id` `ON DELETE SET NULL`, nullable | resolved from picked pool when present |
| `code` | String(32) | replay/match code, free text |

Constraints: `UNIQUE(report_id, map_index)`.

`Encounter` gains a read relationship `captain_reports: list[EncounterCaptainReport]`.
No new columns on `Encounter`.
### `tournament.encounter_map_pool` (amendment)
Add a denormalized, nullable `team_id` FK → `tournament.team.id` `ON DELETE SET
NULL` next to the existing `picked_by: MapPickSide`. It mirrors `picked_by`:
PICKED+`home` → `encounter.home_team_id`, PICKED+`away` → `encounter.away_team_id`,
`decider`/banned/available → `NULL`. `picked_by` stays authoritative for the veto
sequence and the `decider` marker; `team_id` is a convenience denorm so the pool
(and report UI) can identify the picking team directly. It is populated on the
pick branch of `perform_veto_action` and left `NULL` for decider auto-completion,
and surfaced by `serialize_map_pool_entry`.

## 5. Service Logic

New `submit_captain_report(session, auth_user, encounter_id, home_score,
away_score, closeness, map_codes)`:

1. `_load_encounter` (`with_for_update`) + eager-load `captain_reports` and
   teams.
2. Resolve reporter `team_id` via an extended `_resolve_captain_identity`
   (returns `(side, captain_user_id, team_id)`). Non-captain → 403.
3. Gate: `result_status == CONFIRMED` → 400 (admin-only after confirm).
   `NONE`/`PENDING_CONFIRMATION`/`DISPUTED` → allowed (upsert).
4. Upsert the report by `(encounter_id, team_id)`: overwrite score/closeness.
   Map codes: delete-all + reinsert (idempotent replace). Resolve each code's
   `map_id` softly from the completed map pool (PICKED entry with `order ==
   map_index`); else `map_id = NULL`.
5. `_recompute_encounter_result`:
   - < 2 reports → `result_status=PENDING_CONFIRMATION`,
     `submitted_by_id=reporter`, `Encounter.closeness=None`; no finalize.
   - 2 reports, scores match → `finalize_encounter_score(..., source="captain",
     result_status=CONFIRMED, confirmed_by_id=reporter)`;
     `Encounter.closeness = avg(both closeness)/10`; enqueue recalc +
     `EncounterCompletedEvent`; Challonge auto-push.
   - 2 reports, scores differ → `result_status=DISPUTED`,
     `Encounter.closeness=None`; no finalize.
6. commit + refresh.

Admin dispute resolution keeps using the existing admin encounter edit
(set score/closeness) + `admin_confirm_result` (which also sets
`Encounter.closeness` from avg when reports exist, otherwise leaves the admin's
value).

## 6. API / RPC / Gateway

**New:**
- `rpc.tournament.captain_submit_report` → `POST /api/v1/encounters/{encounter_id}/report`
  (AuthRequired, Body). Body: `{home_score, away_score, closeness, map_codes:
  [{map_index, code}]}`. Returns `{id, result_status, home_score, away_score,
  closeness, reports: [<both reports w/ codes>]}`.
- `rpc.tournament.captain_reports` → `GET /api/v1/encounters/{encounter_id}/reports`
  (AuthOptional). Returns both reports (team_id, reporter, score, closeness,
  codes) for separate display.

**Removed (clean cutover):** RPC `captain_submit_result`,
`captain_confirm_result`, `captain_submit_match_report`,
`captain_dispute_result` + their gateway routes (`submit-result`,
`submit-match-report`, `confirm-result`, `dispute-result`) + `schemas.json` and
`openapi_docs.py` entries.

**Kept:** `admin_confirm_result`; admin encounter edit.

New pydantic schemas in `schemas/captain.py`: `CaptainReportSubmission`
(`home_score`, `away_score`, `closeness` 1..10, `map_codes:
list[CaptainMapCode]`) and read schemas `CaptainReportRead` / `CaptainMapCodeRead`.

## 7. Migration + Backfill

Alembic migration `captreport0001_add_encounter_captain_reports.py`:
- Create both tables in `tournament` schema (FKs, uniques, checks, FK indexes),
  with a full `downgrade`.
- **Backfill** (`INSERT … SELECT`): for encounters with `submitted_by_id IS NOT
  NULL`, insert one report: `reporter_user_id = submitted_by_id`, `team_id` =
  the team whose `captain_id` maps to the player linked to `submitted_by_id`
  (join `team` ↔ `players.user`), `home_score/away_score` from the encounter,
  `closeness = round(encounter.closeness*10)` when non-null. No map codes.
  Skip (log) when the team cannot be resolved. Do NOT touch `Encounter` final
  fields (already finalized).
- **`encounter_map_pool.team_id`:** add the nullable FK column; backfill existing
  rows from the encounter — `picked_by='home'` → `home_team_id`,
  `picked_by='away'` → `away_team_id`, else `NULL`. Downgrade drops the column.

## 8. Frontend

- `captain.service.ts`: remove `submitResult`, `confirmResult`, old
  `submitMatchReport`; add `submitReport(encId, payload)` and `getReports(encId)`;
  keep `getMapPoolState`.
- `MatchReportDialog.tsx`: new payload — score, closeness 1..10, dynamic map-code
  slots driven by `getMapPoolState` (picks → named slots; no pool → `best_of`
  unnamed). Shows both reports (own editable, other read-only) + final/status.
- `ResultSubmission.tsx`: drop submit/confirm-result; show both reports + report
  button (opens the dialog).
- `TournamentBracketPage.tsx` / `BracketView.tsx`: remove `onConfirm`/`canConfirm`;
  `canReport` when `result_status ∈ {none, pending_confirmation, disputed}`.
- i18n `en/ru.json`: new keys (`matchReport.mapCodes`, `bothReports`,
  `avgCloseness`, `autoDisputed`…); remove unused confirm keys; keep `matchEdit.*`.
- `types`: add `CaptainReport` (`team_id`, reporter, score, closeness, `map_codes[]`).

## 9. Testing

- **Backend** `tests/test_captain_report.py` (mirrors `test_captain_match_report.py`):
  first report → PENDING + `encounter.closeness=None`; second matching →
  CONFIRMED + `closeness=avg/10` + finalize/advancement + recalc/event enqueued;
  second mismatching → DISPUTED + `closeness=None`; upsert own before confirm
  (replaces score/closeness/codes); 403 non-captain; 400 after CONFIRMED; 422
  closeness out of range; codes: `map_id` resolved from PICKED pool, no pool →
  `map_id=NULL`, extra `map_index` → `map_id=NULL` (soft); correct `team_id`.
- **Frontend** (vitest): update tests referencing removed flows; add a test for
  building map slots from pool state.
- **Migration**: upgrade/downgrade compile + backfill query sanity.

## 10. Out of Scope (YAGNI)

- Per-map score entry.
- Dispute reasons / dispute chat.
- Manual confirm button (auto-confirm replaces it).
- Strict map-pool ↔ code index validation.
