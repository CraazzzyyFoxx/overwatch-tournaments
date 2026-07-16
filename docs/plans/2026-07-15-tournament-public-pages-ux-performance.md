# Tournament Public Pages UX and Performance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a coherent, responsive public tournament experience across bracket, teams, participants, matches, heroes, standings, and standalone Draft, with design-faithful skeletons and a cleaner, cheaper public read path.

**Architecture:** The shared `/tournaments/[id]` layout server-loads one visibility-aware overview and hydrates it into the existing React Query client; page datasets remain client queries behind exact route-specific skeletons. The existing tournament entities contract gains `teams_count`, public query keys stay prefix-compatible with realtime invalidation, and Participants uses one document-scroll `useWindowVirtualizer` collection rather than pagination or a nested vertical viewport.

**Tech Stack:** Next.js 16 App Router/RSC, React 19, TanStack Query 5, TanStack Virtual 3.13, next-intl, TypeScript, CSS Modules/Tailwind, Python 3.13, FastStream RPC, Pydantic 2, SQLAlchemy 2, Bun test, pytest, Ruff, ESLint.

---

## Execution Context and Baseline

- Worktree: `C:\Users\andre\.config\superpowers\worktrees\anak-tournaments\tournament-public-ux`
- Branch: `codex/tournament-public-ux`
- Original dirty workspace to preserve: `C:\Users\andre\Programming\anak-tournaments`
- Approved design: `docs/superpowers/specs/2026-07-15-tournament-public-pages-ux-performance-design.md`
- Do not run `next build`; project instructions define lint as the frontend build-level check.
- Full `npm run lint` is already red with 19 unrelated `react-hooks/set-state-in-effect` errors. Use the scoped ESLint command in every task and report the unchanged global baseline at handoff.
- Current scoped tournament ESLint passes.
- Current targeted Bun suite passes: 13 tests across tournament service, realtime helpers, bracket, and workspace scoping.
- Backend tournament tests currently contain one pre-existing detached-fixture failure because `_tournament()` omits `is_hidden`; repair that fixture before relying on the serialization suite.

## Task 1: Preserve the Existing Draft Migration Baseline

**Files:**

- Copy from original workspace into the worktree without rewriting:
  - `frontend/src/app/(site)/tournaments/[id]/_components/TournamentSectionNav.tsx`
  - `frontend/src/app/(site)/tournaments/[id]/draft/page.tsx`
  - `frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftBoard.tsx`
  - `frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftPageHero.tsx`
  - `frontend/src/app/(site)/tournaments/[id]/draft/_components/SpectatorDraftWorkspace.tsx`
  - `frontend/src/app/(site)/tournaments/[id]/draft/_components/TeamRosters.tsx`
  - `frontend/src/app/admin/tournaments/[id]/components/DraftSessionDashboard.tsx`
  - `frontend/src/app/admin/tournaments/[id]/components/draft/AdminControlRoom.tsx`
  - `frontend/src/app/admin/tournaments/[id]/components/draft/DraftReadyStep.tsx`
  - `frontend/src/app/draft/[id]/page.tsx`
  - `frontend/src/app/draft/[id]/DraftRoom.module.css`
  - `frontend/src/app/globals.css`
  - `frontend/src/i18n/messages/en.json`
  - `frontend/src/i18n/messages/ru.json`
- Existing in worktree: `docs/superpowers/specs/2026-07-15-tournament-public-pages-ux-performance-design.md`
- Existing in worktree: `docs/plans/2026-07-15-tournament-public-pages-ux-performance.md`

**Step 1: Verify the source snapshot**

Run from the original workspace:

```powershell
git status --short
git diff --check
```

Expected: the listed tournament/Draft files are present; unrelated user compare/backend changes are not selected for copying.

**Step 2: Copy only the approved tournament/Draft snapshot**

Use `Copy-Item -LiteralPath` for the listed tracked files and the two files under `frontend/src/app/draft/[id]`. Do not copy the unrelated backend user-service files or user-compare plans/specs.

**Step 3: Verify the copied baseline**

Run in `frontend`:

```powershell
bun test "src/app/(site)/tournaments/[id]/draft/_lib/*.test.ts" "src/app/admin/tournaments/[id]/components/draft/*.test.ts"
npx eslint "src/app/(site)/tournaments/[id]/draft" "src/app/draft/[id]" "src/app/admin/tournaments/[id]/components/draft" "src/app/(site)/tournaments/[id]/_components/TournamentSectionNav.tsx"
```

Expected: targeted Draft tests and scoped lint pass. If the copied user snapshot itself fails, stop and report rather than changing its behavior silently.

**Step 4: Commit the preserved baseline**

```powershell
git add docs/superpowers/specs/2026-07-15-tournament-public-pages-ux-performance-design.md docs/plans/2026-07-15-tournament-public-pages-ux-performance.md frontend/src/app frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json frontend/src/app/globals.css
git commit -m "chore: preserve tournament draft redesign baseline"
```

## Task 2: Add `teams_count` to the Backend Tournament Read Model

**Files:**

- Modify: `backend/tournament-service/tests/test_tournament_public_serialization.py`
- Modify: `backend/tournament-service/src/schemas/tournament.py`
- Modify: `backend/tournament-service/src/services/team/service.py`
- Modify: `backend/tournament-service/src/services/tournament/flows.py`

**Step 1: Repair the existing detached test fixture**

Add `is_hidden=False` to `_tournament()` so the test does not lazy-load a detached default.

**Step 2: Write failing serializer/count tests**

Add tests proving:

```python
@patch.object(team_service, "get_team_count_by_tournament", new_callable=AsyncMock)
async def test_to_pydantic_resolves_requested_teams_count(self, count_mock):
    count_mock.return_value = 20
    read = await flows.to_pydantic(session, _tournament(), ["teams_count"])
    self.assertEqual(read.teams_count, 20)

async def test_to_pydantic_omits_unrequested_teams_count(self):
    read = await flows.to_pydantic(session, _tournament(), [])
    self.assertIsNone(read.teams_count)
```

Also assert the bulk list path passes a prefetched `teams_counts` mapping when the entity is requested.

**Step 3: Run tests to verify the new behavior fails**

Run in `backend`:

```powershell
uv run pytest tournament-service/tests/test_tournament_public_serialization.py -q
```

Expected: failures for the missing schema field/helper, while the repaired existing fixture test passes.

**Step 4: Implement the direct and bulk count contract**

Add to `TournamentRead`:

```python
teams_count: int | None = None
```

Add a singular helper next to the existing bulk helper:

```python
async def get_team_count_by_tournament(session: AsyncSession, tournament_id: int) -> int:
    result = await session.execute(
        sa.select(sa.func.count(models.Team.id)).where(models.Team.tournament_id == tournament_id)
    )
    return result.scalar_one()
```

Extend `to_pydantic(..., teams_counts=None)` and `get_all()` exactly like participant/registration counts. The count must use the requested tournament ID and never materialize teams.

**Step 5: Verify backend behavior and style**

```powershell
uv run pytest tournament-service/tests/test_tournament_public_serialization.py tournament-service/tests/test_tournament_cache_invalidation.py -q
uv run ruff check tournament-service/src/schemas/tournament.py tournament-service/src/services/team/service.py tournament-service/src/services/tournament/flows.py tournament-service/tests/test_tournament_public_serialization.py
```

Expected: all targeted tests pass; Ruff reports no errors.

**Step 6: Commit**

```powershell
git add backend/tournament-service/src backend/tournament-service/tests/test_tournament_public_serialization.py
git commit -m "feat: expose tournament team counts"
```

## Task 3: Centralize Frontend Overview Types, Fetcher, and Query Keys

**Files:**

- Modify: `frontend/src/types/tournament.types.ts`
- Modify: `frontend/src/services/tournament.service.ts`
- Modify: `frontend/src/services/tournament.service.test.ts`
- Modify: `frontend/src/lib/tournament-query-keys.ts`
- Modify: `frontend/src/app/(site)/tournaments/[id]/_hooks/useTournamentClientData.ts`
- Create: `frontend/src/app/(site)/tournaments/[id]/_hooks/tournamentOverview.test.ts`

**Step 1: Write failing service and key tests**

Assert `getPublicOverview(72)` calls the detail route with:

```typescript
{
  skipWorkspace: true,
  query: {
    entities: ["stages", "participants_count", "registrations_count", "teams_count"]
  }
}
```

Assert workspace-aware keys preserve invalidation prefixes:

```typescript
expect(tournamentQueryKeys.teams(72, 6)).toEqual(["teams", 72, 6]);
expect(tournamentQueryKeys.bracketStandings(72, 6)).toEqual(["standings", 72, "bracket", 6]);
```

**Step 2: Run tests to verify failure**

```powershell
bun test src/services/tournament.service.test.ts "src/app/(site)/tournaments/[id]/_hooks/tournamentOverview.test.ts"
```

Expected: missing overview method/keys.

**Step 3: Split stage summary/full types**

Extract the common stage fields into `StageSummary`; make `Stage extends StageSummary` and add `items`. Change `Tournament.stages` to `StageSummary[]` and add:

```typescript
teams_count: number | null;
```

Do not make overview consumers pretend stage items are loaded.

**Step 4: Implement the overview fetcher and shared query options**

Add `tournamentService.getPublicOverview(id)` with the fixed entity set and `skipWorkspace: true`. In `useTournamentClientData.ts`, export a query option factory used by both server hydration and the client hook:

```typescript
export const tournamentOverviewQueryOptions = (id: number) =>
  queryOptions({
    queryKey: tournamentQueryKeys.detail(id),
    queryFn: () => tournamentService.getPublicOverview(id),
    staleTime: 60_000,
  });
```

Keep full stages on their distinct key.

**Step 5: Verify tests and scoped lint**

```powershell
bun test src/services/tournament.service.test.ts "src/app/(site)/tournaments/[id]/_hooks/tournamentOverview.test.ts"
npx eslint src/types/tournament.types.ts src/services/tournament.service.ts src/services/tournament.service.test.ts src/lib/tournament-query-keys.ts "src/app/(site)/tournaments/[id]/_hooks"
```

Expected: tests and lint pass.

**Step 6: Commit**

```powershell
git add frontend/src/types/tournament.types.ts frontend/src/services/tournament.service.ts frontend/src/services/tournament.service.test.ts frontend/src/lib/tournament-query-keys.ts "frontend/src/app/(site)/tournaments/[id]/_hooks"
git commit -m "refactor: centralize tournament overview data"
```

## Task 4: Server-Load and Hydrate the Shared Tournament Shell

**Files:**

- Modify: `frontend/src/app/(site)/tournaments/[id]/_data.ts`
- Modify: `frontend/src/app/(site)/tournaments/[id]/layout.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/page.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/_components/TournamentClientLayout.tsx`
- Create: `frontend/src/app/(site)/tournaments/[id]/_components/TournamentOverviewBoundary.tsx`
- Create: `frontend/src/app/(site)/tournaments/[id]/_components/TournamentShellError.tsx`
- Create: `frontend/src/app/(site)/tournaments/[id]/_components/TournamentSkeletons.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/loading.tsx`
- Create: `frontend/src/app/(site)/tournaments/[id]/tournamentOverview.contract.test.ts`

**Step 1: Write the failing architecture contract**

Test that the server boundary:

- uses `getPublicTournamentOverview` directly;
- maps not-found errors to `notFound()`;
- seeds `tournamentQueryKeys.detail(id)` with `QueryClient.setQueryData` and renders `HydrationBoundary`;
- renders a retryable shell error for other failures;
- leaves no `teamService.getCount` or layout-level full stages query in `TournamentClientLayout`.

Use the repository's existing source-contract test pattern for RSC composition, and keep behavior tests in the service/helper suites.

**Step 2: Run the contract to verify failure**

```powershell
bun test "src/app/(site)/tournaments/[id]/tournamentOverview.contract.test.ts"
```

Expected: missing boundary/hydration and legacy client count/stages calls still present.

**Step 3: Implement the request-scoped loader result**

Keep React `cache()` request-scoped; do not introduce `unstable_cache`. The loader should either return data, call `notFound()` for `isNotFoundError`, or return a serializable error message.

**Step 4: Implement Suspense and hydration**

The layout renders:

```tsx
<Suspense fallback={<TournamentShellSkeleton />}>
  <TournamentOverviewBoundary tournamentId={tournamentId}>
    {children}
  </TournamentOverviewBoundary>
</Suspense>
```

The boundary creates a request-local QueryClient, inserts the successful overview, and dehydrates it. `TournamentClientLayout` consumes only `useTournamentQuery`, derives stage/team metrics from overview summaries, and retains the existing realtime hook.

**Step 5: Reuse overview in redirect and metadata paths**

Make `/tournaments/[id]` select its redirect from overview stage summaries without a separate full-stages read. Metadata uses the same request-scoped overview loader and preserves the current fallback.

**Step 6: Verify**

```powershell
bun test "src/app/(site)/tournaments/[id]/tournamentOverview.contract.test.ts" "src/app/(site)/tournaments/[id]/bracket/TournamentBracketPage.test.ts"
npx eslint "src/app/(site)/tournaments/[id]" src/types/tournament.types.ts src/services/tournament.service.ts src/lib/tournament-query-keys.ts
```

Expected: contract and existing bracket layout tests pass; scoped lint passes.

**Step 7: Commit**

```powershell
git add "frontend/src/app/(site)/tournaments/[id]"
git commit -m "feat: hydrate tournament overview shell"
```

## Task 5: Build the Shared Navigation, State, and Skeleton System

**Files:**

- Modify: `frontend/src/app/(site)/tournaments/[id]/_components/TournamentSectionNav.tsx`
- Create: `frontend/src/app/(site)/tournaments/[id]/_components/tournament-section-nav.ts`
- Create: `frontend/src/app/(site)/tournaments/[id]/_components/tournament-section-nav.test.ts`
- Expand: `frontend/src/app/(site)/tournaments/[id]/_components/TournamentSkeletons.tsx`
- Create: `frontend/src/app/(site)/tournaments/[id]/_components/TournamentPageState.tsx`
- Create: `frontend/src/app/(site)/tournaments/[id]/TournamentDetail.module.css`
- Create: `frontend/src/app/(site)/tournaments/[id]/bracket/loading.tsx`
- Create: `frontend/src/app/(site)/tournaments/[id]/teams/loading.tsx`
- Create: `frontend/src/app/(site)/tournaments/[id]/participants/loading.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/matches/loading.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/heroes/loading.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/standings/loading.tsx`
- Modify: `frontend/src/i18n/messages/en.json`
- Modify: `frontend/src/i18n/messages/ru.json`

**Step 1: Write failing navigation rules tests**

Cover active/locked routes for registration, draft, check-in, live, playoffs, completed, and archived statuses. Assert every locked item has a localized reason key and Draft resolves to `/draft/{id}`.

**Step 2: Run the test to verify failure**

```powershell
bun test "src/app/(site)/tournaments/[id]/_components/tournament-section-nav.test.ts"
```

Expected: missing pure navigation model/reasons.

**Step 3: Extract the pure navigation model**

Return item records with `href`, `active`, `available`, and `reasonKey`. Keep the component focused on rendering/scroll behavior.

**Step 4: Implement sticky accessible navigation**

Use a contained horizontal rail, previous/next scroll buttons, edge fades as decoration only, `scrollIntoView({ inline: "center" })` for the active link, and focusable `aria-disabled` locked items with an explanatory tooltip/note. No element may widen the document.

**Step 5: Implement shared loading/state primitives**

Create one live status per region; mark primitives `aria-hidden`. Export page-specific compositions:

```typescript
type TournamentSkeletonVariant =
  | "bracket" | "teams" | "participants" | "matches"
  | "heroes" | "standings";
```

Each composition must include the actual page header/control geometry and representative content rows/cards. `TournamentPageState` distinguishes initial error, stale-data refresh error, true empty, and filtered empty with reset/retry actions.

**Step 6: Wire every route loading file**

Replace all generic rectangles and legacy sidebar skeletons with shared shell/page variants. Keep dynamic list lengths approximate; keep hero/nav dimensions stable.

**Step 7: Verify i18n, tests, and lint**

```powershell
bun test "src/app/(site)/tournaments/[id]/_components/tournament-section-nav.test.ts"
npx eslint "src/app/(site)/tournaments/[id]" src/i18n/messages/en.json src/i18n/messages/ru.json
```

Expected: test/lint pass and both locales contain identical new key paths.

**Step 8: Commit**

```powershell
git add "frontend/src/app/(site)/tournaments/[id]" frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json
git commit -m "feat: unify tournament navigation and loading states"
```

## Task 6: Close the Realtime Catch-Up Gap and Centralize Invalidation

**Files:**

- Modify: `frontend/src/services/realtime.service.ts`
- Create: `frontend/src/services/realtime.service.test.ts`
- Modify: `frontend/src/hooks/useRealtimeTopic.ts`
- Modify: `frontend/src/hooks/useTournamentRealtime.ts`
- Modify: `frontend/src/hooks/tournamentRealtime.helpers.ts`
- Modify: `frontend/src/hooks/tournamentRealtime.helpers.test.ts`
- Modify: `frontend/src/app/(site)/tournaments/[id]/_components/TournamentClientLayout.tsx`

**Step 1: Write failing callback/matrix/coalescing tests**

Add tests proving:

- `bracket_changed` invalidates encounter prefixes only;
- `results_changed` reaches overview, stages, heroes, all standings variants, and encounters;
- `structure_changed` also reaches teams and registration prefixes and requests one route refresh;
- the catch-up plan invalidates all public prefixes without periodic polling;
- multiple structure refresh requests inside 500 ms coalesce to one callback;
- a `subscribed` frame calls optional subscription callbacks on fresh subscribe and reconnect.

Expose only the smallest test seam needed for `RealtimeClient`; do not make the socket implementation public API broadly.

**Step 2: Run tests to verify failure**

```powershell
bun test src/hooks/tournamentRealtime.helpers.test.ts src/services/realtime.service.test.ts
```

Expected: missing `onSubscribed` and catch-up/coalescer behavior.

**Step 3: Extend subscription acknowledgements compatibly**

Store `{ onEvent, onSubscribed? }` per topic handler. When the server sends `op: "subscribed"`, update its cursor and call every current topic subscriber's optional acknowledgement callback. Existing callers without the callback remain unchanged.

**Step 4: Apply one-shot tournament catch-up**

`useTournamentRealtime` passes an `onSubscribed` handler that invalidates the catch-up prefixes once after every confirmed fresh subscribe/reconnect. It must not start an interval. In `TournamentClientLayout`, coalesce `router.refresh()` for structure events with a 500 ms trailing timer and clean it up on unmount.

**Step 5: Verify**

```powershell
bun test src/hooks/tournamentRealtime.helpers.test.ts src/services/realtime.service.test.ts
npx eslint src/services/realtime.service.ts src/hooks/useRealtimeTopic.ts src/hooks/useTournamentRealtime.ts src/hooks/tournamentRealtime.helpers.ts "src/app/(site)/tournaments/[id]/_components/TournamentClientLayout.tsx"
```

Expected: all tests and scoped lint pass.

**Step 6: Commit**

```powershell
git add frontend/src/services/realtime.service.ts frontend/src/services/realtime.service.test.ts frontend/src/hooks "frontend/src/app/(site)/tournaments/[id]/_components/TournamentClientLayout.tsx"
git commit -m "fix: catch up tournament realtime subscriptions"
```

## Task 7: Fix Teams Scope and Stop Wasteful Bracket Polling

**Files:**

- Modify: `frontend/src/services/team.service.ts`
- Create: `frontend/src/services/team.service.test.ts`
- Modify: `frontend/src/lib/tournament-query-keys.ts`
- Modify: `frontend/src/app/(site)/tournaments/[id]/pages/TournamentTeamsPage.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/bracket/TournamentBracketPage.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/bracket/TournamentBracketPage.test.ts`
- Modify: `frontend/src/app/(site)/tournaments/[id]/pages/tournamentWorkspaceScope.test.ts`

**Step 1: Write failing workspace and polling tests**

Assert `teamService.getAll({ tournamentId: 72, workspaceId: 6 })` sends both IDs explicitly. Assert team keys include the workspace. Add a pure bracket helper test:

```typescript
expect(getBracketRefetchInterval("live")).toBe(15_000);
expect(getBracketRefetchInterval("playoffs")).toBe(15_000);
expect(getBracketRefetchInterval("completed")).toBe(false);
expect(getBracketRefetchInterval("archived")).toBe(false);
```

Assert bracket standings request `{ workspaceId, includeMatchesHistory: false, includeTeamGroup: false }`.

**Step 2: Run tests to verify failure**

```powershell
bun test src/services/team.service.test.ts "src/app/(site)/tournaments/[id]/bracket/TournamentBracketPage.test.ts" "src/app/(site)/tournaments/[id]/pages/tournamentWorkspaceScope.test.ts"
```

Expected: current Teams call inherits ambient workspace; bracket always polls and requests rich standings.

**Step 3: Implement explicit tournament scope**

Replace positional `teamService.getAll` arguments with an options object containing `tournamentId`, `workspaceId`, sort, and order. Include workspace in the query key and API query. The tournament ID remains the visibility authority; the workspace prevents ambient cache/request leakage.

**Step 4: Implement conditional bracket refresh and lean standings**

Use the pure status helper as `refetchInterval`; disable background interval polling. Keep realtime active for all statuses. Use `tournamentQueryKeys.bracketStandings` and the lean service options.

**Step 5: Improve page states without hiding stale data**

Use the shared Teams and Bracket skeletons only for initial load. Keep current data on background fetch, show the updating indicator, and render separate real-empty/filter-empty/error states.

**Step 6: Verify**

```powershell
bun test src/services/team.service.test.ts "src/app/(site)/tournaments/[id]/bracket/TournamentBracketPage.test.ts" "src/app/(site)/tournaments/[id]/pages/tournamentWorkspaceScope.test.ts"
npx eslint src/services/team.service.ts src/lib/tournament-query-keys.ts "src/app/(site)/tournaments/[id]/pages/TournamentTeamsPage.tsx" "src/app/(site)/tournaments/[id]/bracket"
```

Expected: tests/lint pass.

**Step 7: Commit**

```powershell
git add frontend/src/services/team.service.ts frontend/src/services/team.service.test.ts frontend/src/lib/tournament-query-keys.ts "frontend/src/app/(site)/tournaments/[id]/pages/TournamentTeamsPage.tsx" "frontend/src/app/(site)/tournaments/[id]/bracket" "frontend/src/app/(site)/tournaments/[id]/pages/tournamentWorkspaceScope.test.ts"
git commit -m "fix: scope teams and bracket refreshes"
```

## Task 8: Replace Participants Local Storage and Full DOM with URL State and Window Virtualization

**Files:**

- Create: `frontend/src/app/(site)/tournaments/[id]/pages/_components/participants-url-state.ts`
- Create: `frontend/src/app/(site)/tournaments/[id]/pages/_components/participants-url-state.test.ts`
- Create: `frontend/src/app/(site)/tournaments/[id]/pages/_components/VirtualParticipantsList.tsx`
- Create: `frontend/src/app/(site)/tournaments/[id]/pages/_components/VirtualParticipantsList.contract.test.ts`
- Modify: `frontend/src/app/(site)/tournaments/[id]/pages/TournamentParticipantsPage.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/TournamentDetail.module.css`
- Modify: `frontend/src/app/(site)/tournaments/[id]/participants/page.tsx`
- Modify: `frontend/src/i18n/messages/en.json`
- Modify: `frontend/src/i18n/messages/ru.json`

**Step 1: Write failing URL-state tests**

Cover:

- trimming/control-character removal;
- 120-character cap;
- default status omission;
- unsupported status normalization to `all`;
- search updates use replace semantics;
- discrete status changes use push semantics;
- other query parameters are preserved.

**Step 2: Write the virtualization contract test**

Assert the component uses `useWindowVirtualizer`, `getItemKey: index => registrations[index].id`, `overscan`, `scrollMargin`, `data-index`, and `measureElement`; exposes `aria-rowcount`/`aria-rowindex`; and does not create a second desktop/mobile collection or a vertical overflow container.

**Step 3: Run tests to verify failure**

```powershell
bun test "src/app/(site)/tournaments/[id]/pages/_components/participants-url-state.test.ts" "src/app/(site)/tournaments/[id]/pages/_components/VirtualParticipantsList.contract.test.ts"
```

Expected: helper/component do not exist.

**Step 4: Implement URL-backed filters without set-state-in-effect**

Use an uncontrolled keyed search input with a ref-held debounce timer; write URL search via `router.replace`. Use `router.push` for discrete filters. On result changes, preserve focus and scroll to the result heading only when the current window offset is below it. Announce one polite result-count message.

**Step 5: Implement one document-scroll virtual collection**

Follow the current TanStack Virtual API:

```tsx
const virtualizer = useWindowVirtualizer({
  count: registrations.length,
  estimateSize: () => 68,
  getItemKey: (index) => registrations[index].id,
  overscan: 8,
  scrollMargin,
});
```

Render a relative spacer with `height: virtualizer.getTotalSize()`. Each virtual registration is one absolutely positioned item with `data-index`, `ref={virtualizer.measureElement}`, and `translateY(item.start - scrollMargin)`. Summary and expanded details stay inside that one measured item. Use a ResizeObserver-derived scroll margin for responsive/preceding-content changes.

**Step 6: Preserve accessible semantics and responsive order**

Expose full result `aria-rowcount`; virtual items use `aria-rowindex={index + 2}` after the header. Desktop columns and mobile cards are CSS layouts of the same DOM in identity → status → details source order. Expander controls stable detail-region IDs and returns focus on collapse.

**Step 7: Keep initial/background states distinct**

Initial public-list load uses the Participants skeleton. Background refetch preserves current rows. Real-empty and filtered-empty states differ; filtered empty keeps controls and provides reset.

**Step 8: Verify unit contracts and scoped lint**

```powershell
bun test "src/app/(site)/tournaments/[id]/pages/_components/participants-url-state.test.ts" "src/app/(site)/tournaments/[id]/pages/_components/VirtualParticipantsList.contract.test.ts"
npx eslint "src/app/(site)/tournaments/[id]/pages/TournamentParticipantsPage.tsx" "src/app/(site)/tournaments/[id]/pages/_components" "src/app/(site)/tournaments/[id]/participants/page.tsx"
```

Expected: tests and lint pass; no synchronous setState-in-effect workaround is introduced.

**Step 9: Commit**

```powershell
git add "frontend/src/app/(site)/tournaments/[id]/pages" "frontend/src/app/(site)/tournaments/[id]/participants" "frontend/src/app/(site)/tournaments/[id]/TournamentDetail.module.css" frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json
git commit -m "feat: virtualize tournament participants"
```

## Task 9: Polish Matches, Heroes, and Standings with Shared Page States

**Files:**

- Modify: `frontend/src/app/(site)/tournaments/[id]/pages/TournamentEncountersPage.tsx`
- Modify: `frontend/src/components/EncountersTable.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/pages/TournamentHeroPlaytimePage.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/pages/TournamentStandingsPage.tsx`
- Modify: `frontend/src/components/StandingsTable.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/matches/page.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/heroes/page.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/standings/page.tsx`
- Modify: `frontend/src/app/(site)/tournaments/[id]/TournamentDetail.module.css`
- Create: `frontend/src/app/(site)/tournaments/[id]/pages/public-page-states.contract.test.ts`

**Step 1: Write the failing public-page contract**

Assert each page has a section heading/context, initial skeleton, retained content during background fetch, inline retry on query error, and true-empty state. Assert Matches keeps existing URL page/search and does not introduce the unsupported status filter. Assert Standings uses a contained horizontal viewport/sticky team column rather than document overflow.

**Step 2: Run to verify failure**

```powershell
bun test "src/app/(site)/tournaments/[id]/pages/public-page-states.contract.test.ts"
```

Expected: current ad hoc states and missing Matches header fail the contract.

**Step 3: Apply the shared hierarchy and state components**

Use section label → title/count/context → controls → content consistently. Keep Matches server pagination at 15 and its search/page URL behavior. Keep Heroes role filters and strengthen the quantitative bars. Preserve the current Standings stage composition while containing wide tables and making the first team column sticky where supported.

**Step 4: Remove filter sync lint debt only where touched**

`EncountersTable` currently synchronously mirrors URL search into local state in an effect. Replace that touched pattern with an uncontrolled/keyed input or reducer initialization so scoped lint remains green; do not broaden into unrelated global lint cleanup.

**Step 5: Verify**

```powershell
bun test "src/app/(site)/tournaments/[id]/pages/public-page-states.contract.test.ts" "src/app/(site)/tournaments/[id]/pages/tournamentWorkspaceScope.test.ts"
npx eslint "src/app/(site)/tournaments/[id]" src/components/EncountersTable.tsx src/components/StandingsTable.tsx
```

Expected: tests and scoped lint pass.

**Step 6: Commit**

```powershell
git add "frontend/src/app/(site)/tournaments/[id]" frontend/src/components/EncountersTable.tsx frontend/src/components/StandingsTable.tsx
git commit -m "feat: polish tournament public data pages"
```

## Task 10: Replace Standalone Draft Spinner Loading with a Structural Skeleton

**Files:**

- Create: `frontend/src/app/draft/[id]/DraftRoomSkeleton.tsx`
- Create: `frontend/src/app/draft/[id]/loading.tsx`
- Modify: `frontend/src/app/draft/[id]/page.tsx`
- Modify: `frontend/src/app/draft/[id]/DraftRoom.module.css`
- Create: `frontend/src/app/draft/[id]/DraftRoomSkeleton.test.ts`

**Step 1: Write the failing Draft skeleton contract**

Assert the standalone route loading file and client initial query state render the same `DraftRoomSkeleton`; it contains toolbar/back-link geometry, standalone hero geometry, board controls, and representative roster columns; it has one status live region and no spinner.

**Step 2: Run to verify failure**

```powershell
bun test "src/app/draft/[id]/DraftRoomSkeleton.test.ts"
```

Expected: missing structural skeleton and current `Loader2` state.

**Step 3: Implement and reuse the structural skeleton**

Build the skeleton from small aria-hidden primitives but keep exactly one parent status announcement. Respect reduced motion. Reuse it from `loading.tsx` and `tournamentQuery.isLoading`. Preserve the current sticky Back to tournament toolbar and every existing Draft interaction.

**Step 4: Verify Draft**

```powershell
bun test "src/app/draft/[id]/DraftRoomSkeleton.test.ts" "src/app/(site)/tournaments/[id]/draft/_lib/*.test.ts"
npx eslint "src/app/draft/[id]" "src/app/(site)/tournaments/[id]/draft"
```

Expected: tests/lint pass.

**Step 5: Commit**

```powershell
git add "frontend/src/app/draft/[id]"
git commit -m "feat: add standalone draft loading skeleton"
```

## Task 11: End-to-End Verification and Performance Audit

**Files:**

- Modify only if verification finds an in-scope defect.
- Update: `docs/superpowers/specs/2026-07-15-tournament-public-pages-ux-performance-design.md` only if an accepted implementation detail changed.

**Step 1: Run the complete targeted frontend tests**

```powershell
bun test src/services/tournament.service.test.ts src/services/team.service.test.ts src/services/realtime.service.test.ts src/hooks/tournamentRealtime.helpers.test.ts "src/app/(site)/tournaments/[id]/**/*.test.ts" "src/app/draft/[id]/*.test.ts"
```

Expected: all targeted tests pass.

**Step 2: Run scoped frontend lint**

```powershell
npx eslint "src/app/(site)/tournaments/[id]" "src/app/draft/[id]" src/components/EncountersTable.tsx src/components/StandingsTable.tsx src/lib/tournament-query-keys.ts src/services/tournament.service.ts src/services/team.service.ts src/services/realtime.service.ts src/hooks/useRealtimeTopic.ts src/hooks/useTournamentRealtime.ts src/hooks/tournamentRealtime.helpers.ts src/types/tournament.types.ts
```

Expected: zero scoped errors/warnings introduced. Do not run `next build`.

**Step 3: Run targeted backend verification**

```powershell
uv run pytest tournament-service/tests/test_tournament_public_serialization.py tournament-service/tests/test_tournament_cache_invalidation.py tournament-service/tests/test_tournament_realtime_events.py -q
uv run ruff check tournament-service/src/schemas/tournament.py tournament-service/src/services/team/service.py tournament-service/src/services/tournament/flows.py tournament-service/tests/test_tournament_public_serialization.py
```

Expected: tests pass and Ruff is clean.

**Step 4: Start local frontend and smoke-test all routes**

Use the project's existing local API/backend or configured remote gateway, then run `npm run dev` from `frontend`. Inspect:

- `/tournaments/72/bracket`
- `/tournaments/72/teams`
- `/tournaments/72/participants`
- `/tournaments/72/matches`
- `/tournaments/72/heroes`
- `/tournaments/72/standings`
- `/draft/72` when applicable
- `/tournaments/78/participants`

Test desktop and 360–390 px mobile widths. Confirm no document-level horizontal overflow, active nav visibility, locked-tab reasons, keyboard navigation, retry/empty/filter-empty states, and skeleton-to-content geometry.

**Step 5: Verify network behavior**

- Cold tournament entry: one public overview request, no separate team count/stage-summary request.
- Completed/archived bracket: no periodic encounter/standings request during 45 seconds.
- Live/playoffs bracket: 15-second fallback remains.
- Fresh/reconnected realtime subscription: one catch-up invalidation.
- Teams 72: query includes workspace 6 and renders 20 teams.

**Step 6: Verify Participants budgets**

- One native vertical document scroll; no nested vertical scroll trap.
- Search/status encoded in URL; search uses replace, status uses push; Back/Forward is deterministic.
- At audited viewports, no more than 40 registration items are mounted.
- Unmounted registrations create no image elements.
- Generated 500-registration fixture serializes below 1 MiB uncompressed.
- Full `aria-rowcount`, stable `aria-rowindex`, logical mobile reading order, and focus return on collapse.

**Step 7: Measure layout stability**

Use a PerformanceObserver or browser performance tooling during cold route entry and tab navigation. Expected audited CLS is at most 0.1; the hero and navigation do not move when page data resolves.

**Step 8: Record the known global lint baseline**

Run `npm run lint` once only to compare with baseline. Expected: the same pre-existing unrelated errors may remain. Confirm no new error path points to files changed by this plan.

**Step 9: Commit verification-only fixes and final docs**

```powershell
git add -A
git commit -m "test: verify tournament public experience"
```

Skip this commit if verification made no file changes.

**Step 10: Final branch check**

```powershell
git status --short
git log --oneline --decorate -12
git diff develop...HEAD --check
```

Expected: clean worktree, focused commits, and no whitespace errors.
