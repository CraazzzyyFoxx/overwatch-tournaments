# Users Compare Redesign and Performance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move `/users/compare` onto the shared Editorial Tactical page system and reduce compare latency with set-based SQL plus short-lived Redis response caching.

**Architecture:** Preserve the public response models while replacing population-wide correlated-query/Python processing with grouped SQLAlchemy CTEs. Wrap successful responses in versioned cashews keys with lock-based stampede protection and existing event-driven invalidation. Rebuild the page header with `PageHero`, lazy-load scope-specific catalogs, and propagate TanStack Query cancellation signals to `apiFetch`.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind 4, next-intl, TanStack Query 5, Python 3.13, SQLAlchemy 2, PostgreSQL, cashews/Redis, pytest, Vitest, ESLint.

---

## Constraints

- Follow TDD: each behavior test must fail for the expected reason before production code is added.
- Preserve API schemas, formulas, validation errors, and URL semantics.
- Do not run `next build`; frontend verification uses tests and lint.
- Do not run load tests against production.
- Do not create commits unless the user explicitly requests them.

### Task 1: Capture the current contract and baseline

**Files:**
- Modify: `backend/app-service/tests/api/routes/test_user.py`
- Create: `backend/app-service/tests/test_user_compare_performance_contract.py`

**Steps:**

1. Add focused assertions for global/cohort/target and Hero/Map `None`, zero, tie, rank, percentile, and 600-second eligibility semantics.
2. Add a query-construction test that describes the desired v2 interface and asserts the population query does not expose one correlated scalar subquery per metric.
3. Run the focused test and confirm the v2 test fails because the new query helper does not exist.
4. If the local non-production database is available, time the existing global/cohort/target/Hero RPC tests and record the baseline; otherwise record the guarded skip.

Run:

```powershell
uv run --project backend/app-service pytest backend/app-service/tests/test_user_compare_performance_contract.py -v
uv run --project backend/app-service pytest backend/app-service/tests/api/routes/test_user.py -k "compare" -v --durations=20
```

### Task 2: Implement set-based Overall comparison

**Files:**
- Modify: `backend/app-service/src/services/user/service.py`
- Modify: `backend/app-service/src/services/user/flows.py`
- Modify: `backend/app-service/tests/test_user_compare_performance_contract.py`
- Modify: `backend/app-service/tests/api/routes/test_user.py`

**Steps:**

1. Add a failing parity test that compares legacy population output with the v2 result for target, global, and cohort fixtures.
2. Add `_compare_candidate_users_cte` and grouped CTE builders for tournament, achievement, map, placement, closeness, and match-stat aggregates.
3. Add `get_compare_summary_v2` returning only subject/baseline/sample/rank data required by the response.
4. Update `get_compare` to consume the compact summary while retaining the legacy helpers as a test oracle.
5. Run parity and existing RPC tests; refactor only after green.

Run:

```powershell
uv run --project backend/app-service pytest backend/app-service/tests/test_user_compare_performance_contract.py -k "overall or parity" -v
uv run --project backend/app-service pytest backend/app-service/tests/api/routes/test_user.py -k "get_user_compare" -v
```

### Task 3: Implement set-based Hero/Map comparison

**Files:**
- Modify: `backend/app-service/src/services/user/service.py`
- Modify: `backend/app-service/src/services/user/flows.py`
- Modify: `backend/app-service/tests/test_user_compare_performance_contract.py`
- Modify: `backend/app-service/tests/api/routes/test_user.py`

**Steps:**

1. Add failing parity tests for target, global, cohort, no hero filter, map filter, ascending stat, and sub-600-second playtime.
2. Add one grouped v2 aggregation for playtime and requested stats over the candidate user set.
3. Batch-load requested hero/map metadata.
4. Switch `get_hero_compare` to the v2 path while preserving response construction and the legacy oracle.
5. Run focused Hero compare tests and refactor after green.

Run:

```powershell
uv run --project backend/app-service pytest backend/app-service/tests/test_user_compare_performance_contract.py -k "hero" -v
uv run --project backend/app-service pytest backend/app-service/tests/api/routes/test_user.py -k "hero_compare" -v
```

### Task 4: Add Redis caching and invalidation

**Files:**
- Modify: `backend/app-service/src/services/user/flows.py`
- Modify: `backend/app-service/src/services/tournament_events.py`
- Modify: `backend/app-service/src/services/admin/user_merge.py`
- Modify: `backend/app-service/tests/test_tournament_recalculation_events.py`
- Modify: `backend/app-service/tests/test_user_merge_workspace_member.py`
- Create: `backend/app-service/tests/test_user_compare_cache.py`

**Steps:**

1. Add failing tests for deterministic normalized cache keys, versioned namespaces, hit behavior, `lock=True`, unsuccessful-response exclusion, and Redis failure fallback.
2. Add cached internal compare functions accepting only explicit primitive key fields plus runtime-only session/grid arguments.
3. Include `grid.version_id`, normalized optional filters, and sorted stats in keys.
4. Add `backend:user_compare:v2:*` and `backend:user_hero_compare:v2:*` to tournament and merge invalidation.
5. Add invalidation coverage and run cache/event tests.

Run:

```powershell
uv run --project backend/app-service pytest backend/app-service/tests/test_user_compare_cache.py backend/app-service/tests/test_tournament_recalculation_events.py -v
uv run --project backend/app-service pytest backend/app-service/tests/test_user_merge_workspace_member.py -k "cache" -v
```

### Task 5: Add frontend cancellation and scope-aware fetching

**Files:**
- Modify: `frontend/src/services/user.service.ts`
- Modify: `frontend/src/app/(site)/users/compare/hooks/useUserCompareData.ts`
- Modify: `frontend/vitest.config.ts`
- Create: `frontend/src/app/(site)/users/compare/hooks/compare-query-options.ts`
- Create: `frontend/src/app/(site)/users/compare/hooks/compare-query-options.test.ts`

**Steps:**

1. Add failing pure tests for query options: signal forwarding, previous-data placeholder, Hero/Map catalog enablement, and initial-vs-background loading flags.
2. Extract pure query-option builders used by the hook.
3. Pass TanStack Query's `signal` into `getUserCompare`, `getUserHeroCompare`, and `apiFetch`.
4. Enable heroes/maps only for Hero/Map scope and preserve previous compare data with `placeholderData`.
5. Run compare frontend tests and TypeScript-aware lint.

Run:

```powershell
pnpm --dir frontend exec vitest run "src/app/(site)/users/compare/hooks/compare-query-options.test.ts"
pnpm --dir frontend lint
```

### Task 6: Build the shared PageHero experience

**Files:**
- Create: `frontend/src/app/(site)/users/compare/components/ComparePageHero.tsx`
- Create: `frontend/src/app/(site)/users/compare/components/compare-page-hero.model.ts`
- Create: `frontend/src/app/(site)/users/compare/components/compare-page-hero.model.test.ts`
- Modify: `frontend/src/app/(site)/users/compare/page.tsx`
- Delete: `frontend/src/app/(site)/users/compare/components/ComparePageHeader.tsx`
- Modify: `frontend/src/app/(site)/users/compare/components/CompareUnifiedTable.tsx`
- Modify: `frontend/src/i18n/messages/ru.json`
- Modify: `frontend/src/i18n/messages/en.json`
- Modify: `frontend/vitest.config.ts`

**Steps:**

1. Add failing model tests for no-selection, loading, global/cohort/target, Overall/Hero scope, sample size, and metric count status values.
2. Implement the pure hero model.
3. Implement `ComparePageHero` with `PageHero`, `HeroCoord`, guide popover, and responsive status grid.
4. Replace the old header, wire live query data, and add retry/`aria-busy`/distinct empty states to the result area.
5. Add matching Russian and English strings.
6. Run compare tests and lint.

Run:

```powershell
pnpm --dir frontend exec vitest run "src/app/(site)/users/compare/**/*.test.ts"
pnpm --dir frontend lint
```

### Task 7: Verify performance, parity, and repository hygiene

**Files:**
- Modify only if justified by `EXPLAIN ANALYZE`: PostgreSQL migration and matching SQLAlchemy model index declaration.
- Review: `docs/superpowers/specs/2026-07-15-users-compare-redesign-performance-design.md`

**Steps:**

1. Run the complete focused backend compare suite and cache/invalidation tests.
2. Re-run the same duration command used for baseline and compare cold/warm timings when the guarded test DB is available.
3. Inspect generated SQL/query counts; add an index migration only if evidence identifies a critical sequential scan.
4. Run frontend compare tests and full frontend lint; do not run `next build`.
5. Run `git diff --check`, inspect the final diff, and compare every delivered item to the approved design.

Run:

```powershell
uv run --project backend/app-service pytest backend/app-service/tests/api/routes/test_user.py backend/app-service/tests/api/routes/test_user_compare_validation.py backend/app-service/tests/test_user_compare_performance_contract.py backend/app-service/tests/test_user_compare_cache.py backend/app-service/tests/test_tournament_recalculation_events.py -v --durations=20
pnpm --dir frontend exec vitest run "src/app/(site)/users/compare/**/*.test.ts"
pnpm --dir frontend lint
git diff --check
git status --short
```
