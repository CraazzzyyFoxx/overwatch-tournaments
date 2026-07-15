# Users Roster Redesign and Performance Design

**Status:** Approved

**Date:** 2026-07-15

## Understanding summary

- Move the public `/users` roster onto the shared Editorial Tactical design system used by the other site tabs.
- Replace the isolated 1,177-line client screen and 1,050-line CSS module with smaller shared-system components.
- Preserve search, role/division filters, sorting, pagination, URL semantics, table/card views, and links to player profiles.
- Improve mobile behavior, loading/error/empty states, keyboard access, and perceived responsiveness.
- Preserve KPI formulas and workspace isolation while removing sequential and population-wide backend work.
- Keep `/users/[slug]` profile tabs and unrelated user APIs out of scope.

## Assumptions and constraints

- The roster can contain tens of thousands of users and `matches.statistics` is substantially larger.
- The target is API P95 below one second and useful page content within 2.5 seconds, to be validated against real data.
- Production connection details are available through `common.env`.
- Production investigation is read-only: no load test, DDL, writes, or unbounded `EXPLAIN ANALYZE` runs.
- API and URL compatibility must be retained where practical; `view=catalog` remains a valid legacy URL value.
- Frontend verification uses lint and focused tests; per project guidance, do not run `next build`.
- No speculative index is added without an execution plan demonstrating the need.

## Existing-state findings

- The analytics view issues an overview request made of roughly ten sequential SQL statements plus a separate KPI request made of roughly five statements.
- The catalog path loads the complete filtered roster into Python, groups it by first letter, and only then applies per-letter limits. It subsequently runs the same rich row aggregates for a potentially large set.
- KPI calculation materializes every candidate user ID in Python and uses the resulting list in several subsequent queries.
- Hero metrics are computed for every visible row even though they are primarily consumed by expanded details.
- The page uses a null Suspense fallback, so the initial state can appear blank.
- Search/filter changes update the URL and trigger new work without propagating TanStack Query cancellation signals.

## Approaches considered

### 1. Unified paginated roster — selected

Use one paginated data source for table and cards, include first-screen KPIs, and lazy-load rich row details. Build set-based candidate and aggregate queries. This offers the strongest UX and performance improvement without a new operational subsystem.

### 2. Keep the split endpoints

Retain overview, stats, and catalog as independent data paths and optimize each in place. This carries less API change but preserves duplicated state, requests, and maintenance.

### 3. Materialized roster read model

Maintain a precomputed player-statistics projection refreshed by events. This provides the best steady-state latency but adds migration, refresh, recovery, and observability requirements that are not justified for the current scope.

## Design direction

**Aesthetic:** Editorial Tactical / Industrial Utility.

**Purpose:** Let visitors find a player quickly, scan the competitive roster, and understand each player's participation at a glance.

**Differentiation anchor:** A “live roster index” with a strong coordinate number on the left of each player and a restrained role-color signal. It continues the tactical language of the shared `PageHero` without adding decorative noise.

**DFII:** 15/15 (impact 4, context fit 4, feasibility 4, performance safety 4, consistency risk 1).

### Design-system snapshot

- Onest for headings and player identity; JetBrains Mono for coordinates and numeric statistics.
- Existing `--aqt-*` variables only; teal is the primary interactive signal and amber is reserved for warnings.
- Shared `PageHero`, global surface/border tokens, restrained radii, and established site spacing replace local palette aliases.
- Motion is limited to view changes and detail expansion and respects `prefers-reduced-motion`.

## Frontend architecture

The route remains a server page with a meaningful Suspense skeleton. A small client controller owns URL parsing, debounced search, query options, and view selection. Presentation is split into:

- `UsersHero` for filtered KPI status;
- `RosterToolbar` for search, role chips, a single division-range control, sorting, view mode, and reset;
- `RosterTable` for information-dense desktop scanning;
- `RosterCards` for the card mode and narrow viewports;
- an on-demand player-details panel/row with isolated loading and error states.

Both views consume the same page response. The old `catalog` view parameter maps to the new card mode so saved URLs continue to work. Alphabet grouping is removed because it duplicates search and forces population-wide work.

The first request uses a full skeleton. Background refetches retain previous data and display a small busy indicator. Empty results offer “reset filters.” Main and detail failures have independent retry actions. Inputs, tabs, disclosure controls, and live regions receive correct semantics and visible focus states.

TanStack Query's `AbortSignal` is forwarded through `userService` to `apiFetch`, preventing obsolete search requests from continuing after a newer query begins.

## Backend architecture

The existing `/api/v1/users/overview` path becomes the first-screen roster contract. It returns paginated rows, filtered KPIs, and metadata. Each row contains identity, recent role/division data, counts, placement summary, and up to three top heroes, but not expensive per-hero rate metrics.

A focused details endpoint returns the extended hero metrics for one user when their row/card is opened. Details are workspace-scoped and have an independent short-lived cache where safe.

The overview query path starts with one workspace-scoped candidate CTE that applies normalized search, role, and division predicates. Page IDs and the total derive from this candidate set. Tournament counts, achievements, and placement aggregates are set-based and joined/batched against the page IDs. Roles and top heroes remain bounded batch reads. The target first-screen query budget is three to five SQL statements.

KPI aggregation operates in SQL over the candidate CTE. It does not materialize all candidate IDs or calculate median in Python. Only low-cardinality safe responses are cached; arbitrary search strings do not create an unbounded Redis key space. Existing tournament-change invalidation is extended to any new versioned cache namespace.

## Data and compatibility

- Preserve KPI definitions, finished/non-league tournament rules, substitution handling, division normalization, and workspace scoping.
- Preserve existing sort names and pagination response semantics.
- Accept legacy `view=catalog`, but the frontend canonicalizes it to card behavior.
- Reject or normalize invalid division ranges consistently. The UI prevents `min > max`; hand-edited URLs are normalized before fetching.
- Do not add an index until the real execution plan shows a critical scan not addressed by the query rewrite.

## Production-safe baseline

Use the production connection from `common.env` only for bounded, read-only inspection. Start with query cardinalities and `EXPLAIN (FORMAT JSON)` without `ANALYZE`. Run `EXPLAIN ANALYZE` only for a bounded representative SELECT after confirming the plan is safe, with statement/lock timeouts and a read-only transaction. Never run concurrency or stress tests against production.

Record cold/warm endpoint timings, query count, returned row count, and response size before and after the rewrite. Do not claim millisecond improvements that were not measured.

## Error handling and edge cases

- Players with no tournaments, logs, achievements, role, division, or heroes remain valid rows with explicit empty values.
- A details error affects only the opened player.
- A main response error retains retryable page context and does not silently fall back to unscoped data.
- Stale background data remains visible and is marked busy rather than replaced with a full skeleton.
- Page numbers outside the new result range are clamped/reset after filter changes.
- Workspace changes participate in every query/cache key and reset roster pagination.

## Verification strategy

- Route-contract tests for the expanded overview and detail response.
- Regression tests for workspace scope, division normalization, legacy view parsing, and current KPI formulas.
- Aggregate tests covering zero-tournament/log players and median behavior.
- Query-budget coverage for the first-screen response.
- Frontend pure tests for URL parsing, query-option cancellation, reset behavior, and view compatibility.
- Focused backend pytest suites, frontend Vitest suites, full frontend lint, and `git diff --check`.
- Manual desktop/mobile, keyboard, focus, loading, retry, empty-state, and reduced-motion checks.
- Bounded read-only production `EXPLAIN`/timing comparison following the safety rules above.

## Decision log

1. Selected a unified paginated roster instead of preserving split analytics/catalog data paths.
2. Kept table and card modes, but made them projections of the same response.
3. Removed alphabet grouping because it duplicates search and drives population-wide work.
4. Deferred rich hero metrics until user disclosure.
5. Preserved business formulas, workspace isolation, route identity, sort names, and legacy view URLs.
6. Reused the shared Editorial Tactical system rather than extending the local CSS island.
7. Set a first-screen query budget of three to five statements.
8. Allowed real-data profiling through `common.env` under strict read-only, bounded production safeguards.
