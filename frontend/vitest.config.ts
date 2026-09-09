import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // `react-resizable-panels` conditionally exports a stripped-down
      // "edge-light" build under the `node` condition (no layout effects — it
      // targets edge runtimes without a DOM). Node's own module resolution
      // picks that condition once the package is externalized/required by
      // Vitest, even under `@vitest-environment happy-dom`, so every
      // imperative call (`collapse()`/`resize()`) throws "Panel size not
      // found". Alias straight to the real browser build, matching what
      // Next.js's client bundler resolves in production.
      "react-resizable-panels": fileURLToPath(
        new URL(
          "./node_modules/react-resizable-panels/dist/react-resizable-panels.browser.development.js",
          import.meta.url
        )
      )
    },
    dedupe: ["react", "react-dom"]
  },
  test: {
    // Externalized deps are loaded by Node and resolve their own CJS `react`,
    // whose hook dispatcher react-dom never sets. `@tanstack/react-table` calls
    // hooks, so every `useReactTable` render threw "Invalid hook call" until it
    // was inlined through Vite alongside the app code. `cmdk` calls `useRef` the
    // same way, so every combobox popover threw the moment it opened.
    server: { deps: { inline: ["@tanstack/react-table", "cmdk"] } },
    environment: "node",
    include: [
      // The whole admin tree, both extensions. `src/app/admin` holds no
      // `bun:test` file — the mixed-runner problem that forces file-level
      // entries elsewhere in this list does not exist here — so one glob is
      // safe and every test added under a new admin route runs without another
      // edit to this allow-list. The narrower admin entries below are kept
      // where they document a specific trap.
      "src/app/admin/**/*.test.ts",
      "src/app/admin/**/*.test.tsx",
      "src/app/**/tournaments/**/draft/**/*.test.ts",
      "src/app/**/tournaments/**/pregame/**/*.test.ts",
      // `.tsx` needs its own entry: the line above ends in `.test.ts`, so the
      // pregame room's behaviour test would never run and the suite would
      // still report green.
      "src/app/**/tournaments/**/pregame/**/*.test.tsx",
      "src/app/admin/tournaments/**/components/draft/**/*.test.ts",
      // Same `.ts`/`.tsx` trap as the pregame entry above: the render contracts
      // for the draft setup steps are `.tsx` and would silently never run.
      "src/app/admin/tournaments/**/components/draft/**/*.test.tsx",
      "src/app/admin/tournaments/**/overview/**/*.test.ts",
      "src/app/admin/tournaments/new/**/*.test.ts",
      "src/app/admin/divisions/**/*.test.tsx",
      "src/app/admin/tournaments/**/components/*.test.ts",
      "src/app/admin/tournaments/**/components/*.test.tsx",
      "src/app/admin/tournaments/[id]/tab-guards.test.ts",
      "src/app/admin/players/**/*.test.ts",
      // Same `.ts`/`.tsx` trap as the pregame/draft entries above: the players
      // table's render contract is `.tsx` and would silently never run.
      "src/app/admin/players/**/*.test.tsx",
      "src/app/admin/__tests__/**/*.test.ts",
      // `include` is an allow-list: a test file outside it never runs and the
      // suite still reports green. Both data-browser dirs are listed up front
      // so the first test added under either one actually executes.
      "src/app/admin/match-reports/**/*.test.ts",
      "src/app/admin/match-reports/**/*.test.tsx",
      "src/app/admin/matches/**/*.test.ts",
      "src/app/admin/matches/**/*.test.tsx",
      "src/app/admin/sub-roles/**/*.test.tsx",
      "src/app/admin/subscriptions/**/*.test.tsx",
      "src/app/admin/workspaces/members/*.test.ts",
      "src/app/admin/workspaces/members/*.test.tsx",
      "src/app/admin/teams/*.test.tsx",
      "src/app/balancer/components/balance-import.test.ts",
      "src/app/balancer/components/balancer-page-selectors.test.ts",
      "src/app/balancer/components/forced-flex-parity.test.ts",
      "src/app/balancer/components/BalancingPoolSidebar.behavior.test.tsx",
      "src/app/balancer/components/WorkspacePlayersSidebar.behavior.test.tsx",
      "src/app/balancer/tool-context.test.ts",
      "src/app/balancer/redirect-map.test.ts",
      "src/app/balancer/BalancerLayoutClient.behavior.test.tsx",
      // Both extensions: the pickup lineup rules are `.ts` and the panel's
      // render contract is `.tsx`, and a single `.test.ts` entry would silently
      // skip the second one.
      "src/app/balancer/pickup/**/*.test.ts",
      "src/app/balancer/pickup/**/*.test.tsx",
      "src/app/**/users/compare/**/*.test.ts",
      "src/app/(site)/tournaments/[slug]/_views/_components/participantsColumns.test.tsx",
      // Same allow-list trap: this folder also holds `bun:test` files, so the
      // entry is file-level rather than a directory glob.
      "src/app/(site)/tournaments/[slug]/_views/TournamentEncountersPage.behavior.test.tsx",
      "src/app/(site)/tournaments/[slug]/_views/TournamentMapsPage.behavior.test.tsx",
      "src/app/(site)/tournaments/[slug]/_views/TournamentOverviewPage.behavior.test.tsx",
      "src/app/(site)/tournaments/[slug]/_views/TournamentParticipantsPage.behavior.test.tsx",
      "src/app/(site)/tournaments/[slug]/_views/TournamentStatsPage.behavior.test.tsx",
      "src/app/(site)/tournaments/[slug]/_views/TournamentTeamsPage.behavior.test.tsx",
      "src/app/(site)/tournaments/[slug]/_views/_components/ParticipantsPool.behavior.test.tsx",
      // The public list itself. File-level for the same mixed-runner reason as
      // its `[slug]` neighbours above: `src/app/(site)/tournaments` also holds
      // `bun:test` files, so a directory glob would drag them into vitest.
      "src/app/(site)/tournaments/tournamentsList.behavior.test.tsx",
      "src/app/(site)/tournaments/components/TournamentCard.behavior.test.tsx",
      "src/components/tournaments/**/*.test.ts",
      "src/components/pick-ban/**/*.test.ts",
      "src/components/pick-ban/**/*.test.tsx",
      // File-level, not `**/*.test.tsx`: this folder also holds `bun:test`
      // files, which fail on the import when vitest picks them up.
      "src/components/tournaments/MatchReportDialog.behavior.test.tsx",
      "src/components/tournaments/EncounterEditDialog.behavior.test.tsx",
      "src/components/balancer/registrations/**/*.test.tsx",
      "src/components/balancer/form/**/*.test.tsx",
      "src/components/balancer/feed/**/*.test.tsx",
      "src/components/admin/**/*.test.tsx",
      "src/components/admin/**/*.test.ts",
      // `include` is an allow-list, so a test under a directory absent from it
      // never runs and the suite still reports green.
      "src/components/discord/**/*.test.tsx",
      "src/components/ui/data-pagination.test.tsx",
      "src/components/ui/date-range-picker.test.tsx",
      "src/components/ui/infinite-scroll.test.tsx",
      "src/components/site/**/*.test.tsx",
      "src/components/ui/toggle-group.test.tsx",
      "src/components/ui/resizable.test.tsx",
      "src/components/status/**/*.test.tsx",
      // `src/components/stream` is vitest-only, so a directory glob is safe here
      // and covers the next test added without another edit to this allow-list.
      "src/components/stream/**/*.test.ts",
      "src/components/stream/**/*.test.tsx",
      // `src/components/realtime` is vitest-only, so a directory glob is safe
      // here and covers the next test added without another edit to this list.
      "src/components/realtime/**/*.test.tsx",
      // File-level, not a directory glob: this folder holds BOTH runners'
      // tests. `RoleStep.behavior.test.tsx` is `.tsx` yet imports `bun:test`,
      // so a directory glob here drags it into vitest and it fails on the import.
      "src/components/registration/SubscriptionRow.behavior.test.tsx",
      "src/components/registration/CheckInSubscriptionProof.behavior.test.tsx",
      "src/components/registration/DetailsStep.behavior.test.tsx",
      "src/components/registration/MyTeamPanel.i18n.test.tsx",
      // Own-team dedup: unrun, a green suite would coexist with the exact
      // duplicate-card regression this file exists to catch.
      "src/components/registration/RegistrationTeamsList.test.tsx",
      // The only surface an addressed invite exists on. File-level for the same
      // mixed-runner reason as its neighbours; unrun, it would report green while
      // the whole targeted-invite mode was invisible.
      "src/components/registration/MyInviteOffers.behavior.test.tsx",
      // The captain's half of the same mode. Separate from the i18n mount test
      // above because it drives the dialog rather than only rendering it.
      "src/components/registration/MyTeamPanel.picker.test.tsx",
      // The invite ledger. Unrun, a green suite would coexist with a section that
      // fetches on every mount or renders raw i18n key paths.
      "src/components/registration/InviteHistorySection.behavior.test.tsx",
      // File-level for the same mixed-runner reason as its neighbours above.
      // The landing page for a shared invite link: an unrun mount test here
      // would report green while the whole invitee flow was unreachable, which
      // is exactly the state this route was added to fix.
      "src/app/(site)/invite/page.behavior.test.tsx",
      // Same mixed-runner situation in `src/lib`, so file-level again. This one
      // mirrors the backend's best-of resolution and sequence generation, and
      // the veto room runs the SERVER's sequence — an unrun drift check is
      // worse than none, since it reports green either way.
      "src/lib/best-of.test.ts",
      "src/lib/roster-shape.test.ts",
      "src/lib/return-to.test.ts",
      // Same mixed-runner situation, so file-level again: this one pins the
      // reason-code catalogue against both message files and the organizer-first
      // ordering of the aggregate. Unrun, a new backend reason code would reach
      // the UI as raw snake_case with a green suite.
      "src/lib/admission.test.ts",
      // Added when frontend CI landed: these nine imported `vitest` but matched
      // no pattern above, so the suite reported green without ever running them
      // (the allow-list trap this file warns about three times). `scripts/
      // check-vitest-include.mjs` now fails CI on the next one, instead of it
      // going unnoticed until someone reads this array.
      "src/lib/draft-crest.test.ts",
      "src/lib/draft-data.test.ts",
      "src/lib/draft-logic.test.ts",
      "src/lib/draft-visual.test.ts",
      "src/lib/draft-workspace-model.test.ts",
      "src/lib/stream-platform.test.ts",
      "src/lib/image-capture.test.ts",
      // Was in the same unrun state when the register-button gate got its first
      // real test: the stream-visibility cases in it had never executed either.
      "src/lib/tournament-status.test.ts",
      "src/components/Header.mobile-layout.test.ts",
      "src/components/WorkspaceBootstrap.helpers.test.ts",
      // File-level: `src/components` holds both runners' tests, so a directory
      // glob here would drag the `bun:test` files into vitest.
      "src/components/TeamName.behavior.test.tsx",
      "src/components/HoverPrefetchLink.behavior.test.tsx",
      "src/components/EncounterRostersModal.behavior.test.tsx",
      "src/components/BracketView.behavior.test.tsx",
      "src/components/FavoriteStarButton.behavior.test.tsx",
      "src/components/UserSearch.behavior.test.tsx",
      "src/components/StandingsTable.advance.behavior.test.tsx",
      // The only workspace-creation surface a plain account can reach; unrun,
      // a green suite would coexist with a dead self-service entry point.
      "src/components/CreateWorkspaceLauncher.behavior.test.tsx",
      // Same file-level rule: `account-settings` is under `src/components`, and
      // these are its only vitest files so far.
      "src/components/account-settings/MyAccountSection.behavior.test.tsx",
      "src/components/account-settings/FavoritesSection.behavior.test.tsx",
      // Same file-level rule: `src/components/match` is otherwise untested, and
      // this pins that the log download is offered only to a signed-in viewer.
      "src/components/match/MatchLogIndicator.behavior.test.tsx",
      // `src/components/notifications` is vitest-only, so a directory glob is
      // safe and covers the next test added without another edit to this list.
      // Unrun, a green suite would coexist with a bell that never refetches.
      "src/components/notifications/**/*.test.tsx",
      // `src/components/roster-shape` is vitest-only, so a directory glob is
      // safe here too. Both files were the allow-list trap in its loud form:
      // unmatched, they fell into bun's complement, where the editor's mount
      // test has no DOM at all (`document is not defined`) — a red suite for a
      // reason that has nothing to do with the code under test.
      "src/components/roster-shape/**/*.test.ts",
      "src/components/roster-shape/**/*.test.tsx",
      "src/app/(site)/tournaments/[slug]/_components/tournament-section-nav.test.ts",
      "src/app/(site)/tournaments/[slug]/_components/tournament-shared-ui.test.tsx",
      "src/app/(site)/tournaments/[slug]/_components/PhaseTimeline.behavior.test.tsx",
      "src/app/(site)/tournaments/[slug]/_components/TournamentBroadcastDock.behavior.test.tsx",
      "src/app/(site)/tournaments/[slug]/_components/TournamentLinkChips.behavior.test.tsx",
      // Same file-level rule as `src/components`: the bracket folder also holds a
      // `bun:test` file (`TournamentBracketPage.test.ts`).
      // File-level, not a directory glob: `src/hooks` also holds `bun:test`
      // files.
      "src/app/(site)/tournaments/[slug]/bracket/bracketLiveStreams.test.ts",
      "src/hooks/useRealtimeCoalescedRefetch.test.ts",
      "src/hooks/useRealtimePatchedQuery.test.ts",
      "src/hooks/useInvalidation.test.ts",
      // The manifest parity gate: this one is the reason a resource cannot be
      // published without the client knowing which queries it stales.
      "src/lib/realtime-resources.test.ts"
    ]
  }
});
