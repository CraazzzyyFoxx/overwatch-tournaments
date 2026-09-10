// @vitest-environment happy-dom
//
// The Teams › Roster sub-tab, through the route rather than the component.
// What is pinned here:
//  1. `?challongeSync=1` still opens the mapping wizard on arrival and still
//     strips itself — the Integrations card links here to clear its "N
//     participants not mapped" failure, and the fix must survive the move of
//     this screen from `/teams` to `/teams/roster`;
//  2. the page passes real permissions down: without `team.create` there is no
//     sync/import entry at all, so the gate is not a disabled button;
//  3. the tournament and its stages come from the hub's shared queries, and a
//     missing tournament renders nothing rather than a half-empty screen.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TeamsRosterPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Hoisted: these factories run while the module graph is still initializing,
// so they cannot close over ordinary top-level consts.
const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getChallongeTeamSyncPreview: vi.fn(),
  syncTeamsFromChallonge: vi.fn(),
  search: "",
  granted: new Set<string>(),
  tournament: null as { id: number; workspace_id: number } | null
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "64" }),
  usePathname: () => "/admin/tournaments/64/teams/roster",
  useRouter: () => ({ replace: mocks.replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(mocks.search)
}));
vi.mock("next/link", () => ({ default: "a" }));
// The code split is a bundling concern, and vitest's module runner never
// settles an `import()` issued from a mocked module during render — so the
// wrapper is replaced by the tab itself, loaded here where it does resolve.
// This page has exactly one dynamic component, so the loader is not consulted.
vi.mock("next/dynamic", async () => {
  const tab = await import("../../components/TournamentTeamsTab");
  return { default: () => tab.TournamentTeamsTab };
});
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => "en"
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string) => mocks.granted.has(permission),
    isLoaded: true
  })
}));

vi.mock("../../hubQueries", () => ({
  tabFallback: null,
  useHubTournamentQuery: () => ({ data: mocks.tournament, isLoading: false }),
  useHubStagesQuery: () => ({ data: [{ id: 1, name: "Groups" }], isLoading: false }),
  useHubTeamsQuery: () => ({ data: { results: [] }, isLoading: false })
}));

vi.mock("@/components/admin/tournament-checklist", () => ({ hasChallongeSource: () => true }));

vi.mock("@/services/admin.service", () => ({
  default: {
    getChallongeTeamSyncPreview: mocks.getChallongeTeamSyncPreview,
    syncTeamsFromChallonge: mocks.syncTeamsFromChallonge
  }
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), info: vi.fn(), apiError: vi.fn() }
}));

const PREVIEW = {
  teams: [{ id: 13, name: "litnik", balancer_name: "litnik_main" }],
  participants: [
    {
      participant_id: 289541235,
      challonge_id: 289541235,
      group_id: null,
      group_name: null,
      challonge_tournament_id: 4242,
      name: "litnik team",
      active: true,
      suggested_team_id: 13,
      mapped_team_id: null
    }
  ]
};

const TEAM_PERMISSIONS = [
  "team.create",
  "team.update",
  "team.delete",
  "player.create",
  "player.update",
  "player.delete"
];

let container: HTMLElement;
let root: Root;

async function settle() {
  // A macrotask per turn, not a bare microtask: the sync preview query only
  // starts once the dialog is open, and react-query needs the timer queue
  // drained before the participants row exists.
  for (let turn = 0; turn < 5; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <TeamsRosterPage />
      </QueryClientProvider>
    );
  });
  await settle();
}

function byText(selector: string, text: string) {
  return [...document.querySelectorAll(selector)].find((node) => node.textContent?.includes(text));
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  mocks.replace.mockReset();
  mocks.getChallongeTeamSyncPreview.mockReset().mockResolvedValue(PREVIEW);
  mocks.syncTeamsFromChallonge.mockReset().mockResolvedValue({
    success: true,
    count: 1,
    created: 1,
    updated: 0,
    unchanged: 0,
    skipped: 0
  });
  mocks.search = "";
  mocks.granted = new Set(TEAM_PERMISSIONS);
  mocks.tournament = { id: 64, workspace_id: 1 };
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("teams roster route", () => {
  it("renders the roster screen with its team operations", async () => {
    await render();

    expect(container.textContent).toContain("Team operations");
    expect(byText("button", "Sync teams")).toBeTruthy();
  });

  it("withholds sync without team.create", async () => {
    mocks.granted = new Set(["team.update"]);

    await render();

    expect(byText("button", "Sync teams")).toBeUndefined();
    // `team.update` alone still reaches the shared teams workspace.
    expect(byText("a", "Manage teams")).toBeTruthy();
  });

  it("renders nothing until the tournament is loaded", async () => {
    mocks.tournament = null;

    await render();

    expect(container.textContent).toBe("");
  });

  it("opens the mapping wizard from ?challongeSync=1 and strips the param", async () => {
    mocks.search = "challongeSync=1&keep=me";

    await render();

    const dialog = document.querySelector("[role='dialog']");
    expect(dialog).toBeTruthy();
    expect(dialog?.textContent).toContain("Sync Challonge teams");
    // Step one of the wizard, not the write: nothing has been synced yet.
    expect(dialog?.textContent).toContain("Map participants");
    expect(mocks.syncTeamsFromChallonge).not.toHaveBeenCalled();
    // Unrelated params survive; only the one-shot trigger is dropped, so a
    // refresh does not reopen a dialog nobody asked for.
    expect(mocks.replace).toHaveBeenCalledWith("/admin/tournaments/64/teams/roster?keep=me", {
      scroll: false
    });
  });

  it("stays closed without the param and rewrites no url", async () => {
    await render();

    expect(document.querySelector("[role='dialog']")).toBeNull();
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});
