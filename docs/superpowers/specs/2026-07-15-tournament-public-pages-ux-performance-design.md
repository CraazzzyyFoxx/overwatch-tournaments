# Tournament Public Pages UX and Performance Design

**Date:** 2026-07-15  
**Status:** Approved  
**Scope:** Public tournament routes under `/tournaments/[id]` and the linked draft experience at `/draft/[id]`

## Understanding Summary

- Improve the UX/UI of every public tournament subpage: bracket, teams, participants, matches, heroes, standings, and draft.
- Keep the existing Editorial Tactical visual language while making hierarchy, spacing, navigation, responsive behavior, and UI states consistent.
- Replace generic loading placeholders with page-specific skeletons that match the final geometry and avoid layout shift.
- Remove avoidable frontend request duplication and clean up the tournament public read path without introducing a large replacement API.
- Fix correctness and performance issues found during the production audit: ambient-workspace leakage on Teams, excessive Participants DOM/image work, and polling on completed brackets.
- Preserve tournament business rules, realtime behavior, privacy boundaries, admin features, and the existing uncommitted draft redesign.
- Validate against tournaments `72` and `78` on desktop and mobile.

## Current-State Findings

- The shared tournament layout requests tournament details, full stages, and team count independently on the client.
- The route-level `loading.tsx` depicts a legacy sidebar/card layout that does not resemble the current hero, metrics, navigation, or subpage content.
- Every subpage has a separate ad hoc loading state, and Draft uses a spinner instead of a structural skeleton.
- At a 382 px viewport, the tournament document overflows horizontally by about 57 px; the tab rail has no clear scroll affordance.
- Tournament 72 has 20 teams, but the public Teams page displays zero because the generic team request inherits the viewer's ambient workspace instead of the tournament workspace.
- Tournament 72 Participants renders 128 registrations into roughly 2 MB of DOM and initiates more than a thousand image elements, making navigation away from the page unreliable.
- A completed bracket continues polling encounters and full standings every 15 seconds, although realtime invalidation already exists.
- Bracket requests richer standings entities than it renders, including match history.
- Existing backend registration assembly already batches roles, heroes, statuses, form metadata, profile verdicts, and capped history; the main Participants bottleneck is client rendering rather than an N+1 query.
- Uncommitted work is moving Draft from `/tournaments/[id]/draft` to `/draft/[id]`. This work must be preserved and treated as part of the public tournament experience.

## Assumptions and Non-Functional Requirements

- Public tournaments are supported up to 500 registrations, 64 teams, and 8 stages for this iteration. Larger events require a future server-search/pagination design and are an explicit scale boundary rather than an untested promise.
- Participants must remain one continuous, non-paginated list.
- Search and filters are client-side over the complete public registration payload and are shareable through URL parameters.
- Public response fields and current privacy stripping remain unchanged.
- Completed tournament data is effectively immutable unless realtime invalidation says otherwise; periodic polling is unnecessary.
- The frontend must remain usable at 360 px width, with no document-level horizontal overflow.
- Interactive controls must remain keyboard accessible, expose loading/error state to assistive technology, and respect `prefers-reduced-motion`.
- New abstractions should be tournament-specific until a second proven consumer justifies wider generalization.
- Backend changes must be backward compatible and limited to public tournament read concerns.

## Alternatives Considered

### 1. UI-only repair

Replace skeletons, correct responsive overflow, and improve UI states without changing data flow. This has the lowest implementation risk but leaves duplicate shell requests, oversized rendering, and completed-tournament polling in place.

### 2. Balanced redesign — selected

Combine the shared visual redesign with server prefetch/hydration, explicit tournament scoping, continuous-list virtualization, lean page-specific reads, and conditional live updates. This removes the observed bottlenecks without replacing the public API.

### 3. Dedicated aggregate public API

Build a new tournament page aggregate endpoint and server-side Participants search/filtering. This could produce the cleanest eventual public read model, but it changes more contracts, duplicates existing entity selection, and is not justified by the current data scale.

## Decision Log

| Decision | Alternatives | Rationale |
| --- | --- | --- |
| Use the balanced redesign | UI-only; replacement aggregate API | Best UX/performance return without a broad API migration. |
| Keep Editorial Tactical | Introduce a new visual language | The current hero and strongest pages already establish a coherent product identity. |
| Use RSC prefetch plus React Query hydration | Client-only queries; server-only rendering | Removes initial waterfalls while preserving realtime cache behavior and client interactions. |
| Extend the current entities read model with `teams_count` | Separate count request; new overview endpoint | Backward compatible and removes one shell request with minimal backend surface area. |
| Keep Participants unpaginated | Client pagination; server pagination | Explicit product requirement; a continuous virtualized list retains the desired interaction. |
| Virtualize Participants | Render every row; incremental “load more” | Bounds DOM and image work while keeping every filtered result in a single scroll. |
| Put filters in the URL | Local storage only; component state only | Enables reload persistence, history navigation, and shareable filtered views. |
| Stop polling completed brackets | Always poll; realtime only | Avoids waste while retaining a fallback for actively changing tournaments. |
| Preserve `/draft/[id]` migration | Rework legacy nested Draft | Existing uncommitted redesign is authoritative and should not be overwritten. |

### Structured Review Objections and Resolutions

| Reviewer objection | Resolution |
| --- | --- |
| Query prefetch does not define how overview errors become `notFound` or a retryable shell state. | The overview uses a direct server loader returning a discriminated result, not `prefetchQuery`. A 404 calls `notFound`; another failure renders a shell-level retry that invokes `router.refresh`. Successful data is inserted into a request-scoped QueryClient and dehydrated. |
| Participants virtualization combines incompatible table/card/expansion/scroll assumptions. | Use one page-local scroll owner and one virtualized row DOM. Desktop and mobile are CSS layouts of the same accessible row; each row contains its expandable region and is measured as one variable-height virtual item. |
| New query keys are not mapped to realtime reasons. | Preserve common key prefixes and define an explicit reason-to-prefix matrix below. Completed pages have no timer but still respond to every relevant realtime event. |
| Standalone Draft conflicts with the persistent tournament layout assumption. | Draft is explicitly excluded from the tournament shell lifecycle. It receives its own route-level skeleton and a transition from tournament navigation; no shell retention is claimed. |
| Prefetching every page can inflate RSC payloads, especially Participants. | Only the small shared overview is server-loaded/hydrated. Page datasets remain client queries behind exact skeletons; related bracket queries start in parallel. |
| One overview read can still add database work. | The acceptance criterion concerns one public HTTP overview read, not one SQL query. `teams_count` must use a direct count and may add at most one count query versus the existing entity set. |
| Skeleton fidelity and URL history behavior are subjective. | Use a CLS target for the stable shell and define URL normalization/history semantics explicitly below. |
| A fresh realtime subscription can miss changes between the server snapshot and subscription confirmation. | Extend the realtime subscription contract with an optional `onSubscribed` callback. Tournament pages perform one coalesced catch-up invalidation after every confirmed subscribe/reconnect; this is not periodic polling. |
| Full Participants processing remains O(n) despite virtualized rendering. | Declare a supported ceiling of 500 registrations and verify payload/mounted-row budgets against a generated fixture. Beyond that ceiling, server-side search or pagination is required. |
| A bounded Participants viewport creates a nested scroll trap and weakens the agreed continuous-list experience. | Use window/document virtualization. The page remains one native scroll surface; wide participant fields may scroll horizontally inside a row viewport, but vertical scrolling is never nested. |
| Filters, disabled phase tabs, and standalone Draft lack explicit navigation behavior. | Define filter reset/announcement rules, accessible availability reasons for disabled tabs, and a persistent Back to tournament action in Draft. |
| Virtual rows do not expose their place in the complete result set. | The virtual table/grid advertises full `aria-rowcount`; mounted rows expose stable `aria-rowindex`, and the mobile reading order follows the visible card order. |

## Architecture and Data Loading

The tournament segment layout becomes a server-side Suspense boundary. Its fallback is an exact `TournamentShellSkeleton` containing the final hero, four metric cells, and section navigation geometry. A request-scoped cached loader fetches a public tournament overview with tournament fields, participant and registration counts, team count, and stage summaries.

The overview query is dehydrated into the application's existing React Query client. The client layout consumes the same centralized query key, so hydration does not trigger an immediate duplicate request. Metadata and the layout share a strictly request-scoped loader where their data requirements overlap; cross-request caching is prohibited because tournament visibility can depend on the viewer.

The overview loader is awaited directly inside a server boundary and returns a discriminated success/error result. A 404 invokes `notFound()`. Any other initial error renders a shell-level retry state whose action calls `router.refresh()`. On success, the loader inserts the overview into a request-scoped QueryClient and dehydrates it. This avoids relying on `prefetchQuery`, which intentionally swallows query errors.

Only the small shared overview is server-loaded and hydrated. Page datasets remain client queries behind exact structural skeletons; private or viewer-specific data, such as the current user's registration, remains a separate authenticated query. Related bracket queries start concurrently. The persistent layout means tab navigation retains the tournament shell while only the changing subpage enters loading state.

Query keys are centralized under `tournamentQueryKeys` and distinguish overview, full stages, workspace-scoped teams, participants, encounters, lean bracket standings, and full standings. Variants retain common prefixes so one precise prefix invalidation can refresh every relevant variant without listing cache internals throughout the UI.

The existing tournament detail entities mechanism gains an optional `teams_count` field backed by the same tournament/workspace visibility predicates as the Teams list and a direct count query. A named frontend `getPublicTournamentOverview` service hides the fixed entity set from components. Stage summary and full stage TypeScript types are separated so callers cannot accidentally rely on fields absent from overview responses.

## Shared UX/UI System

The shared shell keeps the dark Editorial Tactical canvas, Onest display typography, JetBrains Mono labels, thin rules, and restrained surfaces. Content uses a stable maximum width and responsive gutters. The tournament section nav becomes sticky beneath the global header on long pages.

On narrow screens the nav is an independently scrollable rail with leading/trailing fade affordances and explicit keyboard-accessible previous/next scroll controls so overflow is not communicated by color alone. The active item scrolls into view after navigation. Wide data surfaces are contained within horizontal viewports rather than widening the document.

Phase-locked tabs remain discoverable and expose `aria-disabled` plus a localized availability reason on focus/hover. A concise note beside the nav explains the current phase and when additional sections become available, so a locked route cannot be confused with missing data or an error.

Every subpage follows the same hierarchy:

1. section label;
2. title and concise context/count;
3. page controls;
4. primary visualization or data surface.

Shared skeleton primitives include lines, labels, metrics, controls, table rows, cards, and frames. Skeletons use design tokens, a restrained directional shimmer, and a static reduced-motion variant. Each loading region owns exactly one `role="status"`/`aria-busy` announcement; decorative skeleton primitives are `aria-hidden`. Each route composes those primitives to reproduce its stable header/control/content geometry instead of displaying generic rectangles. Dynamic list length is not predicted; the hero and navigation must remain fixed, and measured route CLS should remain at or below 0.1 during the audited transition.

Loading, empty, filtered-empty, and error states are separate. Initial loads use skeletons; background/realtime refetches keep current data rendered and show only a restrained updating indicator. API errors keep the shared shell and any stale data visible and provide an inline retry action. Filtered-empty states retain controls and offer a reset. True empty states explain why data is absent without implying a failed request.

## Page Designs

### Bracket

Expose stage selection, live/completed status, and a horizontal-navigation hint near the bracket viewport. Preserve the existing bracket visualization. Start stages, encounters, and lean standings client queries in parallel. Request only standings fields needed to label/place teams. Fallback polling runs only for `live` and `playoffs`; all other statuses rely on explicit realtime invalidation.

### Teams

Use an adaptive one/two-column team grid with clear roster counts and identifiers. Derive the workspace explicitly from the tournament overview in a named tournament-scoped service call. The empty state must represent genuinely missing teams, not a scoped-query failure.

### Participants

Keep one continuous list with search and filters encoded in URL parameters. Search input is trimmed, stripped of control characters, capped at 120 characters, debounced, and updates the current history entry with `replace`; discrete status/column filter changes use `push`. Default values are omitted, and unsupported values are normalized once with `replace`.

The filtered collection uses window/document virtualization with a small overscan window, preserving the page's single native vertical scroll surface. One registration is one variable-height virtual item containing both its summary and expandable details. A `ResizeObserver`-driven measurement updates the virtualizer after expansion or responsive layout changes. Horizontal overflow from optional fields remains inside the participant row/table surface and never becomes a second vertical scroll owner.

The same DOM uses accessible table/grid roles and desktop columns, then switches to compact card-like CSS grid areas on mobile; a second hidden collection is never rendered. The collection exposes the full `aria-rowcount`, and every mounted registration exposes `aria-rowindex` for its position in the filtered result set. Mobile source order matches the visible identity → status → details order. The expander exposes `aria-expanded` and `aria-controls`, and expanded state is keyed by registration ID. Only visible/overscan entries mount their images.

A search/filter/history change recomputes the result set and, when the current viewport is below the result start, scrolls to the result heading beneath the sticky nav. It does not steal focus from the search field or triggering filter. A single polite live region announces the new result count. Back/Forward applies the same deterministic rule, preventing a stale virtual offset from landing beyond the new list.

### Matches

Add a section heading and context above the existing search and server pagination. Keep page/search in the URL. Do not add a status filter in this iteration because the current public endpoint does not define that filter contract. Result/status typography and narrow-screen containment are aligned with the shared data viewport.

### Heroes

Keep role filters and ranked rows, strengthen the quantitative bar hierarchy, and align labels/counts with the shared section header. The skeleton mirrors role controls and the final ranked list density.

### Standings

Retain the existing strong stage-grouped composition. Improve stage headings and narrow-screen navigation, including a sticky team column within the table viewport where feasible. Full standings continue to request the richer entities used by this page.

### Draft

Treat the in-progress `/draft/[id]` experience as authoritative and architecturally separate from the `/tournaments/[id]` layout. Do not replace its layout or interaction work. The tournament nav links to it, but no persistent tournament shell or active nested-tab state is promised after navigation. The standalone Draft hero always exposes a localized Back to tournament action that resolves to the tournament's appropriate public section. Draft receives its own route-level structural skeleton consistent with the standalone hero and workspace.

## Realtime Invalidation Contract

All variants use prefixes from the centralized key factory. The existing broad admin invalidators may remain for compatibility, but public refresh correctness is defined by this matrix:

| Event reason | Public query prefixes invalidated | Route refresh |
| --- | --- | --- |
| `bracket_changed` | encounters | No |
| `results_changed` | overview/detail, stages, hero playtime, all standings variants, encounters | No |
| `structure_changed` | overview/detail, stages, workspace-scoped teams, participants list/form/current registration, hero playtime, all standings variants, encounters | Yes, to refresh server overview |

Completed and archived tournaments do not run timers, but the realtime subscription remains active and applies the same matrix. A timer is only a fallback for `live` and `playoffs`.

The realtime client and `useRealtimeTopic` gain an optional `onSubscribed` callback invoked after the server confirms every fresh subscription or reconnect. Tournament pages use it to perform one coalesced catch-up invalidation of their public prefixes after the subscription cursor is established. This closes the server-snapshot-to-WebSocket gap without periodic polling. Repeated confirmations and bursts are coalesced per tournament; `structure_changed` route refreshes use a 500 ms trailing coalescer so one mutation burst causes at most one `router.refresh()`.

## Error Handling and Edge Cases

- An invalid tournament ID or overview 404 resolves through the route's not-found behavior.
- A recoverable overview error renders a shell-level retry state; a page-data error renders inside the retained shell.
- Missing stage/standings data produces a stage-specific empty state instead of an empty generic frame.
- Search/filter parameters are normalized; unsupported values fall back to safe defaults without breaking the page.
- Virtualized Participants preserves expanded state by registration ID, provides stable row/region IDs, and returns focus to the row expander when an expanded region is collapsed.
- Participants has one native document scroll owner; filter/history changes cannot retain an offset beyond the new result set and announce the new count without stealing input focus.
- A breakpoint change keeps one row DOM and filter state, preserves logical source order, remeasures mounted rows, and does not render duplicate desktop/mobile collections.
- Realtime updates can invalidate completed data once, but do not re-enable periodic polling.
- Participants processing is intentionally O(n) up to the documented 500-registration support ceiling; URL search never sends registration contents back to the server.
- Explicit tournament workspace scope is included in team query keys to prevent cross-workspace cache collisions.

## Verification and Acceptance Criteria

Use tournaments `72` and `78` for browser smoke testing through `localhost:3000`.

- No document-level horizontal overflow at 360–390 px.
- The active tournament tab is visible, keyboard accessible, and correctly marked; phase-locked tabs expose a localized reason, and overflow remains operable without relying on a gradient.
- Every tournament subpage skeleton matches its stable loaded geometry; the hero/navigation remain fixed and audited route CLS is at most 0.1. Draft is checked against its separate standalone skeleton.
- Tournament 72 Teams renders the actual tournament teams regardless of the viewer's selected workspace.
- Participants provides one non-paginated scroll while mounting only a bounded visible/overscan set of rows and images.
- A 500-registration fixture keeps the public JSON response below 1 MiB uncompressed, mounts no more than 40 registration items at the audited desktop/mobile viewports, and never creates image elements for unmounted registrations.
- Participants URL filters survive reload, browser history, and link sharing.
- Screen readers receive the complete filtered row count and each mounted row's position; background refetch keeps current content instead of returning to skeleton.
- A completed or archived bracket produces no periodic encounters/standings traffic during a 45-second observation window; `live`/`playoffs` retains fallback refresh and all statuses respond to realtime events.
- A confirmed fresh subscription and reconnect each cause one coalesced catch-up invalidation; a burst of `structure_changed` events causes at most one route refresh per 500 ms window.
- The shared shell makes one public HTTP overview read rather than independent tournament, stages-count, and teams-count requests; adding `teams_count` performs a direct count and does not materialize teams.
- Russian and English messages remain synchronized.
- Existing uncommitted user and Draft changes remain intact.
- Standalone Draft always provides a keyboard-accessible Back to tournament path.

Verification consists of targeted backend contract/query tests, frontend tests for query keys/filter normalization/polling behavior, the repository's frontend lint command, and browser smoke/visual checks. Per project instructions, do not use `next build` as the frontend validation command.

## Risks and Mitigations

- **Variable-height virtualization:** use the document as the only vertical scroll owner, stable registration IDs, one measured item per registration, and no duplicate responsive collection; cover expansion, filtering/history reset, ARIA row metadata, and breakpoint remeasurement in tests.
- **Hydration/query-key mismatch:** centralize query option factories so server prefetch and client hooks share both key and fetcher.
- **Snapshot/subscription gap:** invalidate once only after the server confirms subscription/reconnect; unit-test callback delivery and catch-up coalescing.
- **Participants scale ceiling:** exercise a generated 500-registration fixture and fail the contract if payload or mounted-item budgets are exceeded.
- **Dirty worktree overlap:** inspect every overlapping diff first and apply minimal patches around existing Draft/nav/global-style changes.
- **Over-generalized skeleton API:** keep primitives small and compose route-specific skeletons; avoid a configuration-heavy renderer.
- **Backend entity drift:** test `teams_count` serialization and explicit workspace scoping at service/route boundaries.

## Explicit Non-Goals

- Redesigning tournament administration.
- Changing tournament lifecycle, registration, bracket, standings, or draft business rules.
- Introducing a new paginated Participants API.
- Replacing the realtime transport.
- Rewriting the existing standalone Draft redesign.
- Generalizing the tournament UI into a site-wide design-system migration.
