# Homepage Workspace-Scoping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On white-label tenant hosts (workspace subdomains and verified custom domains), the main page and `/statistics` show data scoped to that one workspace instead of the platform-wide aggregate.

**Architecture:** The scoping machinery already exists — `apiFetch` auto-injects `workspace_id` from the `x-owt-workspace-id` header (set by `middleware.ts` on tenant hosts), and every backend statistics/tournament-list endpoint filters by it. The two dashboard pages currently opt out with a hardcoded `skipWorkspace: true`. We flip that opt-out to `skipWorkspace = !isTenantHost()`: unchanged on apex, workspace-scoped on tenant hosts. Frontend-only.

**Tech Stack:** Next.js App Router (server components), TypeScript, `bun test` (bun:test), Next `next/headers`.

**Spec:** `docs/superpowers/specs/2026-07-11-homepage-workspace-scoping-design.md`

## Global Constraints

- **Frontend-only.** No backend changes — all endpoints already filter by `workspace_id`.
- **Apex behaviour is preserved byte-for-byte.** On the platform host `isTenantHost()` is `false` → `skipWorkspace: true` → global aggregate, exactly as today.
- **`getActive()` keeps `skipWorkspace: true` as its default**, so its two other callers (`(site)/workspace/[slug]/page.tsx:244`, `components/ActiveEvents.tsx:36`) are unaffected.
- **Verify with `bunx tsc --noEmit`, not `next build`** — the build's TS phase stops at the first file and masks later errors.
- **Working tree is dirty with an unrelated user-profile redesign on `develop`.** Stage ONLY the files each task lists (explicit pathspecs) — never `git add -A` / `git add .` / `git add -u`.
- All commands run from `frontend/` unless stated otherwise.

---

## Task 0: Branch

- [ ] **Step 1: Create the feature branch off develop**

From the repo root:

```bash
git checkout -b feature/homepage-workspace-scoping
```

Expected: switched to a new branch. The unrelated modified files remain in the working tree, unstaged — leave them alone.

---

## Task 1: `isTenantHost()` server helper

**Files:**
- Create: `frontend/src/lib/tenant-host.ts`
- Test: `frontend/src/lib/tenant-host.test.ts`

**Interfaces:**
- Consumes: `headers` from `next/headers`.
- Produces: `export async function isTenantHost(): Promise<boolean>` — `true` iff the `x-owt-host-mode` request header equals `"tenant"`; fail-safe `false` on any error. Tasks 3 and 4 depend on this exact name and signature.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/tenant-host.test.ts`:

```ts
import { beforeEach, describe, expect, it, mock } from "bun:test";

// Mirrors the mock.module("next/headers", ...) pattern used by the
// /auth/sso route test — lets us drive the request header from the test.
let requestHeaders: Record<string, string | undefined> = {};

mock.module("next/headers", () => ({
  headers: async () => ({
    get: (name: string) => requestHeaders[name] ?? null,
  }),
}));

const { isTenantHost } = await import("./tenant-host");

describe("isTenantHost", () => {
  beforeEach(() => {
    requestHeaders = {};
  });

  it("returns true when x-owt-host-mode is 'tenant'", async () => {
    requestHeaders["x-owt-host-mode"] = "tenant";
    expect(await isTenantHost()).toBe(true);
  });

  it("returns false when the header is absent (platform host)", async () => {
    expect(await isTenantHost()).toBe(false);
  });

  it("returns false for any non-'tenant' value", async () => {
    requestHeaders["x-owt-host-mode"] = "platform";
    expect(await isTenantHost()).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bun test src/lib/tenant-host.test.ts`
Expected: FAIL — cannot resolve module `./tenant-host` (file not created yet).

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/tenant-host.ts`:

```ts
import { headers } from "next/headers";

/**
 * True when the current request is served on a white-label tenant host — a
 * workspace subdomain or a verified custom domain — per the `x-owt-host-mode`
 * header that `middleware.ts` sets (and strips on the platform apex). Server-only.
 *
 * Fail-safe: returns `false` (platform behaviour) if headers are unavailable.
 */
export async function isTenantHost(): Promise<boolean> {
  try {
    return (await headers()).get("x-owt-host-mode") === "tenant";
  } catch {
    return false;
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bun test src/lib/tenant-host.test.ts`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/tenant-host.ts frontend/src/lib/tenant-host.test.ts
git commit -m "feat(front): add isTenantHost server helper"
```

---

## Task 2: `getActive()` accepts a `skipWorkspace` option

**Files:**
- Modify: `frontend/src/services/tournament.service.ts:70-83`
- Test: `frontend/src/services/tournament.service.test.ts` (create)

**Interfaces:**
- Consumes: existing `apiFetch`, `normalizePaginatedResponse`.
- Produces: `getActive(opts?: { skipWorkspace?: boolean }): Promise<PaginatedResponse<Tournament>>`. When `opts.skipWorkspace` is omitted it defaults to `true`. Task 3 calls `getActive({ skipWorkspace: !isTenantHost result })`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/services/tournament.service.test.ts`:

```ts
import { beforeEach, describe, expect, it, mock } from "bun:test";

// Capture the options apiFetch is called with, so we can assert how
// getActive threads skipWorkspace through.
type Call = { path: string; options: { skipWorkspace?: boolean } | undefined };
const calls: Call[] = [];

mock.module("@/lib/api-fetch", () => ({
  apiFetch: (path: string, options?: { skipWorkspace?: boolean }) => {
    calls.push({ path, options });
    return Promise.resolve({ json: async () => ({ results: [], total: 0 }) });
  },
}));

mock.module("@/lib/normalize-paginated-response", () => ({
  normalizePaginatedResponse: (r: unknown) => r,
}));

const { default: tournamentService } = await import("@/services/tournament.service");

describe("tournamentService.getActive", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("defaults to skipWorkspace: true (platform-wide) when called with no args", async () => {
    await tournamentService.getActive();
    expect(calls[0].options?.skipWorkspace).toBe(true);
  });

  it("forwards skipWorkspace: false when the caller opts into workspace scope", async () => {
    await tournamentService.getActive({ skipWorkspace: false });
    expect(calls[0].options?.skipWorkspace).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bun test src/services/tournament.service.test.ts`
Expected: FAIL on the second test — the current `getActive()` ignores arguments and always sends `skipWorkspace: true`.

- [ ] **Step 3: Modify `getActive`**

In `frontend/src/services/tournament.service.ts`, replace lines 70-83 (the whole `getActive` method):

```ts
  static async getActive(opts?: { skipWorkspace?: boolean }): Promise<PaginatedResponse<Tournament>> {
    return apiFetch(`/api/v1/tournaments`, {
      skipWorkspace: opts?.skipWorkspace ?? true,
      query: {
        page: 1,
        per_page: -1,
        sort: "id",
        order: "desc",
        entities: ["registrations_count"]
      }
    })
      .then((response) => response.json())
      .then((response: PaginatedResponse<Tournament>) => normalizePaginatedResponse(response));
  }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bun test src/services/tournament.service.test.ts`
Expected: PASS — 2 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/tournament.service.ts frontend/src/services/tournament.service.test.ts
git commit -m "feat(front): let tournamentService.getActive opt into workspace scope"
```

---

## Task 3: Scope the homepage; hide the redundant workspace badge on tenant hosts

**Files:**
- Modify: `frontend/src/app/(site)/(home)/page.tsx`

**Interfaces:**
- Consumes: `isTenantHost` (Task 1), `getActive({ skipWorkspace })` (Task 2).
- Produces: no new exports.

No unit test — these are server components composed of `<Suspense>` data cards. The deliverable is checked by `tsc` + `eslint` + a manual E2E pass (below). Each card computes its own `skipWorkspace` locally via `isTenantHost()`.

- [ ] **Step 1: Import the helper**

At the top of `frontend/src/app/(site)/(home)/page.tsx`, add the import next to the other `@/` imports (e.g. after the `tournamentService` import on line 13):

```ts
import { isTenantHost } from "@/lib/tenant-host";
```

- [ ] **Step 2: Reuse the helper for the top-level `tenantMode`**

In `Home()`, replace the inline header read:

```ts
  const tenantMode = (await headers()).get("x-owt-host-mode") === "tenant";
```

with:

```ts
  const tenantMode = await isTenantHost();
```

Line 42 was the only use of `headers` in this file, so it is now unused. Delete its import (line 3):

```ts
import { headers } from "next/headers";
```

- [ ] **Step 3: Scope `LiveEventsSection` and thread the badge flag**

In `LiveEventsSection`, add a tenant check and pass `skipWorkspace` into `getActive`. Replace:

```ts
async function LiveEventsSection() {
  const t = await getTranslations();
  let activeTournaments: TournamentWithCount[] = [];
  let workspaceMap = new Map<number, Workspace>();

  try {
    const [tournamentsData, workspaces] = await Promise.all([
      tournamentService.getActive(),
      workspaceService.getAll(),
    ]);
```

with:

```ts
async function LiveEventsSection() {
  const t = await getTranslations();
  const tenantMode = await isTenantHost();
  let activeTournaments: TournamentWithCount[] = [];
  let workspaceMap = new Map<number, Workspace>();

  try {
    const [tournamentsData, workspaces] = await Promise.all([
      tournamentService.getActive({ skipWorkspace: !tenantMode }),
      workspaceService.getAll(),
    ]);
```

Then, in the same function, update the `EventCard` render to pass the badge flag. Replace:

```tsx
        {activeTournaments.map((tour) => (
          <EventCard
            key={tour.id}
            tournament={tour}
            workspace={workspaceMap.get(tour.workspace_id)}
          />
        ))}
```

with:

```tsx
        {activeTournaments.map((tour) => (
          <EventCard
            key={tour.id}
            tournament={tour}
            workspace={workspaceMap.get(tour.workspace_id)}
            showWorkspaceBadge={!tenantMode}
          />
        ))}
```

- [ ] **Step 4: Accept and honour `showWorkspaceBadge` in `EventCard`**

Update the `EventCard` signature. Replace:

```tsx
async function EventCard({
  tournament,
  workspace,
}: {
  tournament: TournamentWithCount;
  workspace?: Workspace;
}) {
```

with:

```tsx
async function EventCard({
  tournament,
  workspace,
  showWorkspaceBadge = true,
}: {
  tournament: TournamentWithCount;
  workspace?: Workspace;
  showWorkspaceBadge?: boolean;
}) {
```

Then gate the badge. Replace the badge block:

```tsx
            {workspace && (
              <span
                className="text-[9px] font-bold tracking-[0.08em] uppercase px-1.5 py-0.5 rounded-full"
                style={{
                  background: `hsl(${hue} 72% 46% / 0.12)`,
                  border: `1px solid hsl(${hue} 72% 46% / 0.25)`,
                  color: `hsl(${hue} 72% 58%)`,
                }}
              >
                {workspace.name}
              </span>
            )}
```

with (only the condition changes — `workspace &&` becomes `workspace && showWorkspaceBadge &&`):

```tsx
            {workspace && showWorkspaceBadge && (
              <span
                className="text-[9px] font-bold tracking-[0.08em] uppercase px-1.5 py-0.5 rounded-full"
                style={{
                  background: `hsl(${hue} 72% 46% / 0.12)`,
                  border: `1px solid hsl(${hue} 72% 46% / 0.25)`,
                  color: `hsl(${hue} 72% 58%)`,
                }}
              >
                {workspace.name}
              </span>
            )}
```

- [ ] **Step 5: Scope `StatsGrid`**

In `StatsGrid`, replace:

```ts
async function StatsGrid() {
  const t = await getTranslations();
  let overall = null;
  try {
    overall = await statisticsService.getOverallStatistics({ skipWorkspace: true });
  } catch {
```

with:

```ts
async function StatsGrid() {
  const t = await getTranslations();
  const skipWorkspace = !(await isTenantHost());
  let overall = null;
  try {
    overall = await statisticsService.getOverallStatistics({ skipWorkspace });
  } catch {
```

- [ ] **Step 6: Scope the three dashboard cards**

Apply the same pattern to `TournamentActivityCard`, `DivisionRingsCard`, and `ChampionsCard` / `TopWinRateCard`. In each, add `const skipWorkspace = !(await isTenantHost());` right after the `const t = await getTranslations();` line, and change the service call's `{ skipWorkspace: true }` to `{ skipWorkspace }`.

`TournamentActivityCard`:

```ts
    const data = await statisticsService.getTournaments({ skipWorkspace });
```

`DivisionRingsCard`:

```ts
    const data = await statisticsService.getTournamentsDivision({
      skipWorkspace,
    });
```

`ChampionsCard`:

```ts
    const data = await statisticsService.getChampions({ skipWorkspace });
```

`TopWinRateCard`:

```ts
    const data = await statisticsService.getTopWinratePlayers({
      skipWorkspace,
    });
```

Each of these four functions gets one added line after its `getTranslations()` call:

```ts
  const skipWorkspace = !(await isTenantHost());
```

- [ ] **Step 7: Type-check**

Run: `cd frontend && bunx tsc --noEmit`
Expected: no NEW errors in `(site)/(home)/page.tsx`, `lib/tenant-host.ts`, or `services/tournament.service.ts`. (Pre-existing `.next/`-type errors unrelated to these files may remain — compare against a clean baseline.)

- [ ] **Step 8: Lint**

Run: `cd frontend && bun run lint`
Expected: 0 errors. (The now-unused `headers` import was already removed in Step 2.)

- [ ] **Step 9: Run the full test suite (nothing regressed)**

Run: `cd frontend && bun test`
Expected: all tests pass (including Tasks 1-2).

- [ ] **Step 10: Commit**

```bash
git add "frontend/src/app/(site)/(home)/page.tsx"
git commit -m "feat(front): scope homepage data to workspace on tenant hosts"
```

---

## Task 4: Scope the `/statistics` page

**Files:**
- Modify: `frontend/src/app/(site)/statistics/page.tsx`

**Interfaces:**
- Consumes: `isTenantHost` (Task 1).
- Produces: no new exports.

Same rationale as Task 3 — server components, verified by `tsc`/`eslint`/manual E2E. Six data cards, each gets a local `skipWorkspace`.

- [ ] **Step 1: Import the helper**

At the top of `frontend/src/app/(site)/statistics/page.tsx`, add after the `statisticsService` import (line 9):

```ts
import { isTenantHost } from "@/lib/tenant-host";
```

- [ ] **Step 2: Scope all six cards**

In each of `OverallStats`, `ActivityTrendCard`, `DivisionTrendCard`, `ChampionsLeaderboard`, `WinRateLeaderboard`, and `WonMapsLeaderboard`, add this line immediately after that function's `const t = await getTranslations();`:

```ts
  const skipWorkspace = !(await isTenantHost());
```

Then change each function's service call:

`OverallStats`:

```ts
    overall = await statisticsService.getOverallStatistics({ skipWorkspace });
```

`ActivityTrendCard`:

```ts
    data = await statisticsService.getTournaments({ skipWorkspace });
```

`DivisionTrendCard`:

```ts
    data = await statisticsService.getTournamentsDivision({ skipWorkspace });
```

`ChampionsLeaderboard`:

```ts
    rows = (await statisticsService.getChampions({ skipWorkspace })).results.slice(
      0,
      LEADERBOARD_SIZE,
    );
```

`WinRateLeaderboard`:

```ts
    rows = (await statisticsService.getTopWinratePlayers({ skipWorkspace })).results.slice(
      0,
      LEADERBOARD_SIZE,
    );
```

`WonMapsLeaderboard`:

```ts
    rows = (await statisticsService.getTopWonMapsPlayers({ skipWorkspace })).results.slice(
      0,
      LEADERBOARD_SIZE,
    );
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && bunx tsc --noEmit`
Expected: no new errors in `(site)/statistics/page.tsx`.

- [ ] **Step 4: Lint**

Run: `cd frontend && bun run lint`
Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/app/(site)/statistics/page.tsx"
git commit -m "feat(front): scope /statistics data to workspace on tenant hosts"
```

---

## Task 5: Final verification

**Files:** none (verification only).

- [ ] **Step 1: Whole-suite green**

Run: `cd frontend && bun test && bunx tsc --noEmit && bun run lint`
Expected: tests pass, no new type errors, 0 lint errors.

- [ ] **Step 2: Manual E2E (record results in the commit/PR description)**

1. **Apex** (`owt.craazzzyyfoxx.me` or local platform host): homepage + `/statistics` still show the platform-wide aggregate (unchanged). The "communities on this platform" section is still visible.
2. **Tenant** (a workspace subdomain, or a verified custom domain): homepage + `/statistics` now show counts, charts, and leaderboards for that workspace only, and they differ from the apex view. The per-event workspace-name badge is gone. The "communities" section stays hidden.
3. **Empty tenant workspace:** the empty/error fallbacks render (no crash).

- [ ] **Step 3: Spec + plan bookkeeping**

Confirm the spec (`docs/superpowers/specs/2026-07-11-homepage-workspace-scoping-design.md`) and this plan are committed on the branch (stage them explicitly if not).

```bash
git add "docs/superpowers/specs/2026-07-11-homepage-workspace-scoping-design.md" "docs/superpowers/plans/2026-07-11-homepage-workspace-scoping.md"
git commit -m "docs: homepage workspace-scoping spec + plan"
```
