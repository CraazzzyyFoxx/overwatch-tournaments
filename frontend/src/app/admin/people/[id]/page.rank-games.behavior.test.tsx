// @vitest-environment happy-dom
//
// The person hub is game-neutral, so its Ranks tab carries ONE game switcher for all of its blocks — the current
// ranks, the collection, the history chart and the past ratings (R23). It opens on the page's `?discipline=`, else the
// first game — the site's saved scope and last game never reach the admin — and a pick is the page's `?discipline=`,
// which every block reads.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@craazzzyyfoxx/admin-kit/ui/tooltip";
import type { RankOverviewListParams } from "@/services/workspace-player.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { navigation } from "@/test/url-navigation";

import PersonHubPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listRanks = vi.fn();
const getRankCollectionStatus = vi.fn();

vi.mock("next/navigation", async () => ({
  ...(await import("@/test/url-navigation")).nextNavigationMock,
  useParams: () => ({ id: "42" })
}));
vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ canAccessPermission: () => true, hasPermission: () => true, isSuperuser: false, isLoaded: true })
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({
    dateTime: (value: Date) => value.toISOString(),
    relativeTime: (value: Date) => value.toISOString()
  })
}));
vi.mock("@/hooks/useCurrentWorkspace", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCurrentWorkspace")>()),
  useDivisionGrid: () => ({ tiers: [] })
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    getUsers: async () => ({ results: [{ id: 42, name: "nnniik#2515", social_accounts: [] }], total: 1, page: 1, per_page: -1 }),
    getRankCollectionStatus: (...args: unknown[]) => getRankCollectionStatus(...args)
  }
}));
vi.mock("@/services/workspace-player.service", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  workspacePlayerService: {
    listRanks: (...args: unknown[]) => listRanks(...args),
    listAuthors: async () => ({ authors: [] })
  }
}));
// The history chart is the game's own module with its own suite; which game it is drawn for is the subject.
vi.mock("@/disciplines/DisciplineWidget", () => ({
  DisciplineWidget: ({ discipline }: { discipline: string }) => <div data-rank-history={discipline} />
}));

let root: Root;
let container: HTMLDivElement;

const tablists = () => [...container.querySelectorAll('[role="tablist"]')];
// A tab reads as its monogram then its name ("OWOverwatch").
const selectedGame = () => tablists()[0]?.querySelector('[role="tab"][aria-selected="true"]')?.textContent;
/** The rank reads made for one game: the current layers (no `layer`) and the past ones. */
const ranksRead = (game: string) =>
  listRanks.mock.calls
    .map(([, params]) => params as RankOverviewListParams)
    .filter((params) => params.discipline === game && params.playerId === 42);

async function settle() {
  for (let turn = 0; turn < 8; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

beforeEach(() => {
  listRanks.mockReset().mockResolvedValue({ page: 1, per_page: 100, total: 0, results: [] });
  getRankCollectionStatus.mockReset().mockResolvedValue([]);
  useWorkspaceStore.setState({
    workspaces: [{ id: 1, name: "OWT", disciplines_enabled: ["overwatch", "lol"] }] as never,
    currentWorkspaceId: 1,
    statsScope: "workspace",
    hostLockedWorkspaceId: null,
    entityWorkspaceId: null,
    entityDiscipline: null,
    gameScope: "lol",
    lastGame: "lol"
  });
  navigation.reset("/admin/people/42?tab=ranks");
  container = document.body.appendChild(document.createElement("div"));
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("the person hub's Ranks tab", () => {
  it("has one game switcher, opens on the first game whatever the site's saved game, and a League pick switches every block", async () => {
    await act(async () => {
      root.render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <TooltipProvider>
            <PersonHubPage />
          </TooltipProvider>
        </QueryClientProvider>
      );
    });
    await settle();

    expect(tablists()).toHaveLength(1);
    expect(selectedGame()).toContain("Overwatch");
    expect(ranksRead("overwatch").map((params) => params.layer)).toEqual(
      expect.arrayContaining([undefined, ["registration", "tournament", "casual"]])
    );
    expect(getRankCollectionStatus).toHaveBeenLastCalledWith(42, "overwatch");
    expect(container.querySelector("[data-rank-history=overwatch]")).not.toBeNull();

    const league = tablists()[0]?.querySelector<HTMLElement>('[role="tab"]:not([aria-selected="true"])');
    await act(async () => league?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    await settle();

    expect(navigation.current()).toBe("/admin/people/42?tab=ranks&discipline=lol");
    expect(tablists()).toHaveLength(1);
    expect(selectedGame()).toContain("League of Legends");
    expect(ranksRead("lol").map((params) => params.layer)).toEqual(
      expect.arrayContaining([undefined, ["registration", "tournament", "casual"]])
    );
    expect(getRankCollectionStatus).toHaveBeenLastCalledWith(42, "lol");
    // League collects its own native ranks: its own history, never Overwatch's.
    expect(container.querySelector("[data-rank-history=lol]")).not.toBeNull();
    expect(container.querySelector("[data-rank-history=overwatch]")).toBeNull();
  });
});
